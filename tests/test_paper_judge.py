from __future__ import annotations

import json
from pathlib import Path

import pytest
import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from deepscientist.cli import build_parser, main
from deepscientist.config.models import default_config
from deepscientist.artifact import ArtifactService
from deepscientist.config import ConfigManager
from deepscientist.home import ensure_home_layout
from deepscientist.judge import PaperJudgeService, extract_pdf_text
from deepscientist.judge.client import JudgeClientConfig, OpenAICompatibleJudgeClient, extract_json_object
from deepscientist.judge.prompts import build_paper_judge_messages
from deepscientist.judge.schemas import (
    PaperJudgeError,
    normalize_judge_profile,
    normalize_judge_report,
    normalize_rubric,
    rubric_for_profile,
)


def _write_pdf(path: Path, page_texts: list[str]) -> Path:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def test_extract_json_object_tolerates_wrapped_model_output() -> None:
    payload = extract_json_object('Here is the judgment:\n```json\n{"overall_score": 4, "readiness": "reviewable"}\n```')

    assert payload == {"overall_score": 4, "readiness": "reviewable"}


def test_extract_json_object_rejects_empty_or_non_object_output() -> None:
    with pytest.raises(PaperJudgeError):
        extract_json_object("")
    with pytest.raises(PaperJudgeError):
        extract_json_object("[1, 2, 3]")


def test_normalize_judge_report_clamps_scores_and_fills_rubric() -> None:
    rubric = normalize_rubric(
        [
            {"id": "method_soundness", "label": "Method soundness"},
            {"id": "claim_support", "label": "Claim support"},
        ]
    )

    report = normalize_judge_report(
        {
            "overall_score": 9,
            "confidence": 0,
            "readiness": "submission-ready",
            "recommended_route": "finalize",
            "summary": "Strong enough to ship.",
            "scores": {
                "method_soundness": {
                    "score": 6,
                    "rationale": "Method is specified.",
                    "evidence": "paper/draft.md",
                }
            },
            "major_issues": [{"summary": "Missing ablation", "fix": "Add or downgrade the claim."}],
        },
        rubric=rubric,
    )

    assert report["overall_score"] == 5.0
    assert report["confidence"] == 1.0
    assert report["readiness"] == "submission_ready"
    assert report["recommended_route"] == "finalize"
    assert report["scores"]["method_soundness"]["score"] == 5.0
    assert report["scores"]["claim_support"]["score"] is None
    assert report["scores"]["claim_support"]["status"] == "not_assessed"
    assert report["score_calculation"]["assessed_dimension_count"] == 1
    assert report["major_issues"][0]["recommendation"] == "Add or downgrade the claim."


def test_normalize_judge_report_calculates_overall_from_assessed_dimensions() -> None:
    rubric = normalize_rubric([{"id": "method"}, {"id": "evidence"}, {"id": "visual"}])

    report = normalize_judge_report(
        {
            "overall_score": 1,
            "readiness": "not_ready",
            "scores": {
                "method": {"score": 5},
                "evidence": {"score": 3},
                "visual": {"score": None, "status": "not_assessed", "rationale": "No images supplied."},
            },
        },
        rubric=rubric,
        judge_profile="standalone_pdf",
    )

    assert report["overall_score"] == 4.0
    assert report["readiness"] == "reviewable"
    assert report["score_calculation"]["assessed_dimension_count"] == 2
    assert report["scores"]["visual"]["score"] is None
    assert any(item["id"] == "figure_table_quality" for item in report["unassessed_dimensions"])


def test_judge_profiles_are_strict_and_have_distinct_rubrics() -> None:
    standalone_ids = {item["id"] for item in rubric_for_profile("standalone_pdf")}
    package_ids = {item["id"] for item in rubric_for_profile("research_package")}

    assert "manuscript_completeness" in standalone_ids
    assert "submission_readiness" not in standalone_ids
    assert "reproducibility" not in standalone_ids
    assert "submission_readiness" in package_ids
    assert normalize_judge_profile("default") == "research_package"
    with pytest.raises(PaperJudgeError, match="Unsupported paper judge profile"):
        normalize_judge_profile("unknown")


