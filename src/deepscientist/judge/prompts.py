from __future__ import annotations

import json
from typing import Any


def build_paper_judge_messages(*, judge_input: dict[str, Any]) -> list[dict[str, str]]:
    rubric = judge_input.get("rubric")
    profile = str(judge_input.get("judge_profile") or "research_package")
    system = (
        "You are an evidence-grounded scientific paper and report judge. "
        "Review the supplied manuscript/package like a skeptical but constructive expert reviewer. "
        "Do not invent experiments, citations, metrics, or claims. If evidence is missing, mark it as an evidence gap. "
        "When the target text contains PDF page markers such as '--- Page 4 ---', cite the relevant page in evidence fields. "
        "Treat extraction warnings or omitted pages as confidence limitations. "
        "Before comparing numeric metrics, explicitly determine whether higher or lower values are better and verify the comparison. "
        "Do not assess visual design, legibility, or layout unless visual inspection is explicitly available. "
        "A missing item is an evidence gap, not automatically a fatal issue. Reserve fatal issues for flaws that invalidate the manuscript's central result. "
        "Return only valid JSON."
    )
    if profile == "standalone_pdf":
        system += (
            " This is a standalone manuscript review. Judge only what the manuscript itself reports. "
            "Do not penalize missing DeepScientist contracts, outlines, evidence ledgers, LaTeX sources, code repositories, "
            "experiment logs, configs, or other research-package files that were not requested. "
            "You may describe limits on independent reproducibility, but absence of external package materials is not a fatal issue."
        )
    else:
        system += (
            " This is a research-package review. Package manifests, contracts, provenance, coverage, and supplied artifacts "
            "may be used when scoring package readiness."
        )
    user_payload = {
        "task": "Judge the supplied target using only the rubric, assessment scope, and evidence provided.",
        "output_contract": {
            "overall_score": "optional model estimate; the program ignores it and calculates the final score from assessed dimensions",
            "confidence": "number from 1 to 5",
            "readiness": "optional model estimate; the program calculates final readiness from the final score",
            "recommended_route": "one of write, review, analysis-campaign, baseline, scout, decision, finalize",
            "summary": "short evidence-grounded judgment",
            "scores": {
                str(item.get("id")): {
                    "score": "number from 1 to 5, or null when the supplied input cannot support an assessment",
                    "status": "assessed or not_assessed",
                    "rationale": "why this score is justified",
                    "evidence": "path, manifest field, validation result, or evidence gap",
                }
                for item in rubric
                if isinstance(item, dict) and item.get("id")
            },
            "fatal_issues": [{"summary": "...", "evidence": "...", "recommendation": "..."}],
            "major_issues": [{"summary": "...", "evidence": "...", "recommendation": "..."}],
            "minor_issues": [{"summary": "...", "evidence": "...", "recommendation": "..."}],
            "required_followups": [{"summary": "...", "evidence": "...", "recommendation": "..."}],
            "claim_downgrade_recommendations": [{"summary": "...", "evidence": "...", "recommendation": "..."}],
        },
        "judge_input": judge_input,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]
