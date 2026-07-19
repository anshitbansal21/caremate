"""serial_hub_bridge — relay ESP32 candidate events from USB serial to the hub.

    ESP32 (SERIAL_BRIDGE firmware) --USB serial--> [this, on the Mac] --TCP--> UNO Q hub :9000

The wearable can't reach the UNO Q hub over Wi-Fi, so the Mac bridges the gap:
read the ESP32's newline-delimited JSON over USB and forward every line that
starts with '{' verbatim to the hub's WearableServer TCP port. The bytes are
identical to the Wi-Fi path, so the hub's WearableServer can't tell the difference.

    python -m caremate_hub.serial_hub_bridge --serial /dev/cu.usbmodem1101 --hub 192.168.0.193:9000

Auto-reconnects both the serial side and the TCP side; pure stdlib + pyserial.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


def _connect_tcp(host: str, port: int):
    while True:
        try:
            s = socket.create_connection((host, port), timeout=4)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[bridge] connected to hub {host}:{port}")
            return s
        except OSError as exc:
            print(f"[bridge] hub {host}:{port} unreachable ({exc}); retrying in 2s")
            time.sleep(2)


def main() -> None:
    p = argparse.ArgumentParser(description="ESP32 USB-serial -> hub TCP relay")
    p.add_argument("--serial", required=True, help="ESP32 USB serial device")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--hub", required=True, help="hub host:port, e.g. 192.168.0.193:9000")
    args = p.parse_args()

    host, _, port_s = args.hub.partition(":")
    port = int(port_s or 9000)

    import serial  # pyserial

    ser = serial.Serial()
    ser.port = args.serial
    ser.baudrate = args.baud
    ser.timeout = 0.5
    ser.dtr = False  # don't reset the ESP32 on open
    ser.rts = False
    ser.open()
    print(f"[bridge] reading ESP32 on {args.serial} @ {args.baud}")

    sock = _connect_tcp(host, port)
    buf = b""
    fwd = 0
    while True:
        try:
            chunk = ser.read(256)
        except OSError as exc:
            print(f"[bridge] serial error ({exc}); retrying")
            time.sleep(0.5)
            continue
        if not chunk:
            continue
        buf += chunk
        while b"\n" in buf:
            raw, _, buf = buf.partition(b"\n")
            line = raw.strip()
            if not line.startswith(b"{"):
                continue  # skip boot logs / noise, forward only contract JSON
            try:
                sock.sendall(line + b"\n")
                fwd += 1
                kind = b"candidate_fall" in line and "CANDIDATE" or "hb/boot"
                if kind == "CANDIDATE" or fwd % 10 == 0:
                    print(f"[bridge] -> hub ({fwd} lines) {line.decode(errors='replace')[:80]}")
            except OSError as exc:
                print(f"[bridge] hub link dropped ({exc}); reconnecting")
                try:
                    sock.close()
                except OSError:
                    pass
                sock = _connect_tcp(host, port)
                try:
                    sock.sendall(line + b"\n")  # resend the line that failed
                except OSError:
                    pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
        sys.exit(0)
