# Architecture

CareMate is a stationary elderly-safety prototype with three verticals and explicit interfaces. Confirm the exact UNO Q interfaces against the board documentation before implementation.

## Vertical 1: wearable sensor node

The Glyph C6 and Modulino Movement sensor must be worn or clipped to the person. Use the local sequence `impact spike → orientation change → no-motion window` to produce a timestamped candidate-fall event over Wi-Fi. Thresholds must be configurable, and IMU evidence alone must not confirm a fall.

## Vertical 2: stationary vision hub

The UNO Q Linux side and Logitech C270 perform pose/activity inference, annotate the live feed, and evaluate wearable candidate events. Initial activity labels are on the bed, standing, sitting, lying, and walking. A horizontal pose with sustained lack of motion may contribute to fall confirmation.

The hub also supports request-scoped person/room analysis. A provider-neutral adapter may send a fresh frame or tightly bounded frame sample to a vision-capable multimodal model, including a possible OpenAI model after evaluation. The adapter validates structured output and treats text or instructions visible in an image as untrusted data.

The hub's microcontroller-facing I/O drives the buzzer, red LED, and LCD for local alerts. Keep this physical I/O separate from Linux-side vision and networking, and define explicit messages between them. The hub is stationary; motors and navigation are outside the MVP.

## Vertical 3: native iOS app and backend

Prefer a small server on the UNO Q Linux side. It receives wearable and vision events and exposes authenticated APIs for the annotated camera feed, current status, real-time fall alerts, and **Analyze space**. Build the MVP client as a native iOS app. The action requests a fresh camera analysis and returns the person's visible state and a concise room summary. The app may also provide approved test, cancel, and acknowledgement actions. Web and Android clients and general-purpose cloud infrastructure are outside scope unless explicitly requested.

When Aryan's wearable sends a candidate-fall event, the server forwards a visible **possible fall** state to the iOS app while Anshit's base station awaits vision confirmation. The UI then updates that same event to confirmed, rejected, or uncertain without representing the wearable candidate as a confirmed fall.

## On-demand analysis flow

```text
phone app → Analyze space → fresh frame → local vision + optional multimodal model
                                           ↓
                      validated person/room observation + alert recommendation
                                           ↓
                              fusion policy → app status/local alert
```

The model returns an `alert`, `check`, or `none` recommendation, but deterministic fusion policy makes the alert decision using model output, wearable evidence, local vision, and recency. A model timeout, refusal, malformed response, occlusion, or provider outage becomes `uncertain/unavailable`; it must not silently suppress credible evidence from another source.

## Team ownership

| Owner | Responsibility |
|---|---|
| Aryan | Glyph C6/Modulino wearable, fall heuristic, and candidate-event transmission |
| Anshit | UNO Q/C270 base station, image detection, OpenAI-compatible summary, fusion/backend, camera feed, alerts, and native iOS app |
| Ryaan | Hardware connection review, wiring, soldering, continuity, power safety, and bench assembly |

The wearable event schema is the handoff between Aryan and Anshit. Ryaan reviews physical interfaces before soldering or first power-up.

## Fusion flow

```text
sensor candidate → awaiting vision → confirmed fall → locally alerting
                                  ↘ rejected/uncertain
```

Correlate evidence inside a configurable time window. If one node is offline or vision is occluded, prefer an explicit `uncertain—check user` state over silently discarding credible sensor evidence. Track fall confirmation, alert delivery, and acknowledgement separately.

## Suggested message contract

Messages between components should be small and versioned. An initial event could contain:

```json
{
  "version": 1,
  "event": "candidate_fall",
  "source": "wearable",
  "uptime_ms": 123456,
  "confidence": 0.82
}
```

Do not include raw audio/video, names, addresses, phone numbers, or precise location unless the feature explicitly requires it and the user has consented.

An analysis result should use a separate versioned contract, for example:

```json
{
  "version": 1,
  "event": "space_analysis",
  "request_id": "analysis-123",
  "captured_at": "2026-07-19T10:00:00Z",
  "person_state": "on_bed",
  "room_summary": "Person visible on the bed; no immediate floor obstruction visible.",
  "risk_observations": [],
  "alert_recommendation": "none",
  "uncertain": false
}
```

Do not store raw frames by default. If analysis uses an off-device provider, require consent, transmit only the request-scoped frame data, exclude audio and continuous video, keep credentials on the server, and verify the provider's retention behavior.

## Reliability principles

- Local alerting remains available when networking fails.
- A sensor candidate is distinct from a confirmed fall, delivered alert, and acknowledgement.
- Timeouts use non-blocking timers rather than long delays.
- Every remote alert has delivery and acknowledgement status.
- Reboots and disconnected sensors become visible fault states.
- Model recommendations remain distinct from confirmed falls and alert decisions.
