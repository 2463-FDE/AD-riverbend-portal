"""
eligibility-assistant `corpus` — the corpus boundary (SPEC-7 / SPEC-8 / SPEC-38).

Every test opens with the rig's identity assertions (eligibility-assistant-D-66) so the
loader, the tool and the app under test are one pinned module set.
"""
import hashlib
import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

from a1_corpus_rig import app_mod, assert_pinned, policy_index

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO_ROOT, "services", "ai-assistant", "policy_corpus")
FIX_NEG_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "a1", "fix_neg")
EVAL_JSONL = os.path.join(REPO_ROOT, "tests", "fixtures", "a1", "eligibility-assistant-evaluations.jsonl")
ROOT_FILES = {"document-manifest.json", "index.json"}
EXEMPT_NAME = ".DS_Store"
FIX_NEG_IDS = sorted(f[:-3] for f in os.listdir(FIX_NEG_DIR) if f.startswith("FIX-NEG-"))


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _manifest(root: str = CORPUS) -> list:
    with open(os.path.join(root, "document-manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["documents"]


def _walk(root: str) -> list:
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            out.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(out)


def _copy_corpus(tmp_path) -> str:
    dst = str(tmp_path / "policy_corpus")
    shutil.copytree(CORPUS, dst)
    return dst


def _snapshot():
    return (policy_index._INDEX, policy_index.MAX_ROW_BYTES)


def _same(before, after):
    return before[0] is after[0] and before[1] is after[1]


def test_manifest_sha_pinned():
    assert_pinned(with_app=True)
    rows = _manifest()
    assert len(rows) == 87
    by_path = {r["path"]: r for r in rows}
    seen = set()
    for rel in _walk(CORPUS):
        if os.path.basename(rel) == EXEMPT_NAME:
            continue
        if rel in ROOT_FILES:
            continue
        assert rel in by_path, f"unlisted file under policy_corpus/: {rel}"
        assert _sha(os.path.join(CORPUS, rel)) == by_path[rel]["content_sha256"], rel
        seen.add(rel)
    assert seen == set(by_path), "manifest rows with no vendored file"
    # the loader enforces the same rule in code, before any lookup
    index = policy_index.load()
    assert len(index.rows) == 87
    assert policy_index._INDEX is index


@pytest.mark.parametrize("case_id", ["EVAL-031"])
def test_eval_031_fixture_isolation(case_id):
    assert_pinned()
    with open(EVAL_JSONL, encoding="utf-8") as fh:
        cases = {json.loads(line)["id"]: json.loads(line) for line in fh if line.strip()}
    assert cases[case_id]["category"] == "negative-fixture-isolation"
    manifest_ids = {r["document_id"] for r in _manifest()}
    manifest_shas = {r["content_sha256"] for r in _manifest()}
    with open(os.path.join(CORPUS, "index.json"), encoding="utf-8") as fh:
        index_ids = {e["document_id"] for e in json.load(fh)}
    vendored = _walk(CORPUS)
    vendored_shas = {_sha(os.path.join(CORPUS, rel)) for rel in vendored}
    loaded_ids = {row.id for row in policy_index._INDEX.rows}
    assert len(FIX_NEG_IDS) == 7
    for fid in FIX_NEG_IDS:
        assert fid not in manifest_ids
        assert fid not in index_ids
        assert fid not in loaded_ids
        assert not any(fid in rel for rel in vendored)
        fsha = _sha(os.path.join(FIX_NEG_DIR, fid + ".md"))
        assert fsha not in manifest_shas
        assert fsha not in vendored_shas


@pytest.mark.parametrize("fid", FIX_NEG_IDS)
def test_fix_neg_negative(fid):
    assert_pinned()
    with open(os.path.join(FIX_NEG_DIR, fid + ".md"), encoding="utf-8") as fh:
        text = fh.read()
    # a fixture id is not a document the by-id entry will serve
    with pytest.raises(ValueError):
        policy_index.fetch_by_id([fid])
    with pytest.raises(ValueError):
        policy_index.fetch_by_id(["DOC-SYN-NO-INVENTION", fid])
    # its text never appears in any row the retriever can return
    marker_lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 40][:3]
    assert marker_lines
    for category in policy_index._INDEX.categories:
        for row in policy_index.lookup(category, "medicare", "unconfirmed", "unconfirmed"):
            assert row.id != fid
            for marker in marker_lines:
                assert marker not in row.section_text
    for row in policy_index._INDEX.rows:
        assert row.section_text != text


def test_non_approved_row_fails_load(tmp_path):
    assert_pinned()
    # leg 1: a non-approved row raises the loader's own error before any lookup
    root = _copy_corpus(tmp_path / "pending")
    mpath = os.path.join(root, "document-manifest.json")
    with open(mpath, encoding="utf-8") as fh:
        manifest = json.load(fh)
    manifest["documents"][0]["approval_status"] = "pending"
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    before = _snapshot()
    with pytest.raises(policy_index.CorpusLoadError):
        policy_index.load(root=root)
    assert _same(before, _snapshot())
    # leg 2: the one exempt name loads clean, and module state is untouched
    root2 = _copy_corpus(tmp_path / "dsstore")
    with open(os.path.join(root2, "documents", EXEMPT_NAME), "wb") as fh:
        fh.write(b"\x00")
    before = _snapshot()
    index = policy_index.load(root=root2)
    assert len(index.rows) == 87
    assert _same(before, _snapshot())
    # and any other unlisted name at any depth raises
    root3 = _copy_corpus(tmp_path / "rogue")
    os.makedirs(os.path.join(root3, "notes"))
    with open(os.path.join(root3, "notes", "rogue.md"), "w", encoding="utf-8") as fh:
        fh.write("x")
    with pytest.raises(policy_index.CorpusLoadError):
        policy_index.load(root=root3)


def test_load_with_root_does_not_publish_module_state(tmp_path):
    assert_pinned()
    default_index = policy_index.load()
    assert policy_index._INDEX is default_index
    assert policy_index.MAX_ROW_BYTES == 2789
    root = _copy_corpus(tmp_path / "truncated")
    target = "DOC-SYN-NO-INVENTION"
    manifest_path = os.path.join(root, "document-manifest.json")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    row = next(r for r in manifest["documents"] if r["document_id"] == target)
    fpath = os.path.join(root, row["path"])
    with open(fpath, encoding="utf-8") as fh:
        original = fh.read()
    truncated = original[: len(original) // 2]
    with open(fpath, "w", encoding="utf-8") as fh:
        fh.write(truncated)
    row["content_sha256"] = hashlib.sha256(truncated.encode("utf-8")).hexdigest()
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)
    variant = policy_index.load(root=root)
    assert next(r for r in variant.rows if r.id == target).section_text == truncated
    assert policy_index._INDEX is default_index
    assert policy_index.MAX_ROW_BYTES == 2789
    assert policy_index.fetch_by_id([target])[0].section_text == original
    served = policy_index.lookup("no-coverage-invention", "aetna", "commercial", "other_us")
    assert [r.id for r in served] == [target]
    assert served[0].section_text == original


def test_startup_hook_fails_boot_on_corpus_error(monkeypatch):
    assert_pinned(with_app=True)

    def _boom(root=None):
        raise policy_index.CorpusLoadError("sha mismatch (test)")

    monkeypatch.setattr(policy_index, "load", _boom)
    with pytest.raises(policy_index.CorpusLoadError):
        with TestClient(app_mod.app):
            pytest.fail("lifespan entered with a broken corpus")
    monkeypatch.undo()
    with TestClient(app_mod.app) as client:
        assert client.get("/healthz").status_code in (200, 404)
