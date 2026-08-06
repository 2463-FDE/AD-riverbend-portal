"""Render a Mermaid-bearing HTML fragment to a verified single-page PDF.

Invoked by render.sh. See SKILL.md for the why; this file is the how.

Two passes, because the page height is not knowable until Mermaid has laid the
diagram out:

  pass 1  wrap the fragment, render headless, assert the diagram parsed, and read
          document.body.scrollHeight back out of the page title
  pass 2  re-render with @page sized to that height so the PDF is one continuous
          page instead of being sliced at A4 boundaries, then assert page count

Every filesystem mutation is announced, gated behind --dry-run, and refuses to
clobber an existing output unless --force. That is not ceremony: a --clear-cache
flag in an earlier generator here destroyed the live artifact it was meant to
refresh, and this script writes into the repo's deliverables.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BUNDLE = os.path.expanduser("~/.claude/vendor/mermaid.min.js")
BUNDLE_URL = "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"

# Mermaid does not raise on a bad graph; it swaps in an error SVG whose text
# contains these. A "successful" render that silently contains one of them is
# the failure mode this script exists to make impossible.
ERROR_MARKERS = ("syntax error", "error in text", "mermaid version")

# Pass 1 reports the laid-out height through the title, which --dump-dom gives us
# for free. Waiting on a fixed timer rather than a promise keeps this working
# whether the fragment uses mermaid.run() or startOnLoad.
PASS1_TAIL = """
<script src="{bundle}"></script>
<script>
  mermaid.initialize({{ startOnLoad: true, theme: "default", flowchart: {{ useMaxWidth: false }} }});
  setTimeout(function () {{
    document.title = "MEASURED_H=" + document.body.scrollHeight;
  }}, 4000);
</script>
"""

PASS2_HEAD = """
<style>
  @page {{ size: {width}px {height}px; margin: 0; }}
  html, body {{ width: {width}px; }}
  .wrap {{ max-width: {inner}px !important; }}
  .diagram {{ overflow: visible !important; }}
