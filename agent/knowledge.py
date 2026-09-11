"""Local knowledge: allowlisted docs index + keyword search + extractive summary.

Defaults (no deps, local-only):
- Disabled until BUTLER_DOC_PATHS is set (colon-separated dirs/files).
- Indexes .txt/.md natively; .pdf via lazy pypdf (skipped with debug log).
- Index stored at BUTLER_DOC_INDEX (default data/docs.jsonl).
- Vector upgrade: BUTLER_VECTOR=chroma + installed chromadb -> ChromaStore,
  else KeywordStore. Same interface so callers don't change (Phase 4).

Security: only paths inside the allowlist are ever read; symlinks resolved
and re-checked; max file 2MB, max 2000 files.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re

logger = logging.getLogger("butler-agent.knowledge")

MAX_FILE_BYTES = 2_000_000
MAX_FILES = 2000
TEXT_EXTS = {".txt", ".md", ".markdown"}


def doc_paths() -> list[pathlib.Path]:
    raw = os.getenv("BUTLER_DOC_PATHS", "")
    out = []
    for part in (raw or "").split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(pathlib.Path(os.path.expanduser(part)).resolve())
        except OSError:
            continue
    return out


def doc_index_path() -> str:
    return os.getenv("BUTLER_DOC_INDEX", "data/docs.jsonl")


def _read_text_file(path: pathlib.Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _read_pdf(path: pathlib.Path) -> str | None:
    try:
        import pypdf  # type: ignore
    except ImportError:
        try:
            import PyPDF2 as pypdf  # type: ignore
        except ImportError:
            logger.debug("pdf skipped (no pypdf installed): %s", path)
            return None
    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)[:20000]
    except Exception:
        logger.debug("pdf read failed: %s", path, exc_info=True)
        return None


def collect_documents() -> list[dict]:
    roots = doc_paths()
    if not roots:
        return []
    docs: list[dict] = []
    for root in roots:
        try:
            targets = [root] if root.is_file() else sorted(root.rglob("*"))
        except OSError:
            continue
        for p in targets:
            if len(docs) >= MAX_FILES:
                break
            try:
                rp = p.resolve()
            except OSError:
                continue
            if not any(str(rp).startswith(str(r)) for r in roots):
                continue
            if not rp.is_file():
                continue
            suf = rp.suffix.lower()
            if suf in TEXT_EXTS:
                text = _read_text_file(rp)
            elif suf == ".pdf":
                text = _read_pdf(rp)
            else:
                continue
            if text and text.strip():
                docs.append({"path": str(rp), "text": text.strip()[:20000]})
    return docs


def write_index(docs: list[dict] | None = None, path: str | None = None) -> int:
    docs = docs if docs is not None else collect_documents()
    dest = path or doc_index_path()
    try:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            for d in docs:
                fh.write(json.dumps(d) + "\n")
    except OSError:
        return 0
    return len(docs)


def _load_index(path: str | None = None) -> list[dict]:
    try:
        with open(path or doc_index_path(), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []


def _score(text: str, terms: list[str]) -> int:
    low = text.lower()
    return sum(low.count(t) for t in terms)


def search_docs(query: str, limit: int = 3) -> list[dict]:
    terms = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 2]
    if not terms:
        return []
    # Vector backend when explicitly enabled + installed (lazy).
    if (os.getenv("BUTLER_VECTOR", "") or "").lower() == "chroma":
        vec = _chroma_search(query, limit)
        if vec is not None:
            return vec
    rows = _load_index() or collect_documents()
    scored = sorted(((_score(d.get("text", ""), terms), d) for d in rows),
                    key=lambda x: -x[0])
    out = []
    for score, d in scored[:limit]:
        if score <= 0:
            continue
        idx = d["text"].lower().find(terms[0])
        snippet = d["text"][max(0, idx - 120): idx + 240].strip()
        out.append({"path": d["path"], "score": score, "snippet": snippet})
    return out


def _chroma_search(query: str, limit: int) -> list[dict] | None:
    try:
        import chromadb  # type: ignore
    except ImportError:
        return None
    try:
        client = chromadb.PersistentClient(path=os.getenv("BUTLER_CHROMA_DIR", "data/chroma"))
        col = client.get_or_create_collection("butler_docs")
        if col.count() == 0:
            for i, d in enumerate(_load_index() or collect_documents()):
                col.add(ids=[f"d{i}"], documents=[d["text"][:8000]],
                        metadatas=[{"path": d["path"]}])
        res = col.query(query_texts=[query], n_results=limit)
        out = []
        for doc, meta in zip(res.get("documents", [[]])[0], res.get("metadatas", [[]])[0]):
            out.append({"path": meta.get("path", ""), "score": 1, "snippet": doc[:360]})
        return out
    except Exception:
        logger.debug("chroma search failed, falling back", exc_info=True)
        return None


def summarize_text(text: str, query: str = "", max_sentences: int = 3) -> str:
    sents = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    sents = [s.strip() for s in sents if len(s.strip()) > 20]
    if not sents:
        return (text or "").strip()[:500]
    terms = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    if terms:
        ranked = sorted(sents, key=lambda s: -_score(s, terms))
        picked = [s for s in ranked[:max_sentences] if _score(s, terms) > 0] or sents[:max_sentences]
    else:
        picked = sents[:max_sentences]
    return " ".join(picked)[:1200]


def summarize_doc(query: str) -> dict | None:
    hits = search_docs(query, limit=1)
    if not hits:
        return None
    full = ""
    for d in _load_index():
        if d.get("path") == hits[0]["path"]:
            full = d.get("text", "")
            break
    full = full or hits[0].get("snippet", "")
    return {"path": hits[0]["path"], "summary": summarize_text(full, query)}
