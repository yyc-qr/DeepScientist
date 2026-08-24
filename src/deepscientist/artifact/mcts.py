from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from statistics import median
from typing import Any


_ACTIONABLE_STATUSES = {"proposed", "smoke_passed", "promoted"}
_FAILED_STATUSES = {"failed", "smoke_failed", "full_eval_failed", "archived"}
_OBSERVED_STATUSES = {"evaluated", "passed", "success", "promoted", "full_eval_passed"}


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _metric_metadata(candidate: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the recorded primary metric identity and comparison direction."""

    sources: list[dict[str, Any]] = [candidate]
    metrics = candidate.get("metrics_snapshot")
    if isinstance(metrics, dict):
        sources.append(metrics)
        primary = metrics.get("primary")
        if isinstance(primary, dict):
            sources.append(primary)
    for source in sources:
        metric_id = str(source.get("observed_metric_id") or source.get("metric_id") or "").strip()
        direction = str(source.get("observed_direction") or source.get("direction") or "").strip().lower()
        if metric_id or direction:
            return metric_id or None, direction or None
    return None, None


def _is_minimize_direction(direction: str | None) -> bool:
    return str(direction or "").strip().lower() in {"minimize", "lower", "lower_better"}


def _reward_from(value: object, *, direction: str | None) -> float | None:
    if not isinstance(value, dict):
        return None
    # Explicit rewards are already oriented by their producer and must not be inverted.
    for key in ("observed_reward", "reward", "objective_reward"):
        numeric = _number(value.get(key))
        if numeric is not None:
            return numeric
    for key in ("delta_vs_baseline", "metric_delta"):
        numeric = _number(value.get(key))
        if numeric is not None:
            return -numeric if _is_minimize_direction(direction) else numeric
    return None


def _observed_reward(candidate: dict[str, Any]) -> float | None:
    _, candidate_direction = _metric_metadata(candidate)
    direct = _reward_from(candidate, direction=candidate_direction)
    if direct is not None:
        return direct
    metrics = candidate.get("metrics_snapshot")
    if not isinstance(metrics, dict):
        return None
    metric_direction = str(metrics.get("observed_direction") or metrics.get("direction") or candidate_direction or "").strip()
    direct = _reward_from(metrics, direction=metric_direction)
    if direct is not None:
        return direct
    primary = metrics.get("primary")
    primary_direction = metric_direction
    if isinstance(primary, dict):
        primary_direction = str(primary.get("observed_direction") or primary.get("direction") or metric_direction or "").strip()
    return _reward_from(primary, direction=primary_direction)


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(candidate.get("candidate_id") or "").strip()


def _status(candidate: dict[str, Any]) -> str:
    return str(candidate.get("status") or "").strip().lower()


def _family(candidate: dict[str, Any]) -> str:
    return str(candidate.get("mechanism_family") or "").strip() or "unclassified"


def _failure_signature(candidate: dict[str, Any]) -> str:
    return str(candidate.get("failure_signature") or candidate.get("failure_kind") or "").strip()


def _cost(candidate: dict[str, Any]) -> float | None:
    value = _number(candidate.get("compute_seconds"))
    return value if value is not None and value > 0 else None


def _prior(candidate: dict[str, Any]) -> float:
    value = _number(candidate.get("mcts_prior"))
    if value is None:
        return 0.5
    return min(1.0, max(0.0, value))


def _is_actionable(candidate: dict[str, Any]) -> bool:
    if _status(candidate) not in _ACTIONABLE_STATUSES:
        return False
    # A linked main run is the terminal validation for this implementation candidate.
    # Its reward remains useful evidence, but it must not be scheduled a second time.
    return not str(candidate.get("linked_run_id") or "").strip()


def _stable_seed(candidates: list[dict[str, Any]], simulations: int) -> int:
    parts = [str(simulations)]
    for item in sorted(candidates, key=_candidate_id):
        parts.extend(
            [
                _candidate_id(item),
                _status(item),
                _family(item),
                str(_observed_reward(item)),
                str(_cost(item)),
                str(_prior(item)),
                _failure_signature(item),
                str(item.get("parent_candidate_id") or ""),
            ]
        )
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


@dataclass
class _SearchNode:
    candidate: dict[str, Any]
    expected_reward: float
    uncertainty: float
    cost_penalty: float
    repeated_failure_penalty: float
    prior: float
    children: list[str]
    visits: int = 0
    value_sum: float = 0.0

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else self.expected_reward


def _empty_result(*, mode: str, reason: str, actionable_count: int, observed_count: int, root_count: int) -> dict[str, Any]:
    return {
        "policy": "puct_mcts_v1",
        "mode": mode,
        "enabled": False,
        "eligible": False,
        "reason": reason,
        "recommended_candidate_id": None,
        "simulations": 0,
        "actionable_candidate_count": actionable_count,
        "observed_reward_count": observed_count,
        "root_action_count": root_count,
        "ranked_actions": [],
    }


def build_mcts_recommendation(
    candidates: list[dict[str, Any]],
    *,
    mode: str = "auto",
    simulations: int = 96,
    exploration_constant: float = 1.2,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Rank executable candidates with a deterministic, budgeted PUCT-MCTS pass.

    The controller only forecasts from recorded numeric outcomes and candidate metadata.
    It never invents experiment results or executes a command; callers must retain the
    existing experiment gate and treat the returned candidate as a recommendation.
    """

    normalized_mode = str(mode or "auto").strip().lower() or "auto"
    valid_candidates = [dict(item) for item in candidates if isinstance(item, dict) and _candidate_id(item)]
    actionable = [item for item in valid_candidates if _is_actionable(item)]
    observed = [
        (item, _observed_reward(item))
        for item in valid_candidates
        if _status(item) in _OBSERVED_STATUSES and _observed_reward(item) is not None
    ]
    active_ids = {_candidate_id(item) for item in actionable}
    roots = [
        item
        for item in actionable
        if str(item.get("parent_candidate_id") or "").strip() not in active_ids
    ]

    if normalized_mode == "off":
        return _empty_result(
            mode=normalized_mode,
            reason="MCTS is disabled by configuration.",
            actionable_count=len(actionable),
            observed_count=len(observed),
            root_count=len(roots),
        )
    if normalized_mode != "auto":
        return _empty_result(
            mode=normalized_mode,
            reason="Unknown MCTS mode; expected `auto` or `off`.",
            actionable_count=len(actionable),
            observed_count=len(observed),
            root_count=len(roots),
        )
    if len(actionable) < 3 or len(roots) < 3:
        return _empty_result(
            mode=normalized_mode,
            reason="MCTS requires at least 3 actionable root candidates before replacing the frontier fallback.",
            actionable_count=len(actionable),
            observed_count=len(observed),
            root_count=len(roots),
        )
    if len(observed) < 2:
        return _empty_result(
            mode=normalized_mode,
            reason="MCTS requires at least 2 completed candidates with numeric observed reward.",
            actionable_count=len(actionable),
            observed_count=len(observed),
            root_count=len(roots),
        )

    observed_metric_ids = {
        metric_id
        for item, _ in observed
        if (metric_id := _metric_metadata(item)[0])
    }
    if len(observed_metric_ids) > 1:
        return _empty_result(
            mode=normalized_mode,
            reason="MCTS requires completed candidates to use the same primary metric.",
            actionable_count=len(actionable),
            observed_count=len(observed),
            root_count=len(roots),
        )

    completed_rewards = [float(reward) for _, reward in observed if reward is not None]
    global_mean = sum(completed_rewards) / len(completed_rewards)
    global_variance = sum((value - global_mean) ** 2 for value in completed_rewards) / len(completed_rewards)
    global_uncertainty = max(math.sqrt(global_variance), abs(global_mean) * 0.25, 0.02)
    reward_by_family: dict[str, list[float]] = {}
    for item, reward in observed:
        if reward is not None:
            reward_by_family.setdefault(_family(item), []).append(float(reward))
    failure_counts: dict[str, int] = {}
    for item in valid_candidates:
        if _status(item) in _FAILED_STATUSES:
            signature = _failure_signature(item)
            if signature:
                failure_counts[signature] = failure_counts.get(signature, 0) + 1
    known_costs = [value for item in valid_candidates if (value := _cost(item)) is not None]
    cost_scale = float(median(known_costs)) if known_costs else 1.0
    cost_scale = max(cost_scale, 1.0)
    child_ids: dict[str, list[str]] = {}
    for item in actionable:
        parent_id = str(item.get("parent_candidate_id") or "").strip()
        if parent_id in active_ids:
            child_ids.setdefault(parent_id, []).append(_candidate_id(item))

    nodes: dict[str, _SearchNode] = {}
    for item in actionable:
        family_rewards = reward_by_family.get(_family(item), completed_rewards)
        family_mean = sum(family_rewards) / len(family_rewards)
        family_variance = sum((value - family_mean) ** 2 for value in family_rewards) / len(family_rewards)
        uncertainty = max(math.sqrt(family_variance), global_uncertainty)
        candidate_cost = _cost(item)
        cost_penalty = 0.0 if candidate_cost is None else 0.03 * math.log1p(candidate_cost / cost_scale)
        signature = _failure_signature(item)
        repeated_failure_penalty = 0.20 if signature and failure_counts.get(signature, 0) >= 2 else 0.0
        prior = _prior(item)
        expected_reward = family_mean + 0.04 * (prior - 0.5) - cost_penalty - repeated_failure_penalty
        candidate_id = _candidate_id(item)
        nodes[candidate_id] = _SearchNode(
            candidate=item,
            expected_reward=expected_reward,
            uncertainty=uncertainty,
            cost_penalty=cost_penalty,
            repeated_failure_penalty=repeated_failure_penalty,
            prior=prior,
            children=sorted(child_ids.get(candidate_id, [])),
        )

    root_ids = sorted(_candidate_id(item) for item in roots)
    root_visits = 0
    rng = random.Random(_stable_seed(valid_candidates, max(1, int(simulations))))
    total_simulations = max(1, int(simulations))

    def select_child(options: list[str], parent_visits: int) -> str:
        return max(
            options,
            key=lambda candidate_id: (
                nodes[candidate_id].mean_value
                + exploration_constant
                * nodes[candidate_id].prior
                * math.sqrt(max(1, parent_visits))
                / (1 + nodes[candidate_id].visits),
                nodes[candidate_id].expected_reward,
                candidate_id,
            ),
        )

    def rollout(candidate_id: str, depth: int) -> float:
        node = nodes[candidate_id]
        reward = rng.gauss(node.expected_reward, node.uncertainty)
        if depth >= max(1, int(max_depth)) or not node.children:
            return reward
        next_id = max(
            node.children,
            key=lambda child_id: (nodes[child_id].expected_reward, child_id),
        )
        return reward + 0.35 * rollout(next_id, depth + 1)

    for _ in range(total_simulations):
        path: list[str] = []
        current_id = select_child(root_ids, root_visits)
        path.append(current_id)
        while len(path) < max(1, int(max_depth)) and nodes[current_id].children:
            current_id = select_child(nodes[current_id].children, nodes[current_id].visits)
            path.append(current_id)
        reward = rollout(current_id, len(path))
        root_visits += 1
        for candidate_id in path:
            nodes[candidate_id].visits += 1
            nodes[candidate_id].value_sum += reward

    def result_item(candidate_id: str) -> dict[str, Any]:
        node = nodes[candidate_id]
        puct_score = (
            node.mean_value
            + exploration_constant
            * node.prior
            * math.sqrt(max(1, root_visits))
            / (1 + node.visits)
        )
        return {
            "candidate_id": candidate_id,
            "puct_score": round(puct_score, 6),
            "mean_rollout_reward": round(node.mean_value, 6),
            "estimated_reward": round(node.expected_reward, 6),
            "uncertainty": round(node.uncertainty, 6),
            "prior": round(node.prior, 6),
            "visits": node.visits,
            "cost_penalty": round(node.cost_penalty, 6),
            "repeated_failure_penalty": round(node.repeated_failure_penalty, 6),
            "future_child_count": len(node.children),
        }

    ranked_actions = sorted(
        (result_item(candidate_id) for candidate_id in root_ids),
        key=lambda item: (item["puct_score"], item["mean_rollout_reward"], item["candidate_id"]),
        reverse=True,
    )
    return {
        "policy": "puct_mcts_v1",
        "mode": normalized_mode,
        "enabled": True,
        "eligible": True,
        "reason": "MCTS ranked actionable candidates from recorded rewards, cost, failure history, and graph lineage.",
        "recommended_candidate_id": ranked_actions[0]["candidate_id"],
        "simulations": total_simulations,
        "actionable_candidate_count": len(actionable),
        "observed_reward_count": len(observed),
        "root_action_count": len(root_ids),
        "ranked_actions": ranked_actions,
    }
