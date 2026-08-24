from __future__ import annotations

from typing import Any


DEFAULT_PAPER_JUDGE_RUBRIC: list[dict[str, Any]] = [
    {
        "id": "problem_significance",
        "label": "Problem significance",
        "description": "The work addresses an important, well-motivated research problem.",
    },
    {
        "id": "novelty_positioning",
        "label": "Novelty and positioning",
        "description": "The contribution is distinct from nearby work and its novelty boundary is honest.",
    },
    {
        "id": "method_soundness",
        "label": "Method soundness",
        "description": "The method is technically plausible, clearly specified, and matched to the problem.",
    },
    {
        "id": "evidence_sufficiency",
        "label": "Evidence sufficiency",
        "description": "The experiments, analyses, and artifacts are enough to support the paper-facing claims.",
    },
    {
        "id": "baseline_comparability",
        "label": "Baseline comparability",
        "description": "Baselines, metrics, splits, and evaluation protocols make the comparison fair.",
    },
    {
        "id": "claim_support",
        "label": "Claim support",
        "description": "Central claims are grounded in durable evidence rather than prose or plans.",
    },
    {
        "id": "reproducibility",
        "label": "Reproducibility",
        "description": "Code, configs, logs, data references, and result paths are traceable enough to reproduce the claims.",
    },
    {
        "id": "writing_clarity",
        "label": "Writing clarity",
        "description": "The narrative, structure, terminology, and section flow are clear to a skeptical reader.",
    },
    {
        "id": "figure_table_quality",
        "label": "Figure and table quality",
        "description": "Figures and tables answer important reader or reviewer questions.",
    },
    {
        "id": "submission_readiness",
        "label": "Submission readiness",
        "description": "The package is close to a defensible review or submission state.",
    },
]

STANDALONE_PDF_RUBRIC: list[dict[str, Any]] = [
    {
        "id": "problem_significance",
        "label": "Problem significance",
        "description": "The manuscript addresses an important, well-motivated research problem.",
    },
    {
        "id": "novelty_positioning",
        "label": "Novelty and positioning",
        "description": "The contribution is distinct from nearby work and its novelty boundary is honest.",
    },
    {
        "id": "method_soundness",
        "label": "Method soundness",
        "description": "The method is technically plausible, clearly specified, and matched to the problem.",
    },
    {
        "id": "evidence_sufficiency",
        "label": "Experimental sufficiency",
        "description": "The experiments and analyses reported in the manuscript are sufficient for its claims.",
    },
    {
        "id": "baseline_comparability",
        "label": "Baseline comparability",
        "description": "Baselines, metrics, splits, and evaluation protocols make the comparison fair.",
    },
    {
        "id": "claim_support",
        "label": "Claim support",
        "description": "The manuscript's central claims are supported by its reported evidence.",
    },
    {
        "id": "writing_clarity",
        "label": "Writing clarity",
        "description": "The narrative, structure, terminology, and section flow are clear to a skeptical reader.",
    },
    {
        "id": "manuscript_completeness",
        "label": "Manuscript completeness",
        "description": "The manuscript contains the sections and explanations needed for an informed paper review.",
    },
]

JUDGE_PROFILES = {"standalone_pdf", "research_package"}
JUDGE_PROFILE_ALIASES = {"default": "research_package"}

READINESS_LEVELS = {"not_ready", "weak_reviewable", "reviewable", "submission_ready"}
RECOMMENDED_ROUTES = {"write", "review", "analysis-campaign", "baseline", "scout", "decision", "finalize"}


