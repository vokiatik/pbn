# API Documentation

Base URL:
- Backend HTTP API: http://localhost:8080
- WebSocket: ws://localhost:8080/ws

## Projects

### POST /api/projects
Upload an original image and enqueue processing.

Content type:
- multipart/form-data

Fields:
- file: PNG or JPEG file

Headers:
- X-Client-Token: Optional client identifier used for active-project limit checks. Frontend stores this in localStorage.

Responses:
- 202 Accepted
```
{
  "project_id": "public-project-id",
  "status": "queued"
}
```
- 400 Bad Request for invalid file extension/MIME
- 429 Too Many Requests when active-project limit is reached
- 503 Service Unavailable when queue is full

### GET /api/projects?page=1&page_size=10
Paginated project list.

Response:
```
{
  "items": [...],
  "total": 31,
  "page": 1,
  "page_size": 10,
  "total_pages": 4
}
```

### GET /api/projects/{public_id}
Project details + generated files.

Response:
```
{
  "project": {...},
  "files": [...]
}
```

### DELETE /api/projects/{public_id}
Soft-delete a project.

Response:
```
{ "status": "deleted" }
```

## Files

### GET /api/projects/{public_id}/files/{file_id}/preview
Returns file with inline disposition.

### GET /api/projects/{public_id}/files/{file_id}/download
Returns file with attachment disposition.

## Users

### POST /api/users/resolve
Resolve by email.

Request:
```
{ "email": "user@example.com" }
```

Response when found:
```
{ "exists": true, "user": {...} }
```

Response when not found:
```
{ "exists": false, "requires_more_data": true }
```

### POST /api/users
Create user.

Request:
```
{
  "email": "user@example.com",
  "username": "alice",
  "phone_number": "+1000000000"
}
```

### POST /api/projects/{public_id}/attach-user
Attach user to project.

Request:
```
{ "user_id": "uuid" }
```

## Internal Worker Endpoints

These endpoints are called by the Python worker and require header:
- X-Internal-Secret: must match INTERNAL_API_SECRET

### POST /api/internal/projects/{id}/status
Request:
```
{
  "status": "processing",
  "progress": 45,
  "message": "[4/8] Palette clustering + initial assignment"
}
```

### POST /api/internal/projects/{id}/files
Request:
```
{
  "files": [
    {
      "file_type": "pbn_numbered",
      "filename": "pbn_numbered.png",
      "file_path": "/storage/projects/.../generated/pbn_numbered.png",
      "mime_type": "image/png",
      "size_bytes": 12345
    }
  ]
}
```

## WebSocket

### GET /ws?project_id={public_id}
Subscribe to one project, or omit project_id for all events.

Example events:
```
{
  "type": "status_changed",
  "project_id": "...",
  "status": "processing"
}
```

```
{
  "type": "progress",
  "project_id": "...",
  "status": "processing",
  "value": 65,
  "message": "[5/8] Importance map + safe region merging"
}
```

```
{
  "type": "completed",
  "project_id": "...",
  "files": []
}
```
