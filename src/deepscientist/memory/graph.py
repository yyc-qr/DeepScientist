from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from ..shared import ensure_dir, generate_id, read_json, utc_now, write_json
from .qwen import QwenClient, parse_json_object
from .retrieval import (
    bm25_scores,
    cosine_similarity,
    expand_subgraph,
    reciprocal_rank_fusion,
    time_decay_factor,
)
from .service import MemoryService

NODE_TYPES = ("idea", "experiment", "method", "failure")
EDGE_TYPES = ("implements", "validates", "evolves_into", "contradicts", "fails_with")
FAILURE_CATEGORIES = (
    "implementation_bug",
    "timeout",
    "hypothesis_invalid",
    "marginal",
    "unexpected",
)
LINK_DISCOVERY_EDGE_TYPES = (
    "evolves_into",
    "contradicts",
    "validates",
    "fails_with",
)

GRAPH_FILENAME = "knowledge_graph.gml"
EMBEDDINGS_FILENAME = "embeddings.json"

CLASSIFY_FAILURE_SYSTEM_PROMPT = (
    "You classify failed research experiments for an AI Scientist memory system. "
    "Reply with a JSON object only: {\"category\": \"...\", \"reason\": \"...\"}.\n"
    "Categories:\n"
    "- implementation_bug: code or environment error; fix and retry\n"
    "- timeout: run timeout or out-of-memory; retry with smaller settings\n"
    "- hypothesis_invalid: the hypothesis itself does not hold; record permanently\n"
    "- marginal: positive signal but not enough to beat the baseline\n"
    "- unexpected: main task failed but an unexpected positive signal appeared\n"
)

LINK_DISCOVERY_SYSTEM_PROMPT = (
    "You discover typed relations between a new scientific finding and existing "
    "knowledge graph nodes. Reply with a JSON object only: "
    "{\"edges\": [{\"from\": \"existing node id\", \"edge\": \"...\", \"to\": \"new node id\"}]}.\n"
    "Edge types:\n"
    "- evolves_into: the new finding is a gradual evolution of an existing idea or method\n"
    "- contradicts: the new finding contradicts an existing conclusion\n"
    "- validates: an experiment validates a method\n"
    "- fails_with: an idea failed because of a known failure pattern\n"
    "Only reference node ids that appear in the provided node list."
)

