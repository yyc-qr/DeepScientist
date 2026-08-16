from __future__ import annotations

import re
from typing import Any


CANDIDATE_CODE_CHANGE_MODES = {"base", "stepwise", "diff"}
_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def normalize_id_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _relation_sources(node: dict[str, Any]) -> list[str]:
    return [
        str(node.get("parent_candidate_id") or "").strip(),
        *normalize_id_list(node.get("reference_candidate_ids")),
        *normalize_id_list(node.get("fused_from_candidate_ids")),
    ]


def _creates_cycle(candidate_id: str, node: dict[str, Any], existing_nodes: dict[str, dict[str, Any]]) -> bool:
    adjacency: dict[str, set[str]] = {}
    for target_id, existing in existing_nodes.items():
        if target_id == candidate_id:
            continue
        for source_id in _relation_sources(existing):
            if source_id:
                adjacency.setdefault(source_id, set()).add(target_id)
    for source_id in _relation_sources(node):
        if not source_id:
            continue
        pending = [candidate_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == source_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(adjacency.get(current, ()))
    return False


def validate_candidate_node(
    node: dict[str, Any],
    *,
    existing_ids: set[str],
    creating: bool,
    existing_nodes: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    errors: list[str] = []
    candidate_id = str(node.get("candidate_id") or "").strip()
    if not candidate_id:
        errors.append("Candidate experiment requires `candidate_id`.")
        return errors
    if not _CANDIDATE_ID_RE.fullmatch(candidate_id):
        errors.append(
            "Candidate experiment `candidate_id` must start with an ASCII letter or digit and contain only letters, digits, '.', '_', ':', or '-'."
        )
        return errors
    if creating and candidate_id in existing_ids:
        errors.append(f"Candidate experiment `{candidate_id}` already exists; use mode='update'.")
    if not creating and candidate_id not in existing_ids:
        errors.append(f"Candidate experiment `{candidate_id}` does not exist; use mode='create'.")

    related_ids = _relation_sources(node)
    if candidate_id in related_ids:
        errors.append("Candidate experiment cannot reference itself.")
    missing_ids = sorted({item for item in related_ids if item and item not in existing_ids})
    if missing_ids:
        errors.append("Candidate experiment references unknown candidates: " + ", ".join(missing_ids))
    if not missing_ids and _creates_cycle(candidate_id, node, existing_nodes or {}):
        errors.append("Candidate experiment lineage would create a cycle.")

    code_change_mode = str(node.get("code_change_mode") or "").strip().lower()
    if code_change_mode and code_change_mode not in CANDIDATE_CODE_CHANGE_MODES:
        errors.append(
            "Unknown code_change_mode: "
            f"{code_change_mode}. Expected one of: {', '.join(sorted(CANDIDATE_CODE_CHANGE_MODES))}."
        )
    return errors


def project_candidate_graph(events: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (dict(item) for item in events if str(item.get("candidate_id") or "").strip()),
        key=lambda item: (
            str(item.get("updated_at") or item.get("created_at") or ""),
            int(item.get("event_version") or 1),
            str(item.get("artifact_path") or ""),
        ),
    )
    latest_by_id: dict[str, dict[str, Any]] = {}
    history_counts: dict[str, int] = {}
    for event in ordered:
        candidate_id = str(event.get("candidate_id") or "").strip()
        history_counts[candidate_id] = history_counts.get(candidate_id, 0) + 1
        latest_by_id[candidate_id] = event

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    latest_items = sorted(
        latest_by_id.items(),
        key=lambda pair: (
            str(pair[1].get("updated_at") or pair[1].get("created_at") or ""),
            int(pair[1].get("event_version") or 1),
            str(pair[1].get("artifact_path") or ""),
            pair[0],
        ),
    )
    for candidate_id, raw in latest_items:
        node = dict(raw)
        node["reference_candidate_ids"] = normalize_id_list(node.get("reference_candidate_ids"))
        node["fused_from_candidate_ids"] = normalize_id_list(node.get("fused_from_candidate_ids"))
        node["event_count"] = history_counts.get(candidate_id, 1)
        nodes.append(node)

        parent_id = str(node.get("parent_candidate_id") or "").strip()
        relation_sources = {
            "parent": [parent_id] if parent_id else [],
            "reference": node["reference_candidate_ids"],
            "fused_from": node["fused_from_candidate_ids"],
        }
        for relation, source_ids in relation_sources.items():
            for source_id in source_ids:
                edge_key = (source_id, candidate_id, relation)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({"source": source_id, "target": candidate_id, "relation": relation})

        linked_run_id = str(node.get("linked_run_id") or "").strip()
        if linked_run_id:
            edge_key = (candidate_id, linked_run_id, "validated_by")
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append({"source": candidate_id, "target": linked_run_id, "relation": "validated_by"})

    return {
        "ok": True,
        "schema_version": 1,
        "node_count": len(nodes),
        "event_count": len(ordered),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }
