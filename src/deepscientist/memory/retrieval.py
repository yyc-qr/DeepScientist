from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from rank_bm25 import BM25Okapi

STRUCTURED_MEMORY_FIELDS = (
    "task_family",
    "stage",
    "mechanism_family",
    "failure_mode",
    "metric_id",
    "outcome",
    "metric_delta",
    "candidate_id",
    "evidence_paths",
)
LIST_FIELDS = {"evidence_paths"}
TEXT_FIELDS = {"task_family", "stage", "mechanism_family", "failure_mode", "metric_id", "outcome", "candidate_id"}
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw = list(value)
    else:
        raw = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        item_text = _text(item)
        if item_text and item_text not in seen:
            normalized.append(item_text)
            seen.add(item_text)
    return normalized


def normalize_structured_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(metadata or {})
    result: dict[str, Any] = {}
    for field in STRUCTURED_MEMORY_FIELDS:
        value = source.get(field)
        if field in LIST_FIELDS:
            normalized = normalize_list(value)
            if normalized:
                result[field] = normalized
        elif field == "metric_delta":
            if isinstance(value, bool):
                result[field] = float(value)
            elif isinstance(value, (int, float)):
                result[field] = float(value)
            elif isinstance(value, Mapping):
                result[field] = dict(value)
            elif _text(value):
                try:
                    result[field] = float(str(value).strip())
                except ValueError:
                    result[field] = _text(value)
        elif field in TEXT_FIELDS:
            normalized = _text(value)
            if normalized:
                result[field] = normalized
    # Embeddings are optional and are preserved only when they are finite numbers.
    embedding = source.get("embedding")
    if isinstance(embedding, Iterable) and not isinstance(embedding, (str, bytes, bytearray, Mapping)):
        values = list(embedding)
        if values and all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in values):
            result["embedding"] = [float(value) for value in values]
    return result


