# Production: pbn.zichka.com on Coolify + Cloudflare Tunnel

This deployment uses your existing working tunnel and fresh Compose volumes.
The website stays public, with the existing project/file access behavior.
No Cloudflare token belongs in this app's environment or frontend build.

```text
Browser: https://pbn.zichka.com
  -> Cloudflare edge -> encrypted Tunnel -> existing cloudflared connector
  -> Coolify proxy -> frontend:8080
  -> /api/* and /ws -> backend:8080
  -> PostgreSQL / Redis -> worker -> pbn:8081
```

## 1. Create the Coolify application

Add this Git repository as a Docker Compose application. Set Base Directory to
`/` and Compose Location to `/docker-compose.production.yml`. Load the file.
Use this file alone: merging the development Compose file publishes database
and runner ports. Keep **Raw Compose Deployment** and **Connect To Predefined
Network** disabled. Coolify's proxy joins the app network automatically.
See [Coolify Compose](https://coolify.io/docs/applications/build-packs/docker-compose)
and [networking](https://coolify.io/docs/core/networking-in-coolify).

Copy the variables from `deploy/.env.example` into Coolify's **runtime**
environment variables. Generate three different secrets, each with
`openssl rand -hex 32`, for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and
`INTERNAL_API_SECRET`. Use hexadecimal database passwords because the value is
embedded in the PostgreSQL connection URI. Configure both the key and image
model for at least one AI provider. Leave `APP_ORIGIN=https://pbn.zichka.com`.
Do not mark credentials as build variables; disable automatic build-argument
injection. The images need no secret build arguments or hostname rebuilds.

Assign a domain **only to frontend**:

```text
https://pbn.zichka.com:8080
```

The `8080` selects the container port; visitors use normal HTTPS without a port.
For the HTTP tunnel route below, disable **Redirect HTTP to HTTPS** in Coolify
for this domain. Cloudflare handles visitor redirects. Older Coolify versions
without that control can use `http://pbn.zichka.com:8080` as the proxy domain;
the public website and `APP_ORIGIN` still use HTTPS. No other service gets a
domain or host port. See [Coolify domain ports](https://coolify.io/docs/core/networking/domains).

## 2. Add the route to your existing tunnel

In Cloudflare, select your working tunnel, then add a **Published application**
route with subdomain `pbn`, domain `zichka.com`, and no path restriction.
Point it at the Coolify proxy, using the address reachable by your connector:

| Where cloudflared runs | Service URL |
| --- | --- |
| On the Coolify host, or in a container using host networking | `http://localhost:80` |
| In a container sharing a Docker network with `coolify-proxy` | `http://coolify-proxy:80` |

`localhost` inside an ordinary bridge-network container refers to that
container, not the host. Reuse the proxy destination that worked in your tunnel
test. Set **HTTP Host Header** to `pbn.zichka.com` so the proxy selects this app.
The PBN stack itself does not need to join the connector's network.

Verify the route creates a proxied `pbn` CNAME to your tunnel's
`<UUID>.cfargotunnel.com` target. Resolve any pre-existing conflicting `pbn`
record. Keep other routes and the tunnel token unchanged. This follows
[Coolify's proxy/tunnel guide](https://coolify.io/docs/integrations/networking/cloudflare/tunnels/all-resource)
and [Cloudflare's route setup](https://developers.cloudflare.com/tunnel/get-started/).

For a tunnel-only server, block unsolicited Internet ingress to the proxy's
80/443 ports at the host/provider firewall, while retaining the connector's
local access and your verified administration route. This prevents bypassing
Cloudflare's controls through the server IP. The tunnel needs outbound
connectivity; do not close SSH/admin access without a working alternative.

The HTTP hop is local to the server. If the connector and proxy communicate
across an untrusted network, use HTTPS to the proxy instead: install a valid
certificate, set the Coolify domain to HTTPS, select an HTTPS tunnel Service
URL, and set **Origin Server Name** to `pbn.zichka.com`. Keep certificate
verification enabled; configure a trusted CA pool if needed. DNS-based ACME
validation works without opening inbound ports. See
[origin TLS settings](https://developers.cloudflare.com/tunnel/reference/origin-parameters/),
[HTTPS troubleshooting](https://developers.cloudflare.com/tunnel/troubleshooting/https-origins/),
and [Coolify DNS challenge](https://coolify.io/docs/core/networking/proxy/traefik/dns-challenge).
Full (strict) is appropriate for HTTPS origins; it does not convert an HTTP
tunnel Service URL into HTTPS. Do not switch to Flexible to fix a redirect loop.

## 3. Cloudflare settings

- Enforce HTTPS for `pbn.zichka.com`. Use a hostname-scoped Redirect Rule, or
  **Always Use HTTPS** if every hostname in your zone is ready for HTTPS.
  Keep TLS 1.3 enabled and use minimum TLS 1.2. Add HSTS only after HTTPS works
  reliably; do not apply `includeSubDomains` or preload to unrelated sites.
- Keep WebSockets enabled. The backend sends ping frames every 30 seconds;
  the frontend reconnects with backoff and reloads saved project state.
- Create a **Bypass cache** rule for:

  ```text
  (http.host eq "pbn.zichka.com" and
   (starts_with(http.request.uri.path, "/api/") or http.request.uri.path eq "/ws"))
  ```

  Ensure a later rule cannot override that bypass. Do not apply Cache Everything
  to this hostname. The app serves API/download responses with `no-store`, HTML
  with `no-cache`, and versioned `/assets/` files with one-year immutable caching.
- Enable the managed WAF rules available on your plan. Configure rate limiting
  for POST/PUT/DELETE under `/api/`, especially uploads and `/run`. Choose limits
  from expected traffic and tune from events; challenges on API fetches and
  WebSocket upgrades can break the UI. Set provider spend alerts/limits as well.
- Do not enable Cloudflare Access on this public hostname. Protect the separate
  Coolify administration hostname according to your existing admin setup.

References: [HTTPS redirects](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/),
[WebSockets](https://developers.cloudflare.com/network/websockets/),
[cache rules](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/),
[rate limiting](https://developers.cloudflare.com/waf/rate-limiting-rules/).

## 4. Deploy and verify

Deploy and wait for all six services to become healthy. The production stack
has no host port mappings, authenticated PostgreSQL/Redis, persistent volumes,
rotated logs, and non-root application containers with read-only root filesystems.
The worker mounts project storage read-only; backend and runner share UID 10001
and write access. Fresh volume ownership is prepared by the images.

Check these before considering the domain live:

1. `https://pbn.zichka.com/` loads; reloading a project page works.
2. Browser API requests use this hostname, and `/ws` upgrades with status 101
   using `wss://pbn.zichka.com/ws`. No requests target localhost.
3. Upload a PNG/JPEG and HEIC sample, run one AI generation, review it, generate
   difficulty options, select one, and download both PDFs. This incurs the
   configured provider charge. Test a brief browser disconnect during a job.
4. API/file responses have `Cache-Control: no-store` and never a Cloudflare HIT.
   `/api/internal/anything` returns 404 from the public entry point.
5. Redeploy with no active jobs and confirm a saved project and its downloads
   survive. Check certificate/redirect behavior and external monitoring.

Nginx limits total upload requests to **26 MiB**, including multipart overhead;
larger requests receive 413. This is below Cloudflare's standard upload limits.
AI processing remains asynchronous and private between worker and runner, so
long jobs do not hold a Cloudflare HTTP request open. Do not route the runner
through the public hostname. [Cloudflare upload limits](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/)
and [connection limits](https://developers.cloudflare.com/fundamentals/reference/connection-limits/).

## Operations and data

Start with `WORKER_CONCURRENCY=1` and `PBN_NUM_THREADS=1`. CPU/RAM determine
throughput and whether image processing fits in memory, not whether Compose
can parse the file. Measure peak memory on large real inputs before raising
concurrency or setting container memory limits; allow capacity for image builds,
PostgreSQL, Redis, and Coolify. This is a single-server deployment, not HA.

Schedule encrypted off-server backups of both the **PostgreSQL database** and
**storage_data**. Use `pg_dump -Fc -U pbn -d pbn` inside the database container;
do not treat a copy of live PostgreSQL data files as a consistent database dump.
Drain jobs and temporarily prevent uploads/mutations while taking a matched
database dump and project-storage backup. Back up Redis's persistent volume
while stopped if preserving queued work is required. Verify the actual
resource-prefixed volume names in Coolify, set retention, enable failure alerts,
and restore a backup into a separate resource before launch.

Use Coolify's available database/storage backup controls, or an external backup
job when this Compose component has no backup control. A Coolify instance
backup alone does not contain app volumes. On restore, restore the database
and project files together and preserve `/storage/projects/{public_id}` paths
and UID/GID 10001 ownership. Never reset volumes as part of a routine deploy.
See [Coolify backups](https://coolify.io/docs/databases/backups),
[storage backups](https://coolify.io/docs/core/persistent-storage/storage-mounts/overview),
and [instance restore scope](https://coolify.io/docs/core/backup-and-recovery/instance-restore).

Monitor service health, tunnel availability, disk space, failed jobs, and AI
spend. HTTP health checks are liveness probes, not full pipeline tests; worker
health checks supervise live threads and Redis, not individual job progress.
Docker marks unhealthy services but restart policies only restart exited
processes. Keep an external HTTP monitor and Coolify failure notifications.

For maintenance, stop admitting new work, let the queue and active jobs drain,
then deploy. SIGTERM now lets the worker finish a popped job, with a 65-minute
container grace period. The queue still uses destructive BLPOP: a forced kill,
OOM, or power loss after a job is popped can leave its project stuck. A durable
acknowledgment/recovery queue is future application work, not supplied by Redis
AOF. Do not promise zero-downtime job recovery or scale replicas for this MVP.

The public access model is unchanged: projects/downloads are public, browser
tokens control generation/replacement, and existing delete/user-attachment
endpoints are not account-authenticated. CORS is not authentication. This
deployment adds no login, per-account privacy, or billing enforcement.

Preserve known-good images for rollback. Migrations run when the backend starts;
rolling back an image does not roll back the database. Validate schema
compatibility or restore a matched backup in a separate resource first. Refresh
base-image patches and audit dependencies regularly; record image digests for
each released build. Existing dependency locks remain unchanged.

## Local deployment verification

Run `npm run test:websocket` in `frontend/`, `go test ./...` in `backend/`,
and the focused worker tests in `worker/tests/` for reconnection, origin checks,
and graceful-shutdown regressions.

Use a separate Compose project and **test-only** environment file. Never run
the smoke script on production: it creates a project and sends an oversized
test request. It uses no AI credentials or paid provider requests.

```sh
docker compose --env-file deploy/.env.test -p pbn-production-check -f docker-compose.production.yml config --quiet
docker compose --env-file deploy/.env.test -p pbn-production-check -f docker-compose.production.yml build
docker compose --env-file deploy/.env.test -p pbn-production-check -f docker-compose.production.yml up -d --wait
docker run --rm --network pbn-production-check_default -v "$PWD/deploy:/checks:ro" pbn-production-check-pbn python /checks/smoke_test.py
```

The test verifies routing, uploads/downloads, cache headers, request-size limits,
private-route blocking, WebSocket origin checks, and the server heartbeat.
After recreating the test containers while keeping their volumes, run it again
with `--existing` to check persistence. Remove only the disposable test stack
and its volumes when finished.

Pass `--preview` to additionally create a synthetic HEIC upload and verify
Redis -> worker -> runner -> stored JPEG preview registration. This optional
check uses Pillow/pillow-heif already installed in the runner image.
