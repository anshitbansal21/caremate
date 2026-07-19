# Mac relay — wiring the ESP32 to the UNO Q hub over USB

For the demo the ESP32 wearable can't reach the UNO Q hub reliably over Wi-Fi, so
the Mac acts as a **dumb wired relay** between them. The Mac is **not** the hub —
the **UNO Q is the hub** (camera + YOLOv8-pose vision + fusion + API). The Mac only
forwards the wearable's events.

```
  ESP32-C6 wearable ──USB serial──▶  Mac  ──TCP :9000──▶  UNO Q hub
   (SERIAL_BRIDGE firmware,          (serial_hub_bridge)   (run_hub: camera,
    emits candidate JSON)                                   vision, fusion, API)
                                                                   │
                                          iOS app / mock client ◀──┘  :8080 (SSE + REST)
```

The wearable firmware's `SERIAL_BRIDGE` mode already emits byte-identical contract
JSON (`boot` / `heartbeat` / `candidate_fall`) over USB. The relay forwards every
`{`-line verbatim to the hub's `WearableServer`, which can't tell it from Wi-Fi.

## Run the relay (on the Mac)

```bash
cd hub
python -m caremate_hub.serial_hub_bridge \
    --serial /dev/cu.usbmodem1101 \
    --hub <UNO-Q-ip>:9000
```

`--serial` is the ESP32 (Espressif VID `0x303a`; find it with `arduino-cli board
list`). `--hub` is the UNO Q's IP on the shared Wi-Fi, port 9000. The relay
auto-reconnects both the serial and TCP sides. Needs `pyserial`.

## Verified (with real hardware)

- ESP32 streams `boot`/`heartbeat`/`candidate_fall` JSON over `/dev/cu.usbmodem1101`.
- The relay forwards them; a `WearableServer` logs `wearable connected` + `wearable
  boot`, and `/analyze` reports `wearable_online: true`, `method: "wearable IMU
  online…"`. The full ESP32 → Mac → hub path is proven end to end.

## The one remaining gap

The hub must be **running on the UNO Q** for `--hub <UNO-Q-ip>:9000` to land. As of
this writing no UNO Q on the network has `:9000`/`:8080` open — i.e. `run_hub` is
not yet deployed/running on the board. **Owner: integration agent** (needs UNO Q
shell access, which the relay/hub Python side does not have).

Deploy step on the UNO Q Linux side:
```bash
# on the UNO Q, in the repo:
python3 -m caremate_hub.run_hub --camera        # camera + vision + fusion + API
```
Then point the Mac relay at that board's IP. (For local dev without the board, run
`run_hub` on the Mac and use `--hub 127.0.0.1:9000`.)

## What Anshit does

Point the iOS app's configurable base URL at the hub:
- **UNO Q hub on the Wi-Fi:** `http://<UNO-Q-ip>:8080`, token `caremate-dev`.
- **Local dev (no board):** run `python -m caremate_hub.run_hub --demo` on his Mac,
  point at `http://localhost:8080`.
- **Remote:** tunnel the hub with `ngrok http 8080`.

Full endpoint/event contract: `docs/app-api.md`.