RERANK_SYSTEM_PROMPT = (
    "You rank knowledge graph nodes by relevance to a research query. "
    "Reply with a JSON object only: {\"ids\": [\"node id\", ...]} ordered from "
    "most to least relevant. Only reference node ids from the candidate list."
)

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

    def __init__(self, home: Path, *, llm: Any | None = None) -> None:
        self.home = home
        self.llm = llm
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

    def classify_failure(
        self,
        *,
        idea_summary: str,
        experiment_id: str,
        error: str = "",
        log_tail: str = "",
        llm: Any | None = None,
    ) -> dict[str, Any]:
        """Ask QWEN to classify an experiment failure into one of five categories."""
        client = llm or self._default_llm()
        user = (
            "Experiment target (idea): " + (idea_summary or "").strip() + "\n"
            "Experiment id: " + (experiment_id or "").strip() + "\n"
            "Error message: " + (error or "").strip() + "\n"
            "Log tail: " + (log_tail or "").strip() + "\n\n"
            "Classify the failure category and give a one-sentence reason."
        )
        raw = client.chat(
            system=CLASSIFY_FAILURE_SYSTEM_PROMPT,
            user=user,
            json_mode=True,
        )
        payload = parse_json_object(raw)
        category = str(payload.get("category") or "").strip().lower()
        if category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"Unknown failure category `{category}`. "
                f"Available: {', '.join(FAILURE_CATEGORIES)}."
            )
        return {
            "category": category,
            "reason": str(payload.get("reason") or "").strip(),
        }

    def link_discovery(
        self,
        *,
        scope: str = "quest",
        quest_root: Path | None = None,
        node_id: str,
        context_nodes: list[str] | None = None,
        limit: int = 20,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        """Ask QWEN to connect a new node to existing nodes with typed edges.

        Directions are normalized to graph conventions: ``evolves_into`` points
        from the earlier node to the new one, ``contradicts`` points from the
        new finding to the old conclusion, ``validates`` points from experiment
        to method, and ``fails_with`` points from idea to failure. Proposals
        that miss endpoints or violate those type conventions are skipped.
        """
        root = self._root_for(scope, quest_root)
        store = GraphStore(root).load()
        if node_id not in store.graph:
            raise ValueError(f"Node `{node_id}` does not exist in the graph.")

        node = store.get_node(node_id)
        candidate_ids = [candidate for candidate in context_nodes or [] if candidate != node_id]
        if not candidate_ids:
            candidate_ids = [candidate for candidate in sorted(store.graph.nodes) if candidate != node_id]
        candidate_ids = candidate_ids[: max(1, int(limit or 20))]

        node_lines = "\n".join(
            f"- {candidate} [{store.get_node(candidate)['type']}] "
            f"{store.get_node(candidate)['summary']}"
            for candidate in candidate_ids
        )
        user = (
            "New node: "
            f"{node_id} [{node['type']}] {node['summary']}\n"
            "Existing nodes:\n"
            f"{node_lines}\n\n"
            "Return the typed edges between the new node and the existing nodes."
        )
        client = llm or self._default_llm()
        raw = client.chat(
            system=LINK_DISCOVERY_SYSTEM_PROMPT,
            user=user,
            json_mode=True,
        )
        payload = parse_json_object(raw)
        proposals = payload.get("edges") or []

        edges: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for item in proposals:
            if not isinstance(item, dict):
                skipped.append({"reason": "non-object proposal", "item": str(item)[:200]})
                continue
            source = str(item.get("from") or "").strip()
            target = str(item.get("to") or "").strip()
            edge_type = str(item.get("edge") or "").strip().lower()
            normalized, reason = self._normalize_discovered_edge(
                store,
                node_id=node_id,
                source=source,
                target=target,
                edge_type=edge_type,
            )
            if normalized is None:
                skipped.append({"reason": reason, "edge": edge_type, "from": source, "to": target})
                continue
            resolved_source, resolved_target = normalized
            store.add_edge(source=resolved_source, target=resolved_target, edge_type=edge_type)
            edges.append(
                {
                    "source": resolved_source,
                    "target": resolved_target,
                    "edge_type": edge_type,
                }
            )

        store.save()
        return {
            "node_id": node_id,
            "edges_added": len(edges),
            "edges": edges,
            "skipped": skipped,
        }

    def hybrid_search(
        self,
        query: str,
        *,
        scope: str = "quest",
        quest_root: Path | None = None,
        k: int = 5,
        anchor_k: int = 10,
        max_hops: int = 2,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        """Hybrid graph retrieval: dense + BM25, RRF, BFS, LLM re-rank.

        Pipeline: Dense (QWEN embedding) + BM25 -> RRF fusion -> anchor nodes ->
        BFS subgraph expansion -> QWEN re-rank -> contradicts penalty and time
        decay -> top-k items. Nodes without cached embeddings are embedded on
        demand and persisted in the embedding cache.
        """
        root = self._root_for(scope, quest_root)
        store = GraphStore(root).load()
        normalized_query = str(query or "").strip()
        if not store.graph or not normalized_query:
            return {
                "query": normalized_query,
                "count": 0,
                "items": [],
                "anchors": [],
                "subgraph_size": 0,
            }

        client = llm or self._default_llm()
        nodes = store.nodes()
        node_ids = [node["id"] for node in nodes]
        summaries = [node["summary"] for node in nodes]

        missing = [node for node in nodes if store.get_embedding(node["id"]) is None]
        if missing:
            vectors = client.embed([node["summary"] for node in missing])
            for node, vector in zip(missing, vectors):
                store.set_embedding(node["id"], vector)
            store.save()

        query_embedding = client.embed([normalized_query])[0]
        dense_ranked = sorted(
            node_ids,
            key=lambda node_id: cosine_similarity(query_embedding, store.get_embedding(node_id)),
            reverse=True,
        )
        bm25 = bm25_scores(summaries, normalized_query)
        bm25_ranked = [
            node_id
            for node_id, _score in sorted(
                zip(node_ids, bm25),
                key=lambda item: item[1],
                reverse=True,
            )
        ]

        anchors = reciprocal_rank_fusion([dense_ranked, bm25_ranked])[
            : max(1, int(anchor_k or 1))
        ]
        subgraph_ids = expand_subgraph(store.graph, anchors, max_hops=max_hops)
        candidates = list(dict.fromkeys([*anchors, *subgraph_ids]))

        candidate_lines = "\n".join(
            f"- {node_id} [{store.get_node(node_id)['type']}] "
            f"{store.get_node(node_id)['summary']}"
            for node_id in candidates
        )
        user = (
            f"Query: {normalized_query}\n"
            "Candidate nodes:\n"
            f"{candidate_lines}\n\n"
            "Return the node ids most relevant to the query, "
            "ordered from most to least relevant."
        )
        raw = client.chat(
            system=RERANK_SYSTEM_PROMPT,
            user=user,
            json_mode=True,
        )
        payload = parse_json_object(raw)
        reranked = [
            str(item).strip()
            for item in (payload.get("ids") or [])
            if str(item).strip()
        ]
        reranked = [node_id for node_id in reranked if node_id in store.graph]

        scored: list[tuple[str, float]] = []
        for rank, node_id in enumerate(reranked):
            score = 1.0 / (rank + 1)
            for _source, _target, edge_data in store.graph.in_edges(node_id, data=True):
                if edge_data.get("type") == "contradicts":
                    score *= 0.2
                    break
            node = store.get_node(node_id)
            updated_at = node.get("updated_at") or node.get("created_at")
            score *= time_decay_factor(updated_at)
            scored.append((node_id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        scored = scored[: max(1, int(k or 1))]

        items: list[dict[str, Any]] = []
        for node_id, score in scored:
            node = store.get_node(node_id)
            items.append(
                {
                    "id": node_id,
                    "type": node["type"],
                    "summary": node["summary"],
                    "score": round(score, 6),
                    "path": node.get("card_path"),
                    "status": node.get("status"),
                }
            )
        return {
            "query": normalized_query,
            "count": len(items),
            "items": items,
            "anchors": anchors,
            "subgraph_size": len(candidates),
        }

    def record_failure(
        self,
        *,
        scope: str = "quest",
        quest_root: Path | None = None,
        idea_id: str,
        experiment_id: str,
        summary: str,
        error: str = "",
        log_tail: str = "",
        log_path: str | None = None,
        category: str | None = None,
        reason: str = "",
        failure_id: str | None = None,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        """Record a failed experiment in the graph.

        The experiment node is the episode-level evidence record. Only a
        ``hypothesis_invalid`` failure creates a Failure node (knowledge
        layer), marks the idea ``dead_end``, and links it via ``fails_with``;
        other categories such as ``implementation_bug`` stay at the episode
        level and do not pollute the knowledge layer.
        """
        root = self._root_for(scope, quest_root)
        store = GraphStore(root).load()

        resolved_category = category
        resolved_reason = reason
        if resolved_category is None:
            classified = self.classify_failure(
                idea_summary=summary,
                experiment_id=experiment_id,
                error=error,
                log_tail=log_tail,
                llm=llm,
            )
            resolved_category = classified["category"]
            resolved_reason = classified["reason"]
        if resolved_category not in FAILURE_CATEGORIES:
            raise ValueError(
                f"Unknown failure category `{resolved_category}`. "
                f"Available: {', '.join(FAILURE_CATEGORIES)}."
            )

        experiment_attrs: dict[str, Any] = {
            "status": "failed",
            "failure_category": resolved_category,
            "reason": resolved_reason,
        }
        if error:
            experiment_attrs["error"] = error
        if log_path:
            experiment_attrs["log_path"] = log_path
        experiment_node_id = store.add_node(
            node_id=experiment_id,
            node_type="experiment",
            summary=summary,
            **experiment_attrs,
        )

        changes: dict[str, Any] = {
            "category": resolved_category,
            "reason": resolved_reason,
            "experiment_node_id": experiment_node_id,
            "idea_dead_end": False,
            "failure_node_id": None,
        }
        if idea_id in store.graph:
            store.add_edge(source=idea_id, target=experiment_node_id, edge_type="implements")
            changes["implements_linked"] = True
        else:
            changes["implements_linked"] = False
            changes["missing_idea"] = idea_id

        if resolved_category == "hypothesis_invalid":
            resolved_failure_id = str(failure_id or f"failure-{idea_id or experiment_id}")
            store.add_node(
                node_id=resolved_failure_id,
                node_type="failure",
                summary=f"Hypothesis invalid: {summary}",
                status="confirmed",
            )
            changes["failure_node_id"] = resolved_failure_id
            if idea_id in store.graph:
                store.set_status(idea_id, "dead_end")
                store.add_edge(source=idea_id, target=resolved_failure_id, edge_type="fails_with")
                changes["idea_dead_end"] = True

        store.save()
        return changes

    def _default_llm(self) -> Any:
        return self.llm or QwenClient(self.home)

    @staticmethod
    def _normalize_discovered_edge(
        store: GraphStore,
        *,
        node_id: str,
        source: str,
        target: str,
        edge_type: str,
    ) -> tuple[tuple[str, str], str] | tuple[None, str]:
        if edge_type not in LINK_DISCOVERY_EDGE_TYPES:
            return None, f"unsupported edge type `{edge_type}`"
        if source not in store.graph or target not in store.graph:
            return None, "missing endpoint"
        if node_id not in {source, target}:
            return None, "edge does not involve the new node"
        if edge_type == "evolves_into":
            source_type = store.get_node(source)["type"]
            target_type = store.get_node(target)["type"]
            if source_type != target_type or source_type not in {"idea", "method"}:
                return None, "evolves_into requires idea -> idea or method -> method"
            if target == node_id:
                return (source, target), ""
            return (target, node_id), ""
        if edge_type == "contradicts":
            if source == node_id:
                return (source, target), ""
            return (target, node_id), ""
        if edge_type == "validates":
            source_type = store.get_node(source)["type"]
            target_type = store.get_node(target)["type"]
            if source_type == "experiment" and target_type == "method":
                return (source, target), ""
            if source_type == "method" and target_type == "experiment":
                return (target, source), ""
            return None, "validates requires experiment -> method"
        if edge_type == "fails_with":
            source_type = store.get_node(source)["type"]
            target_type = store.get_node(target)["type"]
            if source_type == "idea" and target_type == "failure":
                return (source, target), ""
            if source_type == "failure" and target_type == "idea":
                return (target, source), ""
            return None, "fails_with requires idea -> failure"
        return (source, target), ""
