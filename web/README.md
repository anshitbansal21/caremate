# CareMate web console (demo fallback client)

A browser-based fallback that mirrors the native iOS app's functionality against
the **same hub API** (`docs/app-api.md`): live status + real-time fall alerts,
**Analyze space**, acknowledge, cancel/test, and the live annotated feed. Use it
when the iOS app isn't available for the demo. Explicitly requested as a fallback
(otherwise CLAUDE.md defers web clients).

Stdlib-only (no dependencies). Two files:

| File | Role |
|---|---|
| `index.html` | The UI — SSE-driven status hero, feed, action buttons, analysis panel, event log |
| `proxy.py` | Local static server + reverse proxy to the hub |

## Why a proxy (not a plain page)

The hub sends CORS headers only on `/frame`, so a browser page loaded from a
different origin would be blocked on `/events` (SSE), `/analyze`, `/ack`, and
`/cancel`. `proxy.py` serves the page and forwards `/api/*` to the hub from the
**same origin**, so everything works — and it injects the bearer token
server-side, so the token never sits in browser JS. It also relays SSE and the
MJPEG feed unbuffered. It touches no hub code.

## Run

On a laptop **on the same hotspot as the hub**:

```bash
python3 web/proxy.py
# then open http://localhost:8090
```

Configure via env vars (defaults shown):

```bash
HUB_HOST=172.20.10.2 HUB_PORT=8080 CAREMATE_TOKEN=caremate-dev PORT=8090 \
  python3 web/proxy.py
```

- `HUB_HOST` / `HUB_PORT` — the UNO Q hub's `HttpAppBus` address. Find the hub's
  hotspot IP with `arduino-cli board list` if it changed.
- `CAREMATE_TOKEN` — must match the hub's token (`HttpAppBus(token=...)`, default
  `caremate-dev`).

## What works

- **Status + fall alerts** — live via SSE; the hero banner reflects
  `ready / possible fall / FALL DETECTED / check on user`, and beeps on a
  confirmed alert.
- **Analyze space** — POSTs and renders person state + room summary + risks +
  recommendation.
- **Acknowledge / Cancel-Test** — the alert-clear and safe test buttons.
- **Live feed** — tries the MJPEG `/feed`, falls back to polling `/frame`; shows
  a placeholder until the hub's annotated-frame provider is wired (`/feed` and
  `/frame` return 503 until then).

If the hub is unreachable the page shows "disconnected — retrying" and reconnects
automatically once the hub is up.

## Verified

Exercised end-to-end against the real `HttpAppBus` run locally: static page,
`/status`, `/analyze` (full controller + vision round-trip), `/ack`, and the SSE
stream all pass through the proxy correctly. For the live demo, just point
`HUB_HOST` at the UNO Q once its app server is up — no code change.
