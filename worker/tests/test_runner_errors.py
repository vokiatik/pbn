from __future__ import annotations

import json

import requests

from worker_app.retry import retry_job
from worker_app.runner_client import RunnerRequestError, _runner_error_message


def test_runner_moderation_error_is_actionable() -> None:
    response = requests.Response()
    response.status_code = 502
    response.reason = "Bad Gateway"
    response._content = json.dumps(
        {
            "detail": {
                "error": "Your request was rejected by the safety system.",
                "type": "image_generation_user_error",
                "code": "moderation_blocked",
                "request_id": "req_test",
                "moderation_details": {
                    "moderation_stage": "input",
                    "categories": ["violence"],
                },
            }
        }
    ).encode("utf-8")

    message = _runner_error_message(response)

    assert "Moderation stage: input." in message
    assert "Categories: violence." in message
    assert "Try revising the prompt or input image" in message
    assert "OpenAI request ID: req_test." in message


def test_moderation_block_is_not_retried() -> None:
    error = RunnerRequestError("blocked", code="moderation_blocked")

    assert retry_job(None, None, None, None, {}, error) is False  # type: ignore[arg-type]