class PaperJudgeError(RuntimeError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def normalize_rubric(rubric: object = None) -> list[dict[str, Any]]:
    source = rubric if isinstance(rubric, list) and rubric else DEFAULT_PAPER_JUDGE_RUBRIC
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(source):
        payload = item if isinstance(item, dict) else {"id": str(item or "").strip()}
        rubric_id = str(payload.get("id") or payload.get("metric_id") or f"criterion_{index + 1}").strip()
        if not rubric_id or rubric_id in seen:
            continue
        seen.add(rubric_id)
        normalized.append(
            {
                "id": rubric_id,
                "label": str(payload.get("label") or rubric_id.replace("_", " ").title()).strip(),
                "description": str(payload.get("description") or payload.get("rubric") or "").strip(),
                "scale": payload.get("scale") or "1-5, where 5 is strongest",
            }
        )
    return normalized


def normalize_judge_profile(value: object) -> str:
    profile = str(value or "").strip().lower().replace("-", "_") or "research_package"
    profile = JUDGE_PROFILE_ALIASES.get(profile, profile)
    if profile not in JUDGE_PROFILES:
        raise PaperJudgeError(
            f"Unsupported paper judge profile: {value}",
            details={"supported_profiles": sorted(JUDGE_PROFILES)},
        )
    return profile


def rubric_for_profile(profile: object, rubric: object = None) -> list[dict[str, Any]]:
    if isinstance(rubric, list) and rubric:
        return normalize_rubric(rubric)
    normalized_profile = normalize_judge_profile(profile)
    source = STANDALONE_PDF_RUBRIC if normalized_profile == "standalone_pdf" else DEFAULT_PAPER_JUDGE_RUBRIC
    return normalize_rubric(source)


def clamp_score(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(1.0, min(5.0, number))


def normalize_issue_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        payload = item if isinstance(item, dict) else {"summary": str(item or "").strip()}
        summary = str(payload.get("summary") or payload.get("issue") or payload.get("title") or "").strip()
        if not summary:
            continue
        result.append(
            {
                "id": str(payload.get("id") or f"issue-{index:03d}").strip(),
                "summary": summary,
                "evidence": str(payload.get("evidence") or payload.get("evidence_path") or "").strip() or None,
                "recommendation": str(payload.get("recommendation") or payload.get("fix") or "").strip() or None,
            }
        )
    return result


def normalize_judge_report(
    raw_report: object,
    *,
    rubric: list[dict[str, Any]],
    judge_profile: str = "research_package",
) -> dict[str, Any]:
    if not isinstance(raw_report, dict):
        raise PaperJudgeError("Paper judge response must be a JSON object.")
    normalized_profile = normalize_judge_profile(judge_profile)
    rubric_ids = [str(item.get("id") or "").strip() for item in rubric if str(item.get("id") or "").strip()]
    raw_scores = raw_report.get("scores") if isinstance(raw_report.get("scores"), dict) else {}
    scores: dict[str, dict[str, Any]] = {}
    numeric_scores: list[float] = []
    for rubric_id in rubric_ids:
        raw_item = raw_scores.get(rubric_id)
        payload = raw_item if isinstance(raw_item, dict) else {"score": raw_item}
        raw_score = payload.get("score")
        status = str(payload.get("status") or "").strip().lower().replace("-", "_")
        score: float | None
        if raw_score is None or status in {"not_assessed", "not_applicable", "unavailable"}:
            score = None
            status = "not_assessed"
        else:
            score = clamp_score(raw_score, default=1.0)
            numeric_scores.append(score)
            status = "assessed"
        scores[rubric_id] = {
            "score": score,
            "status": status,
            "rationale": str(payload.get("rationale") or payload.get("reason") or "").strip(),
            "evidence": str(payload.get("evidence") or payload.get("evidence_path") or "").strip() or None,
        }
    overall_score = sum(numeric_scores) / len(numeric_scores) if numeric_scores else 1.0
    readiness = _readiness_from_score(overall_score)
    route = str(raw_report.get("recommended_route") or "").strip().lower()
    if route not in RECOMMENDED_ROUTES:
        route = "review" if readiness in {"weak_reviewable", "reviewable"} else "write"
    confidence = clamp_score(raw_report.get("confidence"), default=3.0)
    unassessed_dimensions = [
        {"id": rubric_id, "reason": item.get("rationale") or "The supplied input did not support this assessment."}
        for rubric_id, item in scores.items()
        if item.get("status") == "not_assessed"
    ]
    if normalized_profile == "standalone_pdf":
        unassessed_dimensions.append(
            {
                "id": "figure_table_quality",
                "reason": "Visual design is not assessed because the current PDF pipeline supplies extracted text only.",
            }
        )
    return {
        "judge_profile": normalized_profile,
        "overall_score": round(overall_score, 3),
        "confidence": round(confidence, 3),
        "readiness": readiness,
        "recommended_route": route,
        "summary": str(raw_report.get("summary") or "").strip(),
        "scores": scores,
        "score_calculation": {
            "method": "arithmetic_mean_of_assessed_dimensions",
            "assessed_dimension_count": len(numeric_scores),
            "final_score": round(overall_score, 3),
        },
        "unassessed_dimensions": unassessed_dimensions,
        "fatal_issues": normalize_issue_list(raw_report.get("fatal_issues")),
        "major_issues": normalize_issue_list(raw_report.get("major_issues")),
        "minor_issues": normalize_issue_list(raw_report.get("minor_issues")),
        "required_followups": normalize_issue_list(raw_report.get("required_followups")),
        "claim_downgrade_recommendations": normalize_issue_list(raw_report.get("claim_downgrade_recommendations")),
    }


def _readiness_from_score(score: float) -> str:
    if score >= 4.35:
        return "submission_ready"
    if score >= 3.5:
        return "reviewable"
    if score >= 2.6:
        return "weak_reviewable"
    return "not_ready"
