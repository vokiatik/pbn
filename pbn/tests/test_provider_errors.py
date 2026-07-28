from __future__ import annotations

import json

from ai_pipeline.http_client import provider_request_error


def test_openai_moderation_error_preserves_safe_details() -> None:
    body = json.dumps(
        {
            "error": {
                "message": "Your request was rejected by the safety system.",
                "type": "image_generation_user_error",
                "code": "moderation_blocked",
                "moderation_details": {
                    "moderation_stage": "input",
                    "categories": ["violence"],
                    "internal_score": 0.99,
                },
            }
        }
    ).encode("utf-8")

    error = provider_request_error(400, body, {"X-Request-ID": "req_test"})

    assert str(error) == "Your request was rejected by the safety system."
    assert error.retryable is False
    assert error.to_detail() == {
        "error": "Your request was rejected by the safety system.",
        "type": "image_generation_user_error",
        "code": "moderation_blocked",
        "request_id": "req_test",
        "moderation_details": {
            "moderation_stage": "input",
            "categories": ["violence"],
        },
    }
