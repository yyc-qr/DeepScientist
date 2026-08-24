from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import networkx as nx
import pytest

from deepscientist.memory.graph import GraphStore, MemoryGraphService
from deepscientist.memory.retrieval import (
    bm25_scores,
    cosine_similarity,
    expand_subgraph,
    reciprocal_rank_fusion,
    time_decay_factor,
    tokenize,
)


class FakeQwenClient:
    def __init__(
        self,
        chat_response: str,
        *,
        embeddings: dict[str, list[float]] | None = None,
    ) -> None:
        self.chat_response = chat_response
        self.embeddings = embeddings or {}
        self.chat_calls: list[dict] = []
        self.embed_calls: list[list[str]] = []

    def chat(self, system: str, user: str, *, json_mode: bool = True) -> str:
        self.chat_calls.append({"system": system, "user": user, "json_mode": json_mode})
        return self.chat_response

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [self.embeddings.get(text, [0.0, 0.0, 0.0]) for text in texts]


def _retrieval_graph(quest_root: Path) -> GraphStore:
    store = GraphStore(quest_root / "memory")
    store.add_node(node_id="idea-a", node_type="idea", summary="T-Detect detector")
    store.add_node(node_id="idea-b", node_type="idea", summary="TDT evolution")
    store.add_node(node_id="method-x", node_type="method", summary="PA-TDT method")
    store.add_node(node_id="failure-1", node_type="failure", summary="OOM pattern")
    store.add_edge(source="method-x", target="idea-a", edge_type="contradicts")
    store.set_embedding("idea-a", [1.0, 0.0, 0.0])
    store.set_embedding("idea-b", [0.0, 1.0, 0.0])
    store.set_embedding("method-x", [0.0, 0.0, 1.0])
    store.set_embedding("failure-1", [0.0, 0.0, 0.1])
    store.save()
    return store


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [2.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity(None, [1.0]) == 0.0


def test_reciprocal_rank_fusion_orders_by_combined_rank() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c"}


def test_expand_subgraph_bfs() -> None:
    graph = nx.DiGraph()
    graph.add_edge("a", "b")
    graph.add_edge("b", "c")
    graph.add_edge("a", "d")
    assert expand_subgraph(graph, ["a"], max_hops=0) == ["a"]
    assert expand_subgraph(graph, ["a"], max_hops=1) == ["a", "b", "d"]
    assert expand_subgraph(graph, ["a"], max_hops=2) == ["a", "b", "c", "d"]


def test_time_decay_factor() -> None:
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    assert time_decay_factor("2026-08-15T00:00:00+00:00", now=now) == pytest.approx(1.0)
    old = time_decay_factor(
        (now - timedelta(days=60)).isoformat(),
        now=now,
    )
    assert old == pytest.approx(0.5)
    assert time_decay_factor("not-a-date", now=now) == 1.0
    assert time_decay_factor(None, now=now) == 1.0


def test_bm25_scores_rank_token_overlap() -> None:
    scores = bm25_scores(["T-Detect detector", "TDT evolution", "OOM pattern"], "OOM")
    assert scores[2] > scores[0]
    assert scores[2] > scores[1]
    assert tokenize("Hello WORLD") == ["hello", "world"]


def test_hybrid_search_applies_rerank_and_contradicts_penalty(tmp_path: Path) -> None:
    quest_root = tmp_path / "quests" / "q1"
    _retrieval_graph(quest_root)
    fake = FakeQwenClient(
        json.dumps({"ids": ["idea-b", "idea-a", "method-x", "failure-1"]}),
        embeddings={"T-Detect detector evolution": [0.8, 0.6, 0.2]},
    )
    service = MemoryGraphService(tmp_path)

    result = service.hybrid_search(
        "T-Detect detector evolution",
        scope="quest",
        quest_root=quest_root,
        k=3,
        llm=fake,
    )

    assert result["count"] == 3
    assert [item["id"] for item in result["items"]] == [
        "idea-b",
        "method-x",
        "failure-1",
    ]
    assert result["items"][0]["score"] == pytest.approx(1.0)
    assert result["anchors"]
    assert result["subgraph_size"] >= 4
    assert fake.embed_calls[0] == ["T-Detect detector evolution"]
    assert len(fake.embed_calls) == 1


def test_hybrid_search_lazily_embeds_missing_nodes(tmp_path: Path) -> None:
    quest_root = tmp_path / "quests" / "q1"
    store = GraphStore(quest_root / "memory")
    store.add_node(node_id="idea-a", node_type="idea", summary="T-Detect detector")
    store.add_node(node_id="idea-b", node_type="idea", summary="TDT evolution")
    store.save()
    fake = FakeQwenClient(
        json.dumps({"ids": ["idea-a", "idea-b"]}),
        embeddings={
            "T-Detect detector": [1.0, 0.0, 0.0],
            "TDT evolution": [0.0, 1.0, 0.0],
            "detector evolution query": [0.7, 0.5, 0.0],
        },
    )
    service = MemoryGraphService(tmp_path)

    result = service.hybrid_search(
        "detector evolution query",
        scope="quest",
        quest_root=quest_root,
        k=2,
        llm=fake,
    )

    assert result["count"] == 2
    reloaded = GraphStore(quest_root / "memory").load()
    assert reloaded.get_embedding("idea-a") == [1.0, 0.0, 0.0]
    assert reloaded.get_embedding("idea-b") == [0.0, 1.0, 0.0]
    assert fake.embed_calls[0] == ["T-Detect detector", "TDT evolution"]


def test_hybrid_search_empty_graph_returns_empty(tmp_path: Path) -> None:
    quest_root = tmp_path / "quests" / "q1"
    service = MemoryGraphService(tmp_path)
    result = service.hybrid_search("anything", scope="quest", quest_root=quest_root)
    assert result["count"] == 0
    assert result["items"] == []


def test_hybrid_search_bm25_surfaces_term_match(tmp_path: Path) -> None:
    quest_root = tmp_path / "quests" / "q1"
    _retrieval_graph(quest_root)
    fake = FakeQwenClient(json.dumps({"ids": ["failure-1"]}))
    service = MemoryGraphService(tmp_path)

    result = service.hybrid_search(
        "OOM",
        scope="quest",
        quest_root=quest_root,
        k=1,
        llm=fake,
    )

    assert "failure-1" in result["anchors"]
    assert result["items"][0]["id"] == "failure-1"
