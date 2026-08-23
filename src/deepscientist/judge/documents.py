from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .schemas import PaperJudgeError


_PLAIN_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".tex", ".rst"}


def load_judge_document(path: Path, *, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    if not path.exists() or not path.is_file():
        raise PaperJudgeError(f"Paper judge target does not exist: {path}")
    suffix = path.suffix.lower()
    cfg = dict(config or {})
    if suffix == ".pdf":
        pdf_cfg = dict(cfg.get("pdf") or {}) if isinstance(cfg.get("pdf"), dict) else {}
        if pdf_cfg.get("enabled") is False:
            raise PaperJudgeError("PDF judging is disabled by the judge.pdf.enabled setting.")
        return extract_pdf_text(path, config=pdf_cfg)
    if suffix not in _PLAIN_TEXT_SUFFIXES:
        raise PaperJudgeError(
            f"Unsupported paper judge target format: {suffix or 'no extension'}. "
            "Use PDF, Markdown, text, LaTeX, or reStructuredText."
        )
    max_chars = _positive_int(cfg.get("target_sample_chars"), 120000)
    text = path.read_text(encoding="utf-8", errors="ignore")
    sample = text[:max_chars]
    return sample, {
        "format": suffix.lstrip("."),
        "sha256": _sha256(path),
        "file_size_bytes": path.stat().st_size,
        "characters_extracted": len(text),
        "characters_in_sample": len(sample),
        "truncated": len(sample) < len(text),
        "warnings": [],
    }


def extract_pdf_text(path: Path, *, config: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    cfg = dict(config or {})
    max_file_mb = _positive_float(cfg.get("max_file_mb"), 50.0)
    max_pages = _positive_int(cfg.get("max_pages"), 80)
    max_chars = _positive_int(cfg.get("max_chars"), 120000)
    min_chars_per_page = _positive_int(cfg.get("min_text_chars_per_page"), 40)
    file_size = path.stat().st_size
    if file_size > int(max_file_mb * 1024 * 1024):
        raise PaperJudgeError(
            f"PDF is too large for paper judge extraction ({file_size} bytes).",
            details={"max_file_mb": max_file_mb, "path": str(path)},
        )
    try:
        reader = PdfReader(str(path), strict=False)
    except (PdfReadError, OSError, ValueError) as exc:
        raise PaperJudgeError("Paper judge could not read the PDF.", details={"error": str(exc)}) from exc
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise PaperJudgeError("The PDF is encrypted and cannot be read without a password.") from exc
        if not unlocked:
            raise PaperJudgeError("The PDF is encrypted and cannot be read without a password.")

    page_count = len(reader.pages)
    if page_count == 0:
        raise PaperJudgeError("The PDF contains no pages.")
    selected_indexes = _select_page_indexes(page_count, max_pages=max_pages)
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index in selected_indexes:
        try:
            text = str(reader.pages[index].extract_text() or "")
        except Exception as exc:
            text = ""
            warnings.append(f"Page {index + 1} text extraction failed: {exc}")
        normalized = _normalize_extracted_text(text)
        pages.append({"page": index + 1, "text": normalized, "characters": len(normalized)})

    extracted_characters = sum(int(page["characters"]) for page in pages)
    nonempty_pages = sum(1 for page in pages if int(page["characters"]) >= min_chars_per_page)
    average_chars = extracted_characters / max(len(pages), 1)
    suspected_scanned = nonempty_pages == 0 or average_chars < min_chars_per_page
    if suspected_scanned:
        raise PaperJudgeError(
            "The PDF contains too little extractable text and is likely scanned. OCR is not enabled in this release.",
            details={
                "page_count": page_count,
                "selected_pages": [index + 1 for index in selected_indexes],
                "characters_extracted": extracted_characters,
                "minimum_characters_per_page": min_chars_per_page,
            },
        )
    if len(selected_indexes) < page_count:
        warnings.append(f"Selected {len(selected_indexes)} of {page_count} pages because judge.pdf.max_pages is {max_pages}.")
    sample = _sample_pages(pages, max_chars=max_chars)
    metadata = {
        "format": "pdf",
        "parser": "pypdf",
        "sha256": _sha256(path),
        "file_size_bytes": file_size,
        "page_count": page_count,
        "selected_pages": [index + 1 for index in selected_indexes],
        "extracted_page_count": len(pages),
        "nonempty_page_count": nonempty_pages,
        "characters_extracted": extracted_characters,
        "characters_in_sample": len(sample),
        "truncated": len(sample) < sum(len(_page_block(page)) for page in pages),
        "is_encrypted": bool(reader.is_encrypted),
        "suspected_scanned": False,
        "warnings": warnings,
        "pages": [{"page": page["page"], "characters": page["characters"]} for page in pages],
    }
    return sample, metadata


def _select_page_indexes(page_count: int, *, max_pages: int) -> list[int]:
    if page_count <= max_pages:
        return list(range(page_count))
    if max_pages == 1:
        return [0]
    indexes = {0, page_count - 1}
    for slot in range(1, max_pages - 1):
        indexes.add(round(slot * (page_count - 1) / (max_pages - 1)))
    if len(indexes) < max_pages:
        for index in range(page_count):
            indexes.add(index)
            if len(indexes) == max_pages:
                break
    return sorted(indexes)[:max_pages]


def _sample_pages(pages: list[dict[str, Any]], *, max_chars: int) -> str:
    blocks = [_page_block(page) for page in pages]
    complete = "\n\n".join(blocks).strip()
    if len(complete) <= max_chars:
        return complete
    separator_budget = max(0, 2 * (len(blocks) - 1))
    per_page = max(1, (max_chars - separator_budget) // max(len(blocks), 1))
    sampled = "\n\n".join(block[:per_page] for block in blocks).strip()
    return sampled[:max_chars]


def _page_block(page: dict[str, Any]) -> str:
    return f"--- Page {page['page']} ---\n{page['text']}".strip()


def _normalize_extracted_text(value: str) -> str:
    lines = [" ".join(line.replace("\x00", "").split()) for line in value.splitlines()]
    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank
    return "\n".join(normalized).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
