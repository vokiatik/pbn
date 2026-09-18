"""Run inside the runner image on an ISOLATED test stack, never production.

Creates a tiny PNG project without making a paid AI request. Pass --existing
after a container recreation to verify database and file persistence.
Uses only the Python standard library.
"""
import base64
import hashlib
import io
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

BASE = "http://frontend:8080"
ORIGIN = "https://pbn.zichka.com"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def request(path, *, method="GET", data=None, headers=None, status=200):
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        assert response.status == status, (path, response.status, body[:200])
        return response.headers, body


def websocket(origin, expected):
    with socket.create_connection(("frontend", 8080), timeout=40) as conn:
        key = base64.b64encode(os.urandom(16)).decode()
        conn.sendall((f"GET /ws?project_id=smoke HTTP/1.1\r\nHost: pbn.zichka.com\r\n"
                      f"Origin: {origin}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(4096)
            assert chunk, "connection closed during upgrade"
            head += chunk
        assert f" {expected} ".encode() in head.split(b"\r\n")[0], head
        if expected == 101:
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            assert accept in head
            frame = head.split(b"\r\n\r\n", 1)[1]
            while len(frame) < 2:
                chunk = conn.recv(2 - len(frame))
                assert chunk, "connection closed before heartbeat"
                frame += chunk
            assert frame[:2] == b"\x89\x00", "server must send a heartbeat ping"


headers, html = request("/")
assert "no-cache" in headers["Cache-Control"]
_, deep_link = request("/projects/example")
assert deep_link == html
asset = re.search(rb'src="(/assets/[^\"]+\.js)"', html).group(1).decode()
headers, _ = request(asset)
assert "immutable" in headers["Cache-Control"]
request("/assets/missing.js", status=404)
request("/api/internal/projects/test/status", method="POST", data=b"{}", status=404)
request("/api/internal", status=404)
_, error = request("/api/projects", method="POST", data=b"x" * (27 * 1024 * 1024), status=413)
assert "26 MiB" in json.loads(error)["error"]

if "--existing" in sys.argv:
    _, data = request("/api/projects")
    public_id = next(p["public_id"] for p in json.loads(data)["items"] if p["original_filename"] == "original.png")
else:
    body = (b'--smoke\r\nContent-Disposition: form-data; name="file"; filename="production-smoke.png"\r\n'
            b'Content-Type: image/png\r\n\r\n' + PNG + b'\r\n--smoke--\r\n')
    _, data = request("/api/projects", method="POST", data=body,
                      headers={"Content-Type": "multipart/form-data; boundary=smoke", "X-Client-Token": "isolated-smoke"}, status=201)
    public_id = json.loads(data)["project_id"]

headers, data = request(f"/api/projects/{public_id}")
assert headers["Cache-Control"] == "no-store"
project = json.loads(data)
original = next(f for f in project["files"] if f["file_type"] == "original")
for action in ("preview", "download"):
    headers, content = request(f'/api/projects/{public_id}/files/{original["id"]}/{action}')
    assert content == PNG
    assert headers["Cache-Control"] == "no-store"
websocket("https://untrusted.example", 403)
websocket(ORIGIN, 101)
print("PASS: SPA, assets, upload limit, upload/download, persistence, private routes, WebSocket origin and heartbeat")

if "--preview" in sys.argv:
    from PIL import Image
    from pillow_heif import register_heif_opener

    register_heif_opener()
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (80, 150, 200)).save(buffer, format="HEIF")
    body = (b'--smoke\r\nContent-Disposition: form-data; name="file"; filename="production-preview.heic"\r\n'
            b'Content-Type: image/heic\r\n\r\n' + buffer.getvalue() + b'\r\n--smoke--\r\n')
    _, data = request("/api/projects", method="POST", data=body,
                      headers={"Content-Type": "multipart/form-data; boundary=smoke", "X-Client-Token": "isolated-smoke"}, status=201)
    preview_id = json.loads(data)["project_id"]
    for attempt in range(30):
        _, data = request(f"/api/projects/{preview_id}")
        preview = next((f for f in json.loads(data)["files"] if f["file_type"] == "upload_preview"), None)
        if preview:
            _, content = request(f'/api/projects/{preview_id}/files/{preview["id"]}/preview')
            assert content.startswith(b"\xff\xd8"), "expected generated JPEG"
            print("PASS: HEIC upload -> Redis -> worker -> runner -> registered JPEG preview")
            break
        time.sleep(1)
    else:
        raise AssertionError("HEIC preview did not finish within 30 seconds")
