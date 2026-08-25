from __future__ import annotations

from pathlib import Path

import pytest

import deepscientist.bash_exec.service as bash_exec_service
from deepscientist.config import ConfigManager
from deepscientist.bash_exec.service import BashExecService
from deepscientist.shared import ensure_dir


def _write_session_meta(
    service: BashExecService,
    quest_root: Path,
    *,
    bash_id: str,
    command: str,
    status: str,
    started_at: str,
    updated_at: str,
) -> None:
    service._write_meta(
        quest_root,
        bash_id,
        {
            "bash_id": bash_id,
            "quest_id": quest_root.name,
            "project_id": quest_root.name,
            "task_id": "",
            "cli_server_id": "",
            "agent_id": "",
            "agent_instance_id": None,
            "started_by_user_id": "pytest",
            "stopped_by_user_id": None,
            "kind": "exec",
            "label": None,
            "comment": None,
            "command": command,
            "workdir": "",
            "cwd": str(quest_root),
            "mode": "await",
            "status": status,
            "exit_code": 0 if status == "completed" else None,
            "stop_reason": None,
            "started_at": started_at,
            "finished_at": updated_at if status in {"completed", "failed", "terminated"} else None,
            "updated_at": updated_at,
        },
    )


def test_list_sessions_uses_summary_recent_sessions_fast_path(temp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = BashExecService(temp_home)
    quest_root = ensure_dir(temp_home / "quests" / "001")

    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-001",
        command="echo old",
        status="completed",
        started_at="2026-04-04T10:00:00+00:00",
        updated_at="2026-04-04T10:00:01+00:00",
    )
    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-002",
        command="echo mid",
        status="completed",
        started_at="2026-04-04T10:01:00+00:00",
        updated_at="2026-04-04T10:01:01+00:00",
    )
    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-003",
        command="echo new",
        status="completed",
        started_at="2026-04-04T10:02:00+00:00",
        updated_at="2026-04-04T10:02:01+00:00",
    )

    monkeypatch.setattr(
        service,
        "_list_session_ids",
        lambda quest_root: (_ for _ in ()).throw(AssertionError("full scan should not be used")),
    )

    sessions = service.list_sessions(quest_root, limit=2)

    assert [item["bash_id"] for item in sessions] == ["bash-003", "bash-002"]
    assert [item["command"] for item in sessions] == ["echo new", "echo mid"]


def test_resolve_session_id_uses_summary_latest_session(temp_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = BashExecService(temp_home)
    quest_root = ensure_dir(temp_home / "quests" / "001")

    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-001",
        command="echo old",
        status="completed",
        started_at="2026-04-04T10:00:00+00:00",
        updated_at="2026-04-04T10:00:01+00:00",
    )
    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-002",
        command="echo latest",
        status="completed",
        started_at="2026-04-04T10:05:00+00:00",
        updated_at="2026-04-04T10:05:01+00:00",
    )

    monkeypatch.setattr(
        service,
        "list_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("list_sessions should not be used")),
    )

    assert service.resolve_session_id(quest_root, None) == "bash-002"


def test_list_running_sessions_returns_empty_from_summary_without_full_scan(
    temp_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BashExecService(temp_home)
    quest_root = ensure_dir(temp_home / "quests" / "001")

    _write_session_meta(
        service,
        quest_root,
        bash_id="bash-001",
        command="echo done",
        status="completed",
        started_at="2026-04-04T10:00:00+00:00",
        updated_at="2026-04-04T10:00:01+00:00",
    )

    monkeypatch.setattr(
        service,
        "_list_session_ids",
        lambda quest_root: (_ for _ in ()).throw(AssertionError("full scan should not be used")),
    )

    assert service.list_sessions(quest_root, status="running", limit=10) == []


def test_hardware_env_overrides_follow_selected_gpu_config(temp_home: Path) -> None:
    ConfigManager(temp_home).ensure_files()
    config_manager = ConfigManager(temp_home)
    config = config_manager.load_runtime_config()
    config["hardware"] = {
        "gpu_selection_mode": "selected",
        "selected_gpu_ids": ["1", "3"],
        "include_system_hardware_in_prompt": True,
    }
    config_manager.save_named_payload("config", config)

    service = BashExecService(temp_home)
    overrides = service._hardware_env_overrides()

    assert overrides["CUDA_VISIBLE_DEVICES"] == "1,3"
    assert overrides["NVIDIA_VISIBLE_DEVICES"] == "1,3"
    assert overrides["ROCR_VISIBLE_DEVICES"] == "1,3"


def test_atomic_write_json_retries_transient_permission_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "meta.json"
    original_replace = Path.replace
    attempts = 0

    def replace_once_blocked(source: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("transient sharing violation")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", replace_once_blocked)
    bash_exec_service._atomic_write_json(path, {"status": "completed"})

    assert attempts == 2
    assert path.read_text(encoding="utf-8") == '{\n  "status": "completed"\n}\n'
