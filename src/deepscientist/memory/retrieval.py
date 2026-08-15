from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from rank_bm25 import BM25Okapi


def tokenize(text: str) -> list[str]:
    return str(text or "").lower().split()


def cosine_similarity(a: Iterable[float] | None, b: Iterable[float] | None) -> float:
    vector_a = list(a or [])
    vector_b = list(b or [])
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return 0.0
    dot = sum(x * y for x, y in zip(vector_a, vector_b))
    norm_a = math.sqrt(sum(x * x for x in vector_a))
    norm_b = math.sqrt(sum(y * y for y in vector_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


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
