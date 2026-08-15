from __future__ import annotations

from pathlib import Path

import pytest

from deepscientist.memory.graph import (
    EDGE_TYPES,
    EMBEDDINGS_FILENAME,
    GRAPH_FILENAME,
    NODE_TYPES,
    GraphStore,
    MemoryGraphService,
)


def test_node_and_edge_type_constants() -> None:
    assert NODE_TYPES == ("idea", "experiment", "method", "failure")
    assert EDGE_TYPES == (
        "implements",
        "validates",
        "evolves_into",
        "contradicts",
        "fails_with",
    )


def test_add_node_upserts_and_sets_default_fields(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    node_id = store.add_node(
        node_type="idea",
        summary="Use t-distribution instead of Gaussian normalization",
        provenance="artifacts/idea/selected_idea.md",
    )

    node = store.get_node(node_id)
    assert node is not None
    assert node["id"] == node_id
    assert node["type"] == "idea"
    assert node["status"] == "active"
    assert node["created_at"] == node["updated_at"]
    assert node["provenance"] == "artifacts/idea/selected_idea.md"

    store.add_node(
        node_id=node_id,
        node_type="idea",
        summary="Refined idea",
        status="dead_end",
    )
    refreshed = store.get_node(node_id)
    assert refreshed["summary"] == "Refined idea"
    assert refreshed["status"] == "dead_end"
    assert refreshed["created_at"] == node["created_at"]
    assert refreshed["updated_at"] >= node["updated_at"]
    assert list(store.graph.nodes) == [node_id]


def test_add_node_rejects_unknown_type(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    with pytest.raises(ValueError, match="Unknown node type"):
        store.add_node(node_type="paper", summary="x")


def test_add_edge_requires_existing_nodes_and_valid_type(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    idea = store.add_node(node_type="idea", summary="Hypothesis")
    experiment = store.add_node(node_type="experiment", summary="Run 001")

    with pytest.raises(ValueError, match="Unknown edge type"):
        store.add_edge(source=idea, target=experiment, edge_type="links")
    with pytest.raises(ValueError, match="does not exist"):
        store.add_edge(source=idea, target="missing", edge_type="implements")

    store.add_edge(source=idea, target=experiment, edge_type="implements")
    assert store.graph.has_edge(idea, experiment)
    assert store.graph[idea][experiment]["type"] == "implements"


def test_save_and_reload_roundtrip(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    idea = store.add_node(
        node_type="idea",
        summary="Idea A",
        provenance="artifacts/idea/selected_idea.md",
    )
    experiment = store.add_node(
        node_type="experiment",
        summary="Experiment A",
        metric="acc",
        value=0.87,
    )
    store.add_edge(source=idea, target=experiment, edge_type="implements")
    store.set_embedding(idea, [0.1, 0.2, 0.3])
    store.save()

    assert (tmp_path / GRAPH_FILENAME).exists()
    assert (tmp_path / EMBEDDINGS_FILENAME).exists()

    reloaded = GraphStore(tmp_path).load()
    assert set(reloaded.graph.nodes) == {idea, experiment}
    assert reloaded.graph[idea][experiment]["type"] == "implements"
    assert reloaded.get_node(experiment)["metric"] == "acc"
    assert reloaded.get_node(experiment)["value"] == 0.87
    assert reloaded.get_embedding(idea) == [0.1, 0.2, 0.3]

    reloaded.save()
    again = GraphStore(tmp_path).load()
    assert set(again.graph.nodes) == {idea, experiment}
    assert again.get_embedding(idea) == [0.1, 0.2, 0.3]


def test_embedding_cache_requires_existing_node(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        store.set_embedding("missing", [1.0])
    assert store.get_embedding("missing") is None

    node_id = store.add_node(node_type="method", summary="Validated method")
    store.set_embedding(node_id, [1.0, 2.0])
    assert store.get_embedding(node_id) == [1.0, 2.0]


def test_neighbors_filters_by_edge_type_and_direction(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    idea = store.add_node(node_type="idea", summary="Hypothesis")
    experiment = store.add_node(node_type="experiment", summary="Run")
    method = store.add_node(node_type="method", summary="Method")
    store.add_edge(source=idea, target=experiment, edge_type="implements")
    store.add_edge(source=experiment, target=method, edge_type="validates")

    outgoing = store.neighbors(experiment, direction="out")
    assert [(item["node_id"], item["edge_type"]) for item in outgoing] == [
        (method, "validates")
    ]
    incoming = store.neighbors(experiment, direction="in")
    assert [(item["node_id"], item["edge_type"]) for item in incoming] == [
        (idea, "implements")
    ]
    both = store.neighbors(experiment)
    assert len(both) == 2

    validates_only = store.neighbors(experiment, edge_types=["validates"])
    assert len(validates_only) == 1
    assert validates_only[0]["node_id"] == method


def test_set_status_bumps_updated_at(tmp_path: Path) -> None:
    store = GraphStore(tmp_path)
    node_id = store.add_node(node_type="idea", summary="Draft")
    before = store.get_node(node_id)["updated_at"]
    store.set_status(node_id, "dead_end")
    refreshed = store.get_node(node_id)
    assert refreshed["status"] == "dead_end"
    assert refreshed["updated_at"] >= before


def test_memory_graph_service_resolves_scope_roots(tmp_path: Path) -> None:
    service = MemoryGraphService(tmp_path)
    with pytest.raises(ValueError, match="Unknown memory scope"):
        service.open_graph(scope="other")
    with pytest.raises(ValueError, match="quest_root is required"):
        service.open_graph(scope="quest")

    quest_root = tmp_path / "quests" / "q1"
    quest_store = service.open_graph(scope="quest", quest_root=quest_root)
    assert quest_store.root == quest_root / "memory"

    global_store = service.open_graph(scope="global")
    assert global_store.root == tmp_path / "memory"