def test_standalone_input_excludes_research_package_gates() -> None:
    payload = PaperJudgeService().build_input(
        quest_id="001",
        package_type="review_package",
        target_path="paper/judge_input.pdf",
        target_text="--- Page 1 ---\nA manuscript.",
        target_exists=True,
        manifest={"writing_plan_path": "paper/outline.md"},
        paper_contract={"missing": ["selected_outline"]},
        paper_contract_health={"ok": False},
        coverage={"missing_sections": ["methods"]},
        language={"ok": False},
        evidence_paths=["paper/evidence_ledger.json"],
        judge_profile="standalone_pdf",
    )

    assert payload["judge_profile"] == "standalone_pdf"
    assert payload["assessment_scope"] == "manuscript_content_only"
    assert "manifest" not in payload
    assert "paper_contract" not in payload
    assert "manuscript_coverage" not in payload
    assert "evidence_paths" not in payload


def test_standalone_prompt_enforces_manuscript_only_and_metric_direction() -> None:
    messages = build_paper_judge_messages(
        judge_input={"judge_profile": "standalone_pdf", "rubric": rubric_for_profile("standalone_pdf")}
    )
    system = messages[0]["content"]

    assert "Do not penalize missing DeepScientist contracts" in system
    assert "whether higher or lower values are better" in system
    assert "Do not assess visual design" in system


def test_extract_pdf_text_preserves_page_markers_and_metadata(tmp_path: Path) -> None:
    pdf_path = _write_pdf(
        tmp_path / "paper.pdf",
        [
            "Introduction: We evaluate a reproducible scientific method on a public benchmark dataset.",
            "Results: The proposed method reaches 78 percent accuracy compared with 71 percent for the baseline.",
        ],
    )

    text, metadata = extract_pdf_text(pdf_path, config={"min_text_chars_per_page": 20})

    assert "--- Page 1 ---" in text
    assert "--- Page 2 ---" in text
    assert "78 percent accuracy" in text
    assert metadata["format"] == "pdf"
    assert metadata["page_count"] == 2
    assert metadata["selected_pages"] == [1, 2]
    assert metadata["suspected_scanned"] is False
    assert len(metadata["sha256"]) == 64


def test_extract_pdf_text_rejects_image_only_or_blank_pdf(tmp_path: Path) -> None:
    pdf_path = _write_pdf(tmp_path / "scanned.pdf", [""])

    with pytest.raises(PaperJudgeError, match="likely scanned"):
        extract_pdf_text(pdf_path, config={"min_text_chars_per_page": 20})