</style>
"""


def log(message: str) -> None:
    print(f"  {message}", file=sys.stderr)


def is_full_document(source: str) -> bool:
    """True if the source already carries its own document scaffolding.

    Script and style bodies are stripped first: a JS comment mentioning
    ``<html>`` used to flip a fragment onto the injecting path, which silently
    dropped the ``data-theme="light"`` the wrapper adds and printed the whole
    artifact in dark theme. The misdetection is invisible in the log line, so
    the cheapest place to stop it is here.
    """
    stripped = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1\s*>", "", source, flags=re.I | re.S
    )
    return bool(re.search(r"<!doctype|<html\b|<body\b", stripped, re.I))


def wrap(source: str, *, bundle: str, extra_head: str = "") -> str:
    """Produce a self-contained render document.

    Two input shapes are in use here and they must be handled differently:

    * **Fragment** — a bare <title>/<style> plus body markup, no doctype and no
      loader. This is what the Artifact tool expects and what the diagram files
      are. It gets a document built around it.
    * **Full document** — already has <html>/<head>/<body>. Wrapping one of these
      nests a second <head> inside the first, which browsers recover from by
      relocating nodes; the layout shifts and the PDF comes out a page short.
      Inject into the existing document instead of rebuilding it.
    """
    tail = PASS1_TAIL.format(bundle=bundle)
    if not is_full_document(source):
        return (
            '<!doctype html><html data-theme="light"><head>'
            '<meta charset="utf-8">'
            f"{extra_head}{source}"
            f"</head><body>{tail}</body></html>"
        )

    out = source
    if extra_head:
        if re.search(r"</head\s*>", out, re.I):
            out = re.sub(r"</head\s*>", extra_head + "</head>", out, count=1, flags=re.I)
        else:  # no explicit head; put it before the first body content
            out = extra_head + out
    if re.search(r"</body\s*>", out, re.I):
        out = re.sub(r"</body\s*>", tail + "</body>", out, count=1, flags=re.I)
    else:
        out = out + tail
    return out


def ensure_bundle(dry_run: bool) -> str:
    if os.path.isfile(BUNDLE) and os.path.getsize(BUNDLE) > 1_000_000:
        log(f"bundle present: {BUNDLE} ({os.path.getsize(BUNDLE) // 1024} KB)")
        return BUNDLE
    log(f"WRITE {BUNDLE}  <- download {BUNDLE_URL}")
    if dry_run:
        return BUNDLE
    os.makedirs(os.path.dirname(BUNDLE), exist_ok=True)
    with urllib.request.urlopen(BUNDLE_URL, timeout=120) as response:
        data = response.read()
    if len(data) < 1_000_000:
        sys.exit(f"error: downloaded bundle is only {len(data)} bytes; refusing to use it")
    with open(BUNDLE, "wb") as handle:
        handle.write(data)
    log(f"bundle downloaded: {len(data) // 1024} KB")
    return BUNDLE


def chrome(args: list[str], *, timeout: int = 180) -> str:
    if not os.path.exists(CHROME):
        sys.exit(f"error: Chrome not found at {CHROME}")
    proc = subprocess.run(
        [CHROME, "--headless", "--disable-gpu", "--no-sandbox", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout


def pdf_page_count(path: str) -> int:
    """Chrome writes /Type /Page and /Type /Pages; the latter is the page tree,
    not a page. Spacing varies by writer, so match both forms."""
    data = open(path, "rb").read()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fragment", help="HTML fragment to render")
    parser.add_argument("--out", required=True, help="output PDF path")
    parser.add_argument("--width", type=int, default=1188, help="page width in px")
    parser.add_argument("--inner", type=int, default=1140, help=".wrap max-width in px")
    parser.add_argument("--pad", type=int, default=50, help="px added to measured height")
    parser.add_argument("--paged", action="store_true",
                        help="let content flow across pages instead of forcing one tall "
                             "page (use for phone-width specimens)")
    parser.add_argument("--page-height", type=int, default=844,
                        help="page height in px when --paged (default: iPhone-ish 844)")
    parser.add_argument("--expect-pages", default="1",
                        help="page count to assert, or 'any' (default: 1)")
    parser.add_argument("--expect", action="append", default=[],
                        help="text that must appear in the rendered DOM; repeatable")
    parser.add_argument("--dry-run", action="store_true",
                        help="print every filesystem mutation and exit without doing any")
    parser.add_argument("--force", action="store_true", help="allow overwriting --out")
    parser.add_argument("--keep", action="store_true", help="keep the temp work dir")
    args = parser.parse_args()

    if not os.path.isfile(args.fragment):
        sys.exit(f"error: no such fragment: {args.fragment}")
    out = os.path.abspath(args.out)
    if os.path.exists(out) and not args.force and not args.dry_run:
        sys.exit(f"error: {out} exists. Re-run with --force to overwrite it.")

    fragment = open(args.fragment, encoding="utf-8").read()
    log("input shape: " + ("full document (injecting)" if is_full_document(fragment)
                           else "fragment (wrapping)"))

    bundle = ensure_bundle(args.dry_run)
    work = tempfile.mkdtemp(prefix="render-pdf-")
    log(f"WRITE {work}/pass1.html")
    log(f"WRITE {work}/pass2.html")
    log(f"WRITE {out}" + (" (overwrite)" if os.path.exists(out) else ""))
    if args.dry_run:
        log("dry run: nothing written, no Chrome invoked")
        shutil.rmtree(work, ignore_errors=True)
        return 0

    try:
        # ---- pass 1: parse-verify and measure -------------------------------
        pass1 = os.path.join(work, "pass1.html")
        with open(pass1, "w", encoding="utf-8") as handle:
            handle.write(wrap(fragment, bundle=bundle))
        dom = chrome(["--virtual-time-budget=8000", "--dump-dom", f"file://{pass1}"])

        # Only demand an SVG when the source actually asks for a diagram. Design
        # specimens are rendered through this same path and legitimately have none.
        wants_diagram = bool(re.search(r'class="mermaid"|```mermaid', fragment))
        if wants_diagram and dom.count("<svg") < 1:
            sys.exit("error: no <svg> in rendered DOM — Mermaid did not run at all")
        low = dom.lower()
        hit = [m for m in ERROR_MARKERS if m in low]
        if hit:
            sys.exit(f"error: Mermaid rendered an error diagram (markers: {', '.join(hit)})")
        missing = [text for text in args.expect if text not in dom]
        if missing:
            sys.exit("error: rendered DOM is missing expected content: "
                     + ", ".join(repr(m) for m in missing)
                     + " — likely a partial render, not a clean one")

        match = re.search(r"MEASURED_H=(\d+)", dom)
        if not match:
            sys.exit("error: could not read measured height from the page title")
        measured = int(match.group(1))
        # One continuous page: PDF page count is ceil(content / page height), so a
        # page taller than the content yields exactly one. --paged opts out, for
        # phone-sized specimens that are meant to flow across pages.
        height = args.page_height if args.paged else measured + args.pad
        log(f"pass 1 OK: {dom.count('<svg')} svg, 0 error markers, "
            f"content {measured}px, page {args.width}x{height}px")

        # ---- pass 2: PDF ----------------------------------------------------
        pass2 = os.path.join(work, "pass2.html")
        head = PASS2_HEAD.format(width=args.width, height=height, inner=args.inner)
        with open(pass2, "w", encoding="utf-8") as handle:
            handle.write(wrap(fragment, bundle=bundle, extra_head=head))
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        chrome([
            "--virtual-time-budget=8000",
            "--no-pdf-header-footer",
            f"--print-to-pdf={out}",
            f"file://{pass2}",
        ])
        if not os.path.isfile(out):
            sys.exit("error: Chrome produced no PDF")

        pages = pdf_page_count(out)
        size_kb = os.path.getsize(out) // 1024
        log(f"pass 2 OK: {out} ({size_kb} KB, {pages} page{'s' if pages != 1 else ''})")
        if args.expect_pages != "any" and pages != int(args.expect_pages):
            sys.exit(f"error: expected {args.expect_pages} page(s), got {pages}. "
                     f"For one continuous page raise --pad, or check the fragment has no "
                     f"fixed-height container clipping content. For a paged render pass "
                     f"--expect-pages {pages} once you have confirmed that is right.")
        print(f"{out}\t{pages} page(s)\t{args.width}x{height}px\t{size_kb} KB")
        return 0
    finally:
        if args.keep:
            log(f"work dir kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
