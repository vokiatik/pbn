from __future__ import annotations

from pathlib import Path

from worker_app.config import WorkerConfig
from worker_app.constants import PUBLIC_AI_FILES, PUBLIC_PBN_OPTION_FILES
from worker_app.jobs import JobProcessor


class FakeBackend:
    def __init__(self) -> None:
        self.statuses: list[str] = []
        self.file_batches: list[list[dict]] = []
        self.options: list[dict] = []
        self.selection: str | None = None
        self.quality: dict | None = None

    def post_status(self, project_id: str, status: str, progress: int = 0, message: str = "", error_message: str = "") -> bool:
        self.statuses.append(status)
        return True

    def post_files(self, project_id: str, files: list[dict]) -> list[dict]:
        self.file_batches.append(files)
        return files

    def post_pbn_options(self, project_id: str, options: list[dict]) -> None:
        self.options = options

    def post_ai_quality(self, project_id: str, quality: dict) -> None:
        self.quality = quality

    def post_pbn_selection(self, project_id: str, difficulty: str) -> None:
        self.selection = difficulty


class FakeRunner:
    def __init__(self) -> None:
        self.generate_calls = 0
        self.continue_calls = 0
        self.finalize_calls = 0

    def generate_ai_image(self, **kwargs) -> dict:
        self.generate_calls += 1
        return {
            "ok": True,
            "result": {
                "metrics": {
                    "ai_quality": {
                        "status": "pass",
                        "codes": [],
                        "message": "Good source",
                        "metrics": {},
                    }
                }
            },
        }

    def continue_ai_pipeline(self, **kwargs) -> dict:
        self.continue_calls += 1
        return {"ok": True, "result": {"metrics": {"options": [{"difficulty": "hard", "status": "valid"}]}}}

    def finalize_pbn_option(self, **kwargs) -> dict:
        self.finalize_calls += 1
        return {"ok": True}


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, payload: dict) -> None:
        self.events.append(payload)


def test_generate_ai_image_job_registers_only_review_image(tmp_path: Path) -> None:
    _write_project_file(tmp_path, "pipeline_ai/ai/simplified.png")
    backend = FakeBackend()
    runner = FakeRunner()
    events = FakeEvents()
    processor = JobProcessor(None, _config(), backend, runner, events)  # type: ignore[arg-type]

    processor.process_ai_image_job(_payload(tmp_path))

    assert runner.generate_calls == 1
    assert backend.statuses[-1] == "ai_image_ready"
    assert backend.quality is not None
    assert backend.quality["status"] == "pass"
    assert [[file["file_type"] for file in batch] for batch in backend.file_batches] == [["ai_simplified"]]


def test_continue_ai_pipeline_job_registers_saved_options(tmp_path: Path) -> None:
    for _, rel_path in PUBLIC_PBN_OPTION_FILES:
        _write_project_file(tmp_path, rel_path)
    for legacy in ("easy", "medium"):
        _write_project_file(tmp_path, f"pipeline_ai/options/{legacy}/numbered_template.png")
    backend = FakeBackend()
    runner = FakeRunner()
    events = FakeEvents()
    processor = JobProcessor(None, _config(), backend, runner, events)  # type: ignore[arg-type]

    processor.process_pbn_pipeline_job(_payload(tmp_path))

    assert runner.continue_calls == 1
    assert backend.statuses[-1] == "pbn_options_ready"
    assert backend.options == [{"difficulty": "hard", "status": "valid"}]
    registered_types = {file["file_type"] for file in backend.file_batches[-1]}
    assert "ai_simplified" in registered_types
    assert "ai_hard_template_preview" in registered_types
    assert not any("easy" in file_type or "medium" in file_type for file_type in registered_types)
    assert "ai_final" not in registered_types


def test_selection_job_registers_only_after_explicit_choice(tmp_path: Path) -> None:
    for _, rel_path in PUBLIC_AI_FILES:
        _write_project_file(tmp_path, rel_path)
    backend = FakeBackend()
    runner = FakeRunner()
    processor = JobProcessor(None, _config(), backend, runner, FakeEvents())  # type: ignore[arg-type]
    payload = {**_payload(tmp_path), "difficulty": "hard"}

    processor.process_pbn_selection_job(payload)

    assert runner.finalize_calls == 1
    assert backend.selection == "hard"
    assert backend.statuses[-1] == "ai_completed"
    assert "ai_final" in {file["file_type"] for file in backend.file_batches[-1]}


def _payload(project_root: Path) -> dict:
    return {
        "project_id": "project-1",
        "public_id": "public-1",
        "project_root": str(project_root),
        "input_path": str(project_root / "original" / "original.png"),
        "settings": {},
    }


def _write_project_file(project_root: Path, rel_path: str) -> None:
    path = project_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake")


def _config() -> WorkerConfig:
    return WorkerConfig(
        redis_addr="redis",
        redis_port=6379,
        redis_db=0,
        redis_password=None,
        queue_name="pbn:jobs",
        events_channel="pbn:events",
        concurrency=1,
        api_base="http://backend:8080/api/internal",
        api_secret="secret",
        python_runner_base_url="http://pbn:8081",
    )