def test_judge_cli_minimal_pdf_dry_run_creates_report(temp_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pdf_path = _write_pdf(
        tmp_path / "minimal-paper.pdf",
        [
            "Abstract: We compare a baseline and a proposed method using one hundred held-out examples.",
            "Results: Accuracy improves from 71 percent to 78 percent, but significance was not tested.",
        ],
    )

    exit_code = main(["--home", str(temp_home), "judge", str(pdf_path), "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["judge_profile"] == "standalone_pdf"
    assert payload["target_metadata"]["format"] == "pdf"
    assert payload["target_metadata"]["page_count"] == 2
    assert Path(payload["judge_report_path"]).exists()
    assert Path(payload["judge_json_path"]).exists()
    assert Path(payload["extraction_manifest_path"]).exists()
    extracted_text = Path(payload["extracted_text_path"]).read_text(encoding="utf-8")
    assert "--- Page 2 ---" in extracted_text
    assert "Accuracy improves" in extracted_text
    report = json.loads(Path(payload["judge_json_path"]).read_text(encoding="utf-8"))
    assert report["judge_profile"] == "standalone_pdf"
    assert report["score_calculation"]["assessed_dimension_count"] == 8
    assert any(item["id"] == "figure_table_quality" for item in report["unassessed_dimensions"])
    judge_input = json.loads((Path(payload["judge_json_path"]).parent / "judge_input_manifest.json").read_text(encoding="utf-8"))
    assert "paper_contract" not in judge_input
    assert "manuscript_coverage" not in judge_input


def test_parser_accepts_minimal_judge_command() -> None:
    args = build_parser().parse_args(["judge", "paper.pdf", "--dry-run"])

    assert args.command == "judge"
    assert args.input_path == "paper.pdf"
    assert args.dry_run is True
    assert args.judge_profile == "standalone_pdf"


def test_default_judge_config_enables_text_pdf_extraction(tmp_path: Path) -> None:
    config = default_config(tmp_path)["judge"]

    assert config["provider"] == "runner_default"
    assert config["model"] == "inherit"
    assert config["pdf"]["enabled"] is True
    assert config["pdf"]["parser"] == "pypdf"


def test_dedicated_judge_environment_overrides_runner_inheritance(
    temp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_home_layout(temp_home)
    ConfigManager(temp_home).ensure_files()
    monkeypatch.setenv("DEEPSCIENTIST_JUDGE_API_BASE", "https://judge.example/v1")
    monkeypatch.setenv("DEEPSCIENTIST_JUDGE_MODEL", "deepseek-v4-flash")

    config = ArtifactService(temp_home)._paper_judge_config()

    assert config["api_base"] == "https://judge.example/v1"
    assert config["model"] == "deepseek-v4-flash"


def test_judge_client_uses_default_environment_api_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"overall_score": 4}'}}]}

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> FakeResponse:
            captured.update({"url": url, "headers": headers, "payload": json})
            return FakeResponse()

    monkeypatch.setenv("DEEPSCIENTIST_JUDGE_API_BASE", "https://judge.example/v1/")
    monkeypatch.setenv("DEEPSCIENTIST_JUDGE_API_KEY", "secret-test-key")
    monkeypatch.setenv("DEEPSCIENTIST_JUDGE_MODEL", "judge-model")
    monkeypatch.setattr("deepscientist.judge.client.httpx.Client", FakeClient)

    report, _raw = OpenAICompatibleJudgeClient(JudgeClientConfig()).complete_json(
        [{"role": "user", "content": "Judge this paper."}]
    )

    assert report == {"overall_score": 4}
    assert captured["url"] == "https://judge.example/v1/chat/completions"
    assert captured["headers"] == {"Content-Type": "application/json", "Authorization": "Bearer secret-test-key"}
    assert captured["payload"]["model"] == "judge-model"  # type: ignore[index]


def test_judge_client_preserves_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://judge.example/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "Model is not available", "type": "invalid_request_error"}},
    )

    class FailingClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "FailingClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
            return response

    monkeypatch.setattr("deepscientist.judge.client.httpx.Client", FailingClient)
    client = OpenAICompatibleJudgeClient(
        JudgeClientConfig(api_base="https://judge.example/v1", api_key="key", model="missing-model")
    )

    with pytest.raises(PaperJudgeError) as captured_error:
        client.complete_json([{"role": "user", "content": "Judge this paper."}])

    assert captured_error.value.details["status_code"] == 400
    assert captured_error.value.details["model"] == "missing-model"
    assert "Model is not available" in captured_error.value.details["response"]


def test_judge_client_retries_empty_model_content(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class RetryResponse:
        def __init__(self, content: str, finish_reason: str) -> None:
            self.content = content
            self.finish_reason = finish_reason

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {"content": self.content},
                        "finish_reason": self.finish_reason,
                    }
                ],
                "usage": {"total_tokens": 100},
            }

    class RetryClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "RetryClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> RetryResponse:
            calls.append(json)
            if len(calls) == 1:
                return RetryResponse("", "stop")
            return RetryResponse('{"overall_score": 4}', "stop")

    monkeypatch.setattr("deepscientist.judge.client.httpx.Client", RetryClient)
    client = OpenAICompatibleJudgeClient(
        JudgeClientConfig(api_base="https://judge.example/v1", api_key="key", model="judge-model")
    )

    report, raw = client.complete_json([{"role": "user", "content": "Return JSON."}])

    assert report == {"overall_score": 4}
    assert len(calls) == 2
    assert raw["_judge_retry"]["attempt_count"] == 2
    assert "previous response was empty" in calls[1]["messages"][-1]["content"]  # type: ignore[index]


def test_deepseek_judge_disables_thinking_for_structured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class DeepSeekResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"overall_score": 4}'}, "finish_reason": "stop"}]}

    class DeepSeekClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> "DeepSeekClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> DeepSeekResponse:
            captured.update(json)
            return DeepSeekResponse()

    monkeypatch.setattr("deepscientist.judge.client.httpx.Client", DeepSeekClient)
    client = OpenAICompatibleJudgeClient(
        JudgeClientConfig(api_base="https://api.deepseek.com", api_key="key", model="deepseek-v4-flash")
    )

    report, _raw = client.complete_json([{"role": "user", "content": "Return JSON."}])

    assert report == {"overall_score": 4}
    assert captured["thinking"] == {"type": "disabled"}
