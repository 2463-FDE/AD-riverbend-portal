---
name: render-pdf
description: Render an HTML fragment or full-document design/diagram artifact (Mermaid included) to a PDF, with the render verified rather than assumed - the diagram is proven to have parsed, expected content is proven present, and the page count is asserted. Use when asked to render, regenerate, or PDF a docs/design specimen or a wN diagram, or to produce a phone-readable version of one for review.
---

# render-pdf

Renders the HTML artifacts in this repo (`w4-multiagent.html`, `docs/design/*.html`) to
PDF offline, and **verifies the render before reporting success**.

The verification is the point. Mermaid does not fail loudly — a malformed graph renders a
grey error box containing "Syntax error in text", and Chrome prints it to PDF as
cheerfully as a correct diagram. A render pipeline without a parse assertion produces a
plausible-looking artifact that is wrong, and this exact procedure was re-derived from
scratch across four sessions before it was written down here.

## Run it

```bash
# single continuous page — diagrams (the default)
bash .claude/skills/render-pdf/render.sh w4-multiagent.html \
  --out W4-Multi-Agent-Patient-View-Assembly.pdf \
  --expect "Patient-View" --force

# phone-readable, flows across pages — design specimens
bash .claude/skills/render-pdf/render.sh docs/design/05-token-directions.html \
  --out docs/design/05-token-directions-mobile.pdf \
  --width 391 --inner 359 --paged --page-height 1500 --expect-pages any --force
```

| Flag | Why it exists |
|---|---|
| `--expect TEXT` | Repeatable. Text that must be in the rendered DOM. **Pass at least one label that only appears if the diagram rendered fully** — it is the only check that separates a complete render from a partial one. |
| `--expect-pages N \| any` | Asserted page count, default `1`. Use `any` on a first paged run, then pin the number you confirmed. |
| `--paged` / `--page-height` | Opt out of one-tall-page, for phone-width specimens. |
| `--width` / `--inner` | Page width and `.wrap` max-width in px. |
| `--pad` | Px added to measured height in single-page mode. Raise it if you get 2 pages. |
| `--dry-run` | Prints every filesystem mutation and exits, touching nothing. |
| `--force` | Required to overwrite an existing `--out`. |
| `--keep` | Keeps the temp work dir for inspecting the generated `pass1/pass2.html`. |

Report the tab-separated summary line it prints on success — path, pages, geometry, size.
If it exits non-zero there is no artifact; do not describe one.

## How it works, and why it is two passes

Page height is unknowable until Mermaid has laid the diagram out, so:

1. **Pass 1 — verify and measure.** Build a self-contained document, render headless,
   then assert: an `<svg>` exists (only if the source actually contains a Mermaid block),
   none of `syntax error` / `error in text` / `mermaid version` appear, and every
   `--expect` string is present. Height is read back via `document.title`, which
   `--dump-dom` surfaces for free.
2. **Pass 2 — print.** Re-render with `@page { size: <width>px <height>px }`. PDF page
   count is `ceil(content / page height)`, so a page taller than the content gives exactly
   one. Then assert the page count actually came out as expected.

## Things that will bite you

- **Two input shapes, handled differently.** Every artifact in this repo today — the
  diagram files *and* `docs/design/*.html` — is a *fragment*: bare `<title>`/`<style>` plus
  body markup, no doctype, no loader, the shape the Artifact tool expects. Fragments get a
  document built around them, which is also where `data-theme="light"` comes from. A real
  full document must be injected into instead: wrapping one nests a second `<head>`, the
  browser relocates nodes, and the PDF comes out a page short. The script detects the shape
  and logs which path it took; check that line if output looks off.
- **Shape detection reads the source, so prose about HTML can flip it.** `is_full_document`
  greps for `<!doctype` / `<html` / `<body`, and until 2026-07-31 it matched those inside
  `<script>` and `<style>` bodies. A JS comment reading "sets data-fontset on `<html>`" and
  a CSS comment reading "do not add `<!doctype>`/`<html>` wrappers" each pushed a fragment
  onto the injecting path — which silently drops `data-theme="light"` and prints the whole
  artifact in dark theme. Script and style bodies are stripped before the match now, but the
  log line is still the only place the choice is visible: **read it on every run.**
- **The Mermaid bundle lives outside the repo,** at `~/.claude/vendor/mermaid.min.js`
  (~3.4 MB), downloaded on first run. **Never commit it.** It previously lived in a
  session scratchpad, which is why the procedure kept getting re-derived — scratchpads are
  ephemeral, and the bundle vanished with them.
- **Page count is not derivable from content height in `--paged` mode.** Print-media
  reflow changes line breaking, so `ceil(height / page)` under-predicts. Run once with
  `--expect-pages any`, confirm the PDF by eye, then pin the number.
- **Do not diagnose a visual problem from a downscaled screenshot.** That cost a long
  detour chasing a "dark button" that did not exist while the real fault was a quoted font
  name inside a `style` attribute. Inspect the generated `pass2.html` (`--keep`) or the
  computed styles instead. The `PostToolUse` syntax hook now catches that specific
  nested-quote break at edit time.
- **Chrome path is hardcoded** to `/Applications/Google Chrome.app/...`; there is no
  puppeteer or `mmdc` here.

## Known non-reproduction

`docs/design/05-token-directions-mobile.pdf` is committed at 11 pages. Re-rendering the
current `05-token-directions.html` at that PDF's own geometry (391×1500 px, read out of its
`MediaBox`) yields **10** pages. The source has been edited since the PDF was produced, and
the original invocation was never recorded. Treat 10 as correct for today's source; this
entry exists so nobody re-investigates it as a regression. Record the flags used whenever a
rendered artifact is committed.

One **untested** candidate cause, worth a look before anyone re-opens this: that PDF was
produced while the shape-detection bug above was live, so `05-token-directions.html` — a
fragment whose CSS comment names `<!doctype>` — was rendering on the injecting path. Nobody
has re-rendered it since the fix.

## Flags used for committed artifacts

```bash
# docs/design/06-p2-mockups.pdf — 1 page, 1060x10701px (2026-08-01)
# Re-render after the type set moved A -> E (05-design-tokens.md §3). Height grew from
# 10341px because the rationale list gained the reasoning; geometry flags are unchanged.
# The last two --expect strings exist only in the post-change source, so they are what
# proves the PDF is not a stale re-print of the previous board.
bash .claude/skills/render-pdf/render.sh docs/design/06-p2-mockups.html \
  --out docs/design/06-p2-mockups.pdf --width 1060 --inner 1000 \
  --expect "The five type sets, side by side" --expect "CHARTER/CAMBRIA" \
  --expect "NO SERIF — SYSTEM UI" --expect "Charter serif" \
  --expect "unconfirmed, not refused" --expect "What these plates do not show" \
  --expect "Chosen 2026-08-01" --expect "Nothing here is decided — superseded" --force
```

**Pin a content-bearing `--expect` when re-rendering after an edit.** The six original
strings all survived the A→E change — including `"Charter serif"`, which matched both the
old button label and the new `"E · Charter serif — chosen"`. A run asserting only those
would have passed against the *old* HTML just as happily. An expect string that postdates
the edit is the only assertion that distinguishes a fresh render from a stale one.
