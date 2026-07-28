from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .models import ProviderRequestError


@dataclass(frozen=True)
class PreparedHTTPRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class HTTPResponse:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> object:
        return json.loads(self.body.decode("utf-8"))


class HTTPTransport(Protocol):
    def send(self, request: PreparedHTTPRequest, timeout_seconds: int) -> HTTPResponse:
        ...


class UrllibTransport:
    def send(self, request: PreparedHTTPRequest, timeout_seconds: int) -> HTTPResponse:
        req = urllib.request.Request(
            request.url,
            data=request.body,
            headers=request.headers,
            method=request.method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                return HTTPResponse(
                    status_code=int(response.status),
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            body = exc.read()
            headers = dict(exc.headers.items()) if exc.headers else {}
            raise provider_request_error(exc.code, body, headers) from exc
        except urllib.error.URLError as exc:
            raise ProviderRequestError(str(exc.reason)) from exc


def json_request(method: str, url: str, headers: dict[str, str], payload: object) -> PreparedHTTPRequest:
    body = json.dumps(payload).encode("utf-8")
    final_headers = {"Content-Type": "application/json", **headers}
    return PreparedHTTPRequest(method=method, url=url, headers=final_headers, body=body)


def multipart_form_request(
    method: str,
    url: str,
    headers: dict[str, str],
    fields: dict[str, str],
    files: dict[str, Path],
    boundary: str | None = None,
) -> PreparedHTTPRequest:
    actual_boundary = boundary or f"pbn-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{actual_boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, path in files.items():
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{actual_boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'.encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{actual_boundary}--\r\n".encode("utf-8"))
    final_headers = {
        "Content-Type": f"multipart/form-data; boundary={actual_boundary}",
        **headers,
    }
    return PreparedHTTPRequest(method=method, url=url, headers=final_headers, body=b"".join(chunks))


def provider_request_error(
    status_code: int,
    body: bytes,
    headers: dict[str, str] | None = None,
) -> ProviderRequestError:
    message = ""
    error_type = None
    code = None
    request_id = _header_value(headers or {}, "x-request-id")
    moderation_details = None

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        message = body.decode("utf-8", errors="replace")
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            if isinstance(error.get("message"), str):
                message = error["message"]
            if isinstance(error.get("type"), str):
                error_type = error["type"]
            if isinstance(error.get("code"), str):
                code = error["code"]
            if isinstance(error.get("request_id"), str):
                request_id = error["request_id"]
            moderation_details = _safe_moderation_details(error.get("moderation_details"))
        elif isinstance(error, str):
            message = error
        if not request_id and isinstance(payload.get("request_id"), str):
            request_id = payload["request_id"]

    return ProviderRequestError(
        message or f"HTTP {status_code}",
        status_code=status_code,
        error_type=error_type,
        code=code,
        request_id=request_id,
        moderation_details=moderation_details,
        retryable=code != "moderation_blocked",
    )


def _safe_moderation_details(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None

    result: dict[str, object] = {}
    stage = value.get("moderation_stage")
    if isinstance(stage, str) and stage:
        result["moderation_stage"] = stage

    categories = value.get("categories")
    if isinstance(categories, list):
        safe_categories = [category for category in categories if isinstance(category, str) and category]
        if safe_categories:
            result["categories"] = safe_categories

    return result or None


def _header_value(headers: dict[str, str], name: str) -> str | None:
    normalized_name = name.lower()
    for key, value in headers.items():
        if key.lower() == normalized_name and value:
            return value
    return None
