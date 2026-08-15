from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from ..shared import ensure_dir, generate_id, read_json, utc_now, write_json

NODE_TYPES = ("idea", "experiment", "method", "failure")
EDGE_TYPES = ("implements", "validates", "evolves_into", "contradicts", "fails_with")

GRAPH_FILENAME = "knowledge_graph.gml"
EMBEDDINGS_FILENAME = "embeddings.json"

_GML_SCALAR_TYPES = (str, int, float, bool)


class GraphStore:
    """NetworkX-based directed knowledge graph persisted as a single GML file.

    Node embeddings live in a separate JSON cache because the GML format does
    not support list values. The graph is quest-scoped or global depending on
    the root directory it is opened with.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.graph_path = self.root / GRAPH_FILENAME
        self.embeddings_path = self.root / EMBEDDINGS_FILENAME
        self.graph = nx.DiGraph()
        self._embeddings: dict[str, list[float]] = {}

    def load(self) -> "GraphStore":
        if self.graph_path.exists():
            self.graph = nx.read_gml(str(self.graph_path))
        embeddings = read_json(self.embeddings_path, {}) or {}
        self._embeddings = {
            str(node_id): [float(value) for value in vector]
            for node_id, vector in embeddings.items()
        }
        return self

    def save(self) -> "GraphStore":
        ensure_dir(self.root)
        nx.write_gml(self.graph, str(self.graph_path))
        write_json(self.embeddings_path, self._embeddings)
        return self

    def add_node(
        self,
        *,
        node_type: str,
        summary: str,
        node_id: str | None = None,
        **attrs: Any,
    ) -> str:
        """Add a typed node or upsert an existing one by id.

        Existing nodes keep their ``created_at`` and only ``updated_at`` and the
        supplied attributes are refreshed. Returns the resolved node id.
        """
        normalized_type = self._normalize_node_type(node_type)
        resolved_id = str(node_id or generate_id(normalized_type))
        now = utc_now()
        base = dict(self.graph.nodes.get(resolved_id) or {})
        base["type"] = normalized_type
        base["summary"] = summary
        base.setdefault("status", "active")
        base.setdefault("created_at", now)
        base["updated_at"] = now
        for key, value in attrs.items():
            base[key] = value
        self.graph.add_node(resolved_id, **self._sanitize_attrs(base))
        return resolved_id

    def add_edge(
        self,
        *,
        source: str,
        target: str,
        edge_type: str,
        **attrs: Any,
    ) -> None:
        """Add or update a typed edge between two existing nodes."""
        normalized_type = self._normalize_edge_type(edge_type)
        if source not in self.graph or target not in self.graph:
            raise ValueError(
                f"Cannot add `{normalized_type}` edge: source or target node does not exist in the graph."
            )
        payload = {"type": normalized_type, **attrs}
        if self.graph.has_edge(source, target):
            self.graph[source][target].update(self._sanitize_attrs(payload))
        else:
            self.graph.add_edge(source, target, **self._sanitize_attrs(payload))

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        data = self.graph.nodes.get(str(node_id))
        if data is None:
            return None
        return {"id": str(node_id), **dict(data)}

    def nodes(self) -> list[dict[str, Any]]:
        return [self.get_node(node_id) for node_id in sorted(self.graph.nodes)]

    def edges(self) -> list[dict[str, Any]]:
        return [
            {"source": source, "target": target, **dict(self.graph[source][target])}
            for source, target in sorted(self.graph.edges)
        ]

    def neighbors(
        self,
        node_id: str,
        *,
        edge_types: Iterable[str] | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Return typed neighbors of a node, optionally filtered by edge type."""
        if node_id not in self.graph:
            return []
        allowed = set(edge_types) if edge_types is not None else None
        normalized_direction = str(direction or "both").strip().lower()
        if normalized_direction not in {"out", "in", "both"}:
            raise ValueError("direction must be `out`, `in`, or `both`.")

        results: list[dict[str, Any]] = []
        if normalized_direction in {"out", "both"}:
            for _, neighbor, data in self.graph.out_edges(node_id, data=True):
                edge_type = data.get("type")
                if allowed is None or edge_type in allowed:
                    results.append(
                        {"node_id": neighbor, "edge_type": edge_type, "direction": "out"}
                    )
        if normalized_direction in {"in", "both"}:
            for neighbor, _, data in self.graph.in_edges(node_id, data=True):
                edge_type = data.get("type")
                if allowed is None or edge_type in allowed:
                    results.append(
                        {"node_id": neighbor, "edge_type": edge_type, "direction": "in"}
                    )
        return results

    def set_status(self, node_id: str, status: str) -> None:
        if node_id not in self.graph:
            raise ValueError(f"Node `{node_id}` does not exist in the graph.")
        self.graph.nodes[node_id]["status"] = status
        self.graph.nodes[node_id]["updated_at"] = utc_now()

    def get_embedding(self, node_id: str) -> list[float] | None:
        vector = self._embeddings.get(str(node_id))
        return list(vector) if vector is not None else None

    def set_embedding(self, node_id: str, vector: Iterable[float]) -> None:
        if node_id not in self.graph:
            raise ValueError(f"Node `{node_id}` does not exist in the graph.")
        self._embeddings[str(node_id)] = [float(value) for value in vector]

    @staticmethod
    def _sanitize_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
        """Normalize attribute values to GML-writable primitives."""
        cleaned: dict[str, Any] = {}
        for key, value in attrs.items():
            normalized_key = str(key)
            if value is None:
                cleaned[normalized_key] = ""
            elif isinstance(value, _GML_SCALAR_TYPES):
                cleaned[normalized_key] = value
            else:
                cleaned[normalized_key] = json.dumps(
                    value, ensure_ascii=False, sort_keys=True
                )
        return cleaned

    @staticmethod
    def _normalize_node_type(node_type: str) -> str:
        normalized = str(node_type or "").strip().lower()
        if normalized not in NODE_TYPES:
            raise ValueError(f"Unknown node type `{node_type}`. Available: {', '.join(NODE_TYPES)}.")
        return normalized

    @staticmethod
    def _normalize_edge_type(edge_type: str) -> str:
        normalized = str(edge_type or "").strip().lower()
        if normalized not in EDGE_TYPES:
            raise ValueError(f"Unknown edge type `{edge_type}`. Available: {', '.join(EDGE_TYPES)}.")
        return normalized


class MemoryGraphService:
    """Scope-aware access to per-quest and global knowledge graphs."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def _root_for(self, scope: str, quest_root: Path | None = None) -> Path:
        if scope == "global":
            return self.home / "memory"
        if scope == "quest":
            if quest_root is None:
                raise ValueError("quest_root is required for quest-scoped memory graph")
            return quest_root / "memory"
        raise ValueError(f"Unknown memory scope: {scope}")

    def open_graph(self, *, scope: str = "quest", quest_root: Path | None = None) -> GraphStore:
        return GraphStore(self._root_for(scope, quest_root)).load()
