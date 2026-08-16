from __future__ import annotations

from pathlib import Path

from ..shared import require_yaml


def load_markdown_document_from_text(text: str) -> tuple[dict, str]:
    require_yaml()
    import yaml

    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text
    metadata = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    return metadata, body


def load_markdown_document(path: Path) -> tuple[dict, str]:
    return load_markdown_document_from_text(path.read_text(encoding="utf-8"))


def load_markdown_metadata(path: Path) -> dict:
    require_yaml()
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        if handle.readline() != "---\n":
            return {}
        frontmatter_lines: list[str] = []
        for line in handle:
            if line == "---\n":
                break
            frontmatter_lines.append(line)
        else:
            return {}
    return yaml.safe_load("".join(frontmatter_lines)) or {}


def dump_markdown_document(metadata: dict, body: str) -> str:
    require_yaml()
    import yaml

    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    body = body.rstrip() + "\n"
    return f"---\n{frontmatter}\n---\n{body}"
