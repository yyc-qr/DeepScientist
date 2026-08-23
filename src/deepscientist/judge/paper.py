from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..shared import read_json, read_text, utc_now
from .client import JudgeClientConfig, OpenAICompatibleJudgeClient
from .prompts import build_paper_judge_messages
from .schemas import PaperJudgeError, normalize_judge_profile, normalize_judge_report, rubric_for_profile


class PaperJudgeService:
    def __init__(self, *, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    def build_input(
        self,
        *,
        quest_id: str,
        package_type: str,
        target_path: str | None,
        target_text: str,
        target_exists: bool,
        manifest: dict[str, Any],
        paper_contract: dict[str, Any],
        paper_contract_health: dict[str, Any],
        coverage: dict[str, Any],
        language: dict[str, Any],
        evidence_paths: list[str],
        judge_profile: str = "research_package",
        target_metadata: dict[str, Any] | None = None,
        extra_context: dict[str, Any] | None = None,
        rubric: object = None,
    ) -> dict[str, Any]:
        profile = normalize_judge_profile(judge_profile)
        payload = {
            "schema_version": 1,
            "quest_id": quest_id,
            "created_at": utc_now(),
            "judge_profile": profile,
            "package_type": package_type,
            "assessment_scope": (
                "manuscript_content_only"
                if profile == "standalone_pdf"
                else "manuscript_and_research_package"
            ),
            "capabilities": {"text_extraction": True, "visual_inspection": False},
            "target": {
                "path": target_path,
                "exists": target_exists,
                "text_sample": target_text,
                **dict(target_metadata or {}),
            },
            "extra_context": dict(extra_context or {}),
            "rubric": rubric_for_profile(profile, rubric),
        }
        if profile == "research_package":
            payload.update(
                {
                    "manifest": manifest,
                    "paper_contract": paper_contract,
                    "paper_contract_health": paper_contract_health,
                    "manuscript_coverage": coverage,
                    "manuscript_language": language,
                    "evidence_paths": evidence_paths,
                }
            )
        return payload

    def judge(
        self,
        *,
        judge_input: dict[str, Any],
        provider: str | None = None,
        model: str | None = None,
        api_base: str | None = None,
        api_key_env: str | None = None,
        dry_run: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = normalize_judge_profile(judge_input.get("judge_profile"))
        rubric = rubric_for_profile(profile, judge_input.get("rubric"))
        if dry_run:
            report = self._dry_run_report(judge_input=judge_input, rubric=rubric)
            return report, {"dry_run": True}
        client_config = self._client_config(
            provider=provider,
            model=model,
            api_base=api_base,
            api_key_env=api_key_env,
        )
        if client_config.provider not in {"openai_compatible", "runner_default", "openai-compatible"}:
            raise PaperJudgeError(f"Unsupported paper judge provider: {client_config.provider}")
        client = OpenAICompatibleJudgeClient(client_config)
        raw_report, raw_response = client.complete_json(build_paper_judge_messages(judge_input={**judge_input, "rubric": rubric}))
        report = normalize_judge_report(raw_report, rubric=rubric, judge_profile=profile)
        return report, raw_response

    def _client_config(
        self,
        *,
        provider: str | None,
        model: str | None,
        api_base: str | None,
        api_key_env: str | None,
    ) -> JudgeClientConfig:
        cfg = dict(self.config or {})
        return JudgeClientConfig(
            provider=str(provider or cfg.get("provider") or "openai_compatible").strip(),
            api_base=str(api_base or cfg.get("api_base") or "").strip() or None,
            api_key=str(cfg.get("api_key") or "").strip() or None,
            api_key_env=str(api_key_env or cfg.get("api_key_env") or "").strip() or None,
            model=str(model or cfg.get("model") or "").strip() or None,
            temperature=float(cfg.get("temperature", 0.1) or 0.1),
            max_output_tokens=int(cfg.get("max_output_tokens", 6000) or 6000),
            timeout_seconds=float(cfg.get("timeout_seconds", 120.0) or 120.0),
            empty_response_max_attempts=int(cfg.get("empty_response_max_attempts", 3) or 3),
            thinking=str(cfg.get("thinking") or "auto").strip().lower() or "auto",
        )

    @staticmethod
    def _dry_run_report(*, judge_input: dict[str, Any], rubric: list[dict[str, Any]]) -> dict[str, Any]:
        profile = normalize_judge_profile(judge_input.get("judge_profile"))
        coverage = judge_input.get("manuscript_coverage") if isinstance(judge_input.get("manuscript_coverage"), dict) else {}
        language = judge_input.get("manuscript_language") if isinstance(judge_input.get("manuscript_language"), dict) else {}
        target = judge_input.get("target") if isinstance(judge_input.get("target"), dict) else {}
        coverage_ok = bool(coverage.get("ok") or coverage.get("submission_ready"))
        language_ok = bool(language.get("ok"))
        target_exists = bool(target.get("exists"))
        base = 3.0
        if profile == "research_package" and coverage_ok:
            base += 0.5
        if profile == "research_package" and language_ok:
            base += 0.4
        if not target_exists:
            base -= 1.0
        raw = {
            "overall_score": max(1.0, min(5.0, base)),
            "confidence": 2.0,
            "recommended_route": "review",
            "summary": "Dry-run paper judge report generated without calling a model API.",
            "scores": {
                str(item["id"]): {
                    "score": max(1.0, min(5.0, base)),
                    "rationale": "Dry-run placeholder score based on local gates only.",
                    "evidence": "local validation gates",
                }
                for item in rubric
            },
            "fatal_issues": [] if target_exists else [{"summary": "Target manuscript/report was not found.", "evidence": target.get("path"), "recommendation": "Provide a durable draft or bundle path before model judging."}],
            "major_issues": [],
            "minor_issues": [],
            "required_followups": [],
            "claim_downgrade_recommendations": [],
        }
        return normalize_judge_report(raw, rubric=rubric, judge_profile=profile)


def read_manifest(path: Path) -> dict[str, Any]:
    payload = read_json(path, {})
    return payload if isinstance(payload, dict) else {}


def read_text_sample(path: Path | None, *, max_chars: int) -> tuple[str, bool]:
    if path is None:
        return "", False
    if not path.exists() or not path.is_file():
        return "", False
    return read_text(path)[:max_chars], True
