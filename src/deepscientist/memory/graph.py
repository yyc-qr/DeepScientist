from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from ..shared import ensure_dir, generate_id, read_json, utc_now, write_json
from .service import MemoryService

NODE_TYPES = ("idea", "experiment", "method", "failure")
EDGE_TYPES = ("implements", "validates", "evolves_into", "contradicts", "fails_with")

GRAPH_FILENAME = "knowledge_graph.gml"
EMBEDDINGS_FILENAME = "embeddings.json"

_CARD_KIND_TO_NODE_TYPE = {
    "idea": "idea",
    "ideas": "idea",
    "episode": "failure",
    "episodes": "failure",
    "knowledge": "method",
}

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

    def clear(self) -> None:
        """Drop all nodes, edges, and cached embeddings."""
        self.graph.clear()
        self._embeddings.clear()

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

    def sync_from_cards(
        self,
        cards: Iterable[dict[str, Any]],
        *,
        rebuild: bool = False,
    ) -> dict[str, Any]:
        """Build the graph from memory cards, using card ids as node ids.

        Card kinds map to node types as: ideas -> idea, episodes -> failure,
        knowledge -> method. Papers, decisions, and templates are skipped for
        now. Edges are derived from card frontmatter fields ``evolved_from``,
        ``contradicted_by``, and ``fails_with``; references that point to
        missing nodes are reported instead of failing. Re-running with the same
        cards is idempotent; ``rebuild=True`` clears the graph first.
        """
        if rebuild:
            self.clear()

        card_list = list(cards)
        seen = 0
        created = 0
        updated = 0
        skipped_cards: list[dict[str, str]] = []
        mapped: list[dict[str, Any]] = []

        for card in card_list:
            seen += 1
            kind = self._card_kind(card)
            node_type = _CARD_KIND_TO_NODE_TYPE.get(kind)
            node_id = str(card.get("id") or "").strip()
            if node_type is None or not node_id:
                skipped_cards.append({"id": node_id, "kind": kind or "unknown"})
                continue
            mapped.append(card)

            existed = node_id in self.graph
            metadata = card.get("metadata") or {}
            summary = (
                str(card.get("title") or metadata.get("title") or "").strip()
                or "Untitled"
            )
            attrs: dict[str, Any] = {}
            if card.get("path"):
                attrs["card_path"] = str(card["path"])
            if card.get("scope"):
                attrs["scope"] = str(card["scope"])
            if metadata.get("tags"):
                attrs["tags"] = metadata["tags"]
            for key in ("created_at", "updated_at"):
                if metadata.get(key):
                    attrs[key] = metadata[key]
            if metadata.get("status"):
                attrs["status"] = str(metadata["status"])
            self.add_node(
                node_id=node_id,
                node_type=node_type,
                summary=summary,
                **attrs,
            )
            if existed:
                updated += 1
            else:
                created += 1

        edges_created = 0
        skipped_refs: list[str] = []
        for card in mapped:
            node_id = str(card.get("id") or "").strip()
            metadata = card.get("metadata") or {}
            for ref in self._as_id_list(metadata.get("evolved_from")):
                if self._try_add_edge(ref, node_id, "evolves_into"):
                    edges_created += 1
                elif ref != node_id:
                    skipped_refs.append(ref)
            for ref in self._as_id_list(metadata.get("contradicted_by")):
                if self._try_add_edge(ref, node_id, "contradicts"):
                    edges_created += 1
                elif ref != node_id:
                    skipped_refs.append(ref)
            for ref in self._as_id_list(metadata.get("fails_with")):
                if self._try_add_edge(node_id, ref, "fails_with"):
                    edges_created += 1
                elif ref != node_id:
                    skipped_refs.append(ref)

        return {
            "cards_seen": seen,
            "nodes_created": created,
            "nodes_updated": updated,
            "edges_created": edges_created,
            "skipped_cards": skipped_cards,
            "skipped_refs": sorted(set(skipped_refs)),
        }

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

    def _try_add_edge(self, source: str, target: str, edge_type: str) -> bool:
        if source == target:
            return False
        if source not in self.graph or target not in self.graph:
            return False
        if self.graph.has_edge(source, target):
            return False
        self.add_edge(source=source, target=target, edge_type=edge_type)
        return True

    @staticmethod
    def _card_kind(card: dict[str, Any]) -> str:
        metadata = card.get("metadata") or {}
        raw = card.get("type") or metadata.get("kind") or metadata.get("type") or ""
        return str(raw).strip().lower()

    @staticmethod
    def _as_id_list(value: Any) -> list[str]:
        if value is None:
            return []
        raw_values = value if isinstance(value, (list, tuple)) else [value]
        return [str(item).strip() for item in raw_values if str(item).strip()]


class MemoryGraphService:
    """Scope-aware access to per-quest and global knowledge graphs."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.memory = MemoryService(home)

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

    def sync_scope(
        self,
        *,
        scope: str = "quest",
        quest_root: Path | None = None,
        rebuild: bool = False,
    ) -> dict[str, Any]:
        """Reconcile the graph for a scope with the cards under that scope."""
        root = self._root_for(scope, quest_root)
        store = GraphStore(root).load()
        cards = self.memory.list_cards(
            scope=scope,
            quest_root=quest_root,
            limit=100000,
            kind=None,
        )
        full_cards = [
            self.memory.read_card(
                card_id=card.get("id"),
                path=card.get("path"),
                scope=scope,
                quest_root=quest_root,
            )
            for card in cards
        ]
        result = store.sync_from_cards(full_cards, rebuild=rebuild)
        store.save()
        return result
