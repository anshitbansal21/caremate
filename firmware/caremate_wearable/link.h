/*
 * CareMate wearable — hub link (persistent TCP socket to the UNO Q).
 *
 * Transport chosen for an always-connected, low-latency wearable on a private
 * hotspot (see firmware/caremate_wearable/README.md for the full contract):
 *   - one long-lived TCP connection, newline-delimited JSON, both directions
 *   - candidate_fall is acked by the hub; retransmitted until acked
 *   - periodic heartbeat for hub-side liveness / fault detection
 *   - the hub->wearable "reset" (caregiver acknowledged) arrives on this socket
 *   - non-blocking throughout: no delay(), no unbounded network waits
 *
 * No TLS: the network is a closed, trusted hotspot. HTTPS belongs on the
 * hub<->phone link, not here.
 */

#ifndef CAREMATE_WEARABLE_LINK_H
#define CAREMATE_WEARABLE_LINK_H

#include <Arduino.h>
#include <WiFi.h>

#include "config.h"

typedef void (*ResetHandler)();

class HubLink {
 public:
  void begin(const LinkConfig& cfg,
             const char* ssid, const char* password,
             const char* host, uint16_t port,
             ResetHandler on_reset);

  // Drive Wi-Fi/TCP state, heartbeats, retransmits, and inbound parsing.
  // Call every loop() iteration with a monotonic millisecond clock.
  void loop(uint32_t now_ms);

  // Queue a candidate_fall (bounded outbox; flushed/retransmitted until acked).
  void sendCandidate(uint32_t uptime_ms, float confidence);

  bool connected() const { return connected_; }

 private:
  struct Pending {
    bool used = false;
    uint32_t seq = 0;
    char json[160];
    uint32_t last_send_ms = 0;
  };

  LinkConfig cfg_;
  const char* ssid_ = nullptr;
  const char* password_ = nullptr;
  const char* host_ = nullptr;
  uint16_t port_ = 0;
  ResetHandler on_reset_ = nullptr;

  WiFiClient client_;
  bool connected_ = false;
  bool wifi_up_ = false;
  uint32_t next_reconnect_ms_ = 0;
  uint32_t backoff_ms_ = 0;
  uint32_t last_heartbeat_ms_ = 0;
  uint32_t seq_ = 0;

  Pending outbox_[LinkConfig::outbox_capacity];

  // Inbound line assembly.
  char in_buf_[192];
  int in_len_ = 0;

  void manageConnection(uint32_t now_ms);
  void onConnected(uint32_t now_ms);
  void sendHeartbeat(uint32_t now_ms);
  void flushOutbox(uint32_t now_ms);
  bool writeLine(const char* line);
  void readInbound();
  void handleLine(const char* line);
  void ackSeq(uint32_t seq);
  int enqueue(uint32_t seq, const char* json);
};

#endif  // CAREMATE_WEARABLE_LINK_H
