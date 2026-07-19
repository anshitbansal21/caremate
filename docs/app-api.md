# CareMate app API (hub ↔ iOS app)

The contract between **Aryan's control system** (the UNO Q hub) and **Anshit's API
layer / native iOS app**. This is the single handoff; the hub side is
`hub/caremate_hub/app_server.py` (`HttpAppBus`). It runs on the UNO Q **Linux
side** — the STM32/MCU is not involved (that side only speaks the serial alert
protocol in `docs/main-controller.md`).

## Transport at a glance

The hub **publishes**, the app **subscribes**. Two traffic shapes → two mechanisms:

| Concern | Direction | Mechanism |
|---|---|---|
| Status + fall-alert push | hub → app | **SSE** (one long-lived HTTP connection) |
| Analyze space / acknowledge / cancel | app → hub | **REST POST** |
| Current status | app → hub | **REST GET** |
| Annotated camera feed | hub → app | **MJPEG** (`multipart/x-mixed-replace`) |

It is a **long-lived HTTP connection (SSE)** for real-time events — *not* a raw TCP
socket. This keeps auth headers, one server, and one port for everything, and it's
a line-stream `URLSession` reads natively on iOS. The choice lives behind the
`AppBus` abstraction, so switching to WebSocket later needs **no fusion changes** —
flag it if the app side would prefer WS.

Base URL on the demo LAN: `http://<hub-ip>:8080`. TLS is deferred for the MVP
(self-signed + iOS ATS is a rabbit hole on a trusted LAN); the bearer token is the
MVP auth. Do not put this on the open internet as-is.

## Auth

Every request needs `Authorization: Bearer <token>`. For the SSE and feed
connections (where a header may be awkward) `?token=<token>` is also accepted. The
token is configured on the hub; provider credentials (e.g. a VLM key) never leave it.
The iOS app keeps the hub URL in device preferences and the bearer token in the
device-only Keychain after a validated Connect action; disconnecting does not erase
either value.

When using an ngrok free-tier URL, every native client request must also include
`ngrok-skip-browser-warning: true` so the tunnel returns the API/stream instead
of its HTML warning page. The iOS client uses native `URLSession` for REST, SSE,
and MJPEG, so the shared request builder applies both headers to all endpoints.

Missing/wrong token → `401 {"error":"unauthorized"}`.

## Connecting the app (dev vs demo)

**Do not hardcode the hub address.** Make the **base URL + token a config field** —
the address changes constantly (dev laptop → tunnel → demo IP), and a field beats
rebuilding. A plain LAN IP (`192.168.x.x`) only works on the *same* network; to
cross networks you need a tunnel.

1. **Build the app with no Arduino and no shared network.** `run_hub` is pure
   Python, so run the hub on your own machine:
   `python -m caremate_hub.run_hub --demo` → point the app at
   `http://localhost:8080` (or your Mac's LAN IP for a physical device). You get
   real SSE events, a scripted fall, and working `/analyze` to build against.
   Do most of the app here.
2. **Reach a real hub on a different network.** Run a tunnel on the hub —
   `ngrok http 8080` (or Cloudflare Tunnel) — for an HTTPS URL that works from
   anywhere and also satisfies iOS ATS. Dev/integration only.
3. **Demo day.** Put the phone on the hub's network (hub Wi-Fi AP or a shared
   hotspot) and set the config to the hub's LAN IP, e.g. `http://192.168.x.x:8080`.

**iOS gotchas** for the plain-HTTP LAN path (localhost and the HTTPS tunnel avoid
both): add an ATS exception (`NSAllowsLocalNetworking` or an `NSExceptionDomains`
entry) or iOS blocks `http://`; and add `NSLocalNetworkUsageDescription` for the
iOS 14+ local-network permission prompt.

## Endpoints

### `GET /events` — real-time event stream (SSE)
Long-lived. Emits one JSON object per `data:` line. On connect it immediately
sends the current status. A `: ping` comment every ~15 s keeps it alive.

Event shapes:
```jsonc
// status change (incl. the "possible fall" that appears while vision is pending)
{"type":"status","state":"awaiting_vision","level":"possible","ts":123456}

// a fusion decision worth surfacing prominently
{"type":"alert","state":"alerting","level":"confirmed","detail":"vision: lying + sustained no-motion","ts":123999}

// Analyze-space result (also returned directly from POST /analyze)
{"type":"analysis","request_id":"req-ab12","person_state":"on_bed","room_summary":"...","risk_observations":[],"alert_recommendation":"none","uncertain":false,"captured_at":"","ts":124500}
```
`state` ∈ `ready | awaiting_vision | confirmed_fall | alerting | uncertain | rejected | fault`.
`level` ∈ `none | possible | check | confirmed`.

The app should render `level=possible` as **“possible fall — checking”**, then
update the *same* event to `confirmed` / `rejected` (back to `ready`) / `check`
(uncertain). Never show `possible` as a confirmed fall.

### `GET /status` — snapshot
`200 {"state":"ready","level":"none","ts":123456}` — the latest status, for app
launch / reconnect before the SSE stream warms up.

### `POST /analyze` — Analyze space
No body required. Captures a fresh frame, runs the analysis, and **returns the
result directly** (also mirrored on the SSE stream). Always returns within the
hub's timeout — a timeout/occlusion yields `uncertain:true`, never a hang.
```json
{"request_id":"req-ab12","person_state":"on_bed","room_summary":"Person resting on the bed; floor clear.","risk_observations":[],"alert_recommendation":"none","uncertain":false,"captured_at":""}
```
`person_state` ∈ `on_bed | standing | sitting | lying | walking | not_visible | uncertain`.
`alert_recommendation` ∈ `alert | check | none` — **advisory only**; the hub's
fusion policy owns the actual alert decision.

The app may pass this structured response—but never the raw frame—to Apple's
on-device Foundation Models framework on supported iOS 26 devices to produce a
concise display paragraph. The app treats every returned string as untrusted
observed data, preserves the raw fields in the UI, and uses a deterministic
fallback when the system model is unavailable. Generated prose never feeds back
into `/ack`, `/cancel`, fusion, or local alerting.

### `POST /ack` — acknowledge an active alert
`202 {"accepted":"ack"}`. Clears the local alert and (via the hub) resets the
wearable latch. Acknowledgement is recorded separately from fall confirmation.

### `POST /cancel` — cancel / test
`202 {"accepted":"cancel"}`. Safe to wire to a “test” button — this is the
cancel/test mechanism that must exist before real recipients are involved.

### `GET /feed` — annotated camera feed
`multipart/x-mixed-replace; boundary=frame` MJPEG stream. Returns
`503 {"error":"no camera feed wired"}` until the vision layer's annotated-frame
provider is connected. Show it only while capture is active (consent/visibility).

## iOS client sketch

- One `URLSessionDataTask` to `/events`, parse `data:` lines → drive UI state.
- `URLSession` POST to `/analyze` for the button; render the returned JSON.
- Optionally summarize that JSON on-device for presentation; keep the raw hub
  observation and recommendation visible and authoritative.
- POST `/ack` and `/cancel` for the alert and test buttons.
- `AsyncImage`/`URLSession` MJPEG reader (or an `<img>`-style view) for `/feed`.

## Not yet wired (hub side)

- `/feed` needs the annotated-JPEG provider from `PoseVisionSource` (follow-up).
- TLS + hub-side per-user token management remain unwired (the MVP hub uses one
  shared bearer token on the LAN; the iOS client stores that token in Keychain).