def _values_match(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and not isinstance(actual, bool):
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            return math.isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(actual, list):
        expected_values = normalize_list(expected)
        return bool(expected_values) and any(str(item) in expected_values for item in actual)
    if isinstance(expected, (list, tuple, set)):
        return str(actual or "") in {str(item) for item in expected}
    return str(actual or "").strip().lower() == str(expected or "").strip().lower()


def filter_metadata(metadata: Mapping[str, Any], filters: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    if not filters:
        return True, []
    unknown = sorted(set(filters) - set(STRUCTURED_MEMORY_FIELDS))
    if unknown:
        raise ValueError("Unknown structured memory filters: " + ", ".join(unknown))
    matched: list[str] = []
    for field, expected in filters.items():
        if _values_match(metadata.get(field), expected):
            matched.append(field)
        else:
            return False, matched
    return True, matched


def _tokens(value: Any) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(str(value or "")) if token}


def lexical_score(query: str, *, title: str, excerpt: str, body: str, tags: Any = None) -> tuple[float, list[str]]:
    query_text = _text(query).lower()
    if not query_text:
        return 0.0, []
    query_tokens = _tokens(query_text)
    title_tokens = _tokens(title)
    tag_tokens = _tokens(tags)
    body_tokens = _tokens(f"{excerpt} {body}")
    score = 0.0
    reasons: list[str] = []
    if query_text in _text(title).lower():
        score += 4.0
        reasons.append("title_substring")
    if query_text in f"{_text(excerpt)} {_text(body)}".lower():
        score += 2.0
        reasons.append("body_substring")
    if query_tokens:
        title_hits = len(query_tokens & title_tokens)
        tag_hits = len(query_tokens & tag_tokens)
        body_hits = len(query_tokens & body_tokens)
        score += 3.0 * title_hits / len(query_tokens)
        score += 1.5 * tag_hits / len(query_tokens)
        score += 1.0 * body_hits / len(query_tokens)
        if title_hits:
            reasons.append("title_terms")
        if tag_hits:
            reasons.append("tag_terms")
        if body_hits:
            reasons.append("body_terms")
    return score, reasons


def _optional_cosine_similarity(left: Any, right: Any) -> float | None:
    if not isinstance(left, Iterable) or isinstance(left, (str, bytes, bytearray, Mapping)):
        return None
    if not isinstance(right, Iterable) or isinstance(right, (str, bytes, bytearray, Mapping)):
        return None
    left_values = list(left)
    right_values = list(right)
    if not left_values or len(left_values) != len(right_values):
        return None
    try:
        left_numbers = [float(value) for value in left_values]
        right_numbers = [float(value) for value in right_values]
    except (TypeError, ValueError):
        return None
    left_norm = math.sqrt(sum(value * value for value in left_numbers))
    right_norm = math.sqrt(sum(value * value for value in right_numbers))
    if not left_norm or not right_norm:
        return None
    return sum(left * right for left, right in zip(left_numbers, right_numbers)) / (left_norm * right_norm)


def rank_cards(
    cards: list[dict[str, Any]],
    *,
    query: str,
    filters: Mapping[str, Any] | None = None,
    limit: int = 20,
    query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for card in cards:
        metadata = normalize_structured_metadata(card.get("metadata") or card.get("structured_metadata"))
        matches, matched_filters = filter_metadata(metadata, filters)
        if not matches:
            continue
        lexical, reasons = lexical_score(
            query,
            title=card.get("title"),
            excerpt=card.get("excerpt"),
            body=card.get("body"),
            tags=(card.get("tags") or (card.get("metadata") or {}).get("tags")),
        )
        similarity = _optional_cosine_similarity(query_embedding, metadata.get("embedding"))
        if _text(query) and query_embedding is None:
            query_tokens = _tokens(query)
            searchable_text = " ".join(
                [
                    _text(card.get("title")),
                    _text(card.get("excerpt")),
                    _text(card.get("body")),
                    _text(card.get("tags") or (card.get("metadata") or {}).get("tags")),
                ]
            ).lower()
            if _text(query).lower() not in searchable_text and not query_tokens.issubset(_tokens(searchable_text)):
                continue
        mode = "hybrid" if query_embedding is not None and similarity is not None else "lexical"
        score = lexical + (2.0 * similarity if similarity is not None else 0.0)
        # Empty lexical queries are valid for structured browsing; otherwise keep
        # legacy search semantics by excluding cards with no lexical or vector hit.
        if _text(query) and lexical <= 0.0 and similarity is None:
            continue
        result = dict(card)
        result["structured_metadata"] = metadata
        result["retrieval"] = {
            "mode": mode,
            "score": round(score, 8),
            "lexical_score": round(lexical, 8),
            "embedding_similarity": round(similarity, 8) if similarity is not None else None,
            "matched_filters": matched_filters,
            "match_reasons": reasons,
        }
        ranked.append(result)
    ranked.sort(
        key=lambda item: (
            float((item.get("retrieval") or {}).get("score") or 0.0),
            str(item.get("updated_at") or ""),
            str(item.get("path") or ""),
        ),
        reverse=True,
    )
    return ranked[: max(0, int(limit))]
def tokenize(text: str) -> list[str]:
    return str(text or "").lower().split()


def cosine_similarity(left: Any, right: Any) -> float:
    """Return cosine similarity, using zero for missing or invalid vectors."""

    return _optional_cosine_similarity(left, right) or 0.0


def reciprocal_rank_fusion(
    rankings: Iterable[list[str]],
    *,
    k: int = 60,
) -> list[str]:
    """Fuse multiple ranked id lists with Reciprocal Rank Fusion."""
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, node_id in enumerate(ranking):
            scores[node_id] += 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda node_id: scores[node_id], reverse=True)


def expand_subgraph(
    graph: Any,
    anchor_ids: Iterable[str],
    *,
    max_hops: int = 2,
) -> list[str]:
    """Collect anchor nodes plus their undirected BFS neighborhood."""
    collected = set(str(anchor) for anchor in anchor_ids)
    frontier = set(collected)
    for _ in range(max(0, int(max_hops or 0))):
        next_frontier: set[str] = set()
        for node in frontier:
            for _, neighbor, _data in graph.out_edges(node, data=True):
                if neighbor not in collected:
                    next_frontier.add(neighbor)
            for predecessor, _, _data in graph.in_edges(node, data=True):
                if predecessor not in collected:
                    next_frontier.add(predecessor)
        collected.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return sorted(collected)


def time_decay_factor(
    updated_at: str | None,
    *,
    now: datetime | None = None,
    half_life_days: float = 60.0,
) -> float:
    """Halve the relevance weight every ``half_life_days`` since the timestamp."""
    if not updated_at:
        return 1.0
    try:
        parsed = datetime.fromisoformat(str(updated_at))
    except ValueError:
        return 1.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    resolved_now = now or datetime.now(timezone.utc)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=timezone.utc)
    age_days = max((resolved_now - parsed).total_seconds(), 0.0) / 86400.0
    half_life = float(half_life_days or 1.0)
    return 0.5 ** (age_days / half_life)


def bm25_scores(summaries: list[str], query: str) -> list[float]:
    """BM25 relevance scores for summaries against one query."""
    corpus = [tokenize(summary) for summary in summaries]
    query_tokens = tokenize(query)
    if not corpus or not query_tokens:
        return [0.0] * len(summaries)
    return list(BM25Okapi(corpus).get_scores(query_tokens))
