# Proposed architecture

CareMate should be split into small components with explicit responsibilities. The exact UNO Q interfaces must be confirmed against the board documentation before implementation.

## Layers

### Real-time controller

Responsible for buttons, encoder, movement input, LEDs, buzzer, LCD, watchdogs, and the safety state machine. It should continue to provide local feedback if networking or AI is unavailable.

### AI and perception

Responsible for webcam/microphone processing and higher-level activity interpretation. Prefer on-device processing and transmit the minimum information needed. This layer must not silently override physical privacy controls.

### Connectivity

Responsible for authenticated alerts, delivery status, retry/backoff, and acknowledgements. Credentials belong in local secret storage, never in source control.

### Mobility (future)

Responsible for motor control, obstacle sensing, following behavior, speed limits, and an emergency stop. Mobility faults must not disable manual-help controls or alerts.

## Suggested message contract

Messages between components should be small and versioned. An initial event could contain:

```json
{
  "version": 1,
  "event": "possible_fall",
  "source": "movement_sensor",
  "uptime_ms": 123456,
  "confidence": 0.82
}
```

Do not include raw audio/video, names, addresses, phone numbers, or precise location unless the feature explicitly requires it and the user has consented.

## Reliability principles

- Local controls remain available when AI/networking fails.
- A possible fall is distinct from a confirmed/delivered alert.
- Timeouts use non-blocking timers rather than long delays.
- Every remote alert has delivery and acknowledgement status.
- Reboots and disconnected sensors become visible fault states.
