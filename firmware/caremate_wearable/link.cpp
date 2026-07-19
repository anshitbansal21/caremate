/*
 * CareMate wearable — hub link implementation.
 * See link.h and README.md for the transport contract.
 */

#include "link.h"

#include <string.h>

void HubLink::begin(const LinkConfig& cfg,
                    const char* ssid, const char* password,
                    const char* host, uint16_t port,
                    ResetHandler on_reset) {
  cfg_ = cfg;
  ssid_ = ssid;
  password_ = password;
  host_ = host;
  port_ = port;
  on_reset_ = on_reset;

  backoff_ms_ = cfg_.reconnect_min_ms;
  next_reconnect_ms_ = 0;
  in_len_ = 0;

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid_, password_);
}

void HubLink::loop(uint32_t now_ms) {
  manageConnection(now_ms);

  if (!connected_) return;

  readInbound();
  flushOutbox(now_ms);
  sendHeartbeat(now_ms);
}

void HubLink::manageConnection(uint32_t now_ms) {
  // Detect a dropped TCP connection.
  if (connected_ && !client_.connected()) {
    client_.stop();
    connected_ = false;
    Serial.println(F("[link] hub disconnected"));
    next_reconnect_ms_ = now_ms + backoff_ms_;
  }

  if (connected_) return;

  // Wait for Wi-Fi association first (non-blocking; the core retries STA).
  // Log the up/down transition so association is observable even before the
  // hub is listening (the TLM "link" column only reflects the TCP layer).
  const bool wifi_now = (WiFi.status() == WL_CONNECTED);
  if (wifi_now && !wifi_up_) {
    wifi_up_ = true;
    Serial.print(F("[link] WiFi connected, IP="));
    Serial.println(WiFi.localIP());
  } else if (!wifi_now && wifi_up_) {
    wifi_up_ = false;
    Serial.println(F("[link] WiFi lost"));
  }
  if (!wifi_now) return;

  if (now_ms < next_reconnect_ms_) return;  // honor backoff

  // Single non-blocking-ish connect attempt (bounded by connect_timeout_ms
  // inside the core). On failure, grow the backoff and try again later.
  if (client_.connect(host_, port_)) {
    connected_ = true;
    backoff_ms_ = cfg_.reconnect_min_ms;  // reset backoff on success
    onConnected(now_ms);
  } else {
    backoff_ms_ *= 2;
    if (backoff_ms_ > cfg_.reconnect_max_ms) backoff_ms_ = cfg_.reconnect_max_ms;
    next_reconnect_ms_ = now_ms + backoff_ms_;
  }
}

void HubLink::onConnected(uint32_t now_ms) {
  client_.setNoDelay(true);  // low latency: don't Nagle-buffer tiny events
  in_len_ = 0;
  Serial.println(F("[link] TCP connected to hub"));

  // Announce a fresh boot/connection so the hub can reset any stale wearable
  // state (an uptime reset means we rebooted).
  char line[128];
  snprintf(line, sizeof(line),
           "{\"version\":1,\"event\":\"boot\",\"source\":\"wearable\","
           "\"seq\":%lu,\"uptime_ms\":%lu}",
           (unsigned long)++seq_, (unsigned long)now_ms);
  writeLine(line);
  last_heartbeat_ms_ = now_ms;

  // Re-send any candidates buffered while we were offline.
  flushOutbox(now_ms);
}

void HubLink::sendHeartbeat(uint32_t now_ms) {
  if (now_ms - last_heartbeat_ms_ < cfg_.heartbeat_ms) return;
  last_heartbeat_ms_ = now_ms;

  char line[128];
  snprintf(line, sizeof(line),
           "{\"version\":1,\"event\":\"heartbeat\",\"source\":\"wearable\","
           "\"seq\":%lu,\"uptime_ms\":%lu}",
           (unsigned long)++seq_, (unsigned long)now_ms);
  writeLine(line);  // fire-and-forget: heartbeats are not acked
}

void HubLink::sendCandidate(uint32_t uptime_ms, float confidence) {
  uint32_t seq = ++seq_;
  char json[160];
  // Matches CandidateFall in hub/caremate_hub/events.py. received_at_ms is
  // stamped by the hub on receipt, so it is intentionally not sent here.
  snprintf(json, sizeof(json),
           "{\"version\":1,\"event\":\"candidate_fall\",\"source\":\"wearable\","
           "\"seq\":%lu,\"uptime_ms\":%lu,\"confidence\":%.2f}",
           (unsigned long)seq, (unsigned long)uptime_ms, confidence);

  int slot = enqueue(seq, json);
  if (slot < 0) return;  // outbox full; oldest already dropped in enqueue()

  // Best-effort immediate send; retransmit loop covers the rest.
  if (connected_ && writeLine(json)) {
    outbox_[slot].last_send_ms = millis();
  }
}

int HubLink::enqueue(uint32_t seq, const char* json) {
  for (int i = 0; i < LinkConfig::outbox_capacity; ++i) {
    if (!outbox_[i].used) {
      outbox_[i].used = true;
      outbox_[i].seq = seq;
      strncpy(outbox_[i].json, json, sizeof(outbox_[i].json) - 1);
      outbox_[i].json[sizeof(outbox_[i].json) - 1] = '\0';
      outbox_[i].last_send_ms = 0;
      return i;
    }
  }
  // Full: drop the oldest (lowest seq) so a fresh candidate is never lost.
  int oldest = 0;
  for (int i = 1; i < LinkConfig::outbox_capacity; ++i) {
    if (outbox_[i].seq < outbox_[oldest].seq) oldest = i;
  }
  outbox_[oldest].seq = seq;
  strncpy(outbox_[oldest].json, json, sizeof(outbox_[oldest].json) - 1);
  outbox_[oldest].json[sizeof(outbox_[oldest].json) - 1] = '\0';
  outbox_[oldest].last_send_ms = 0;
  return oldest;
}

void HubLink::flushOutbox(uint32_t now_ms) {
  if (!connected_) return;
  for (int i = 0; i < LinkConfig::outbox_capacity; ++i) {
    if (!outbox_[i].used) continue;
    if (outbox_[i].last_send_ms != 0 &&
        now_ms - outbox_[i].last_send_ms < cfg_.candidate_retransmit_ms) {
      continue;  // waiting on an ack for this one
    }
    if (writeLine(outbox_[i].json)) {
      outbox_[i].last_send_ms = now_ms;
    }
  }
}

bool HubLink::writeLine(const char* line) {
  if (!connected_) return false;
  size_t n = strlen(line);
  if (client_.write((const uint8_t*)line, n) != n) return false;
  return client_.write((const uint8_t*)"\n", 1) == 1;
}

void HubLink::readInbound() {
  while (client_.available() > 0) {
    int c = client_.read();
    if (c < 0) break;
    if (c == '\n') {
      in_buf_[in_len_] = '\0';
      if (in_len_ > 0) handleLine(in_buf_);
      in_len_ = 0;
    } else if (in_len_ < (int)sizeof(in_buf_) - 1) {
      in_buf_[in_len_++] = (char)c;
    } else {
      in_len_ = 0;  // overflow -> drop the malformed line
    }
  }
}

void HubLink::handleLine(const char* line) {
  // Minimal, dependency-free parsing of the hub's small fixed-shape messages:
  //   {"version":1,"event":"ack","seq":N}
  //   {"version":1,"event":"reset"}
  if (strstr(line, "\"event\":\"ack\"") != nullptr) {
    const char* p = strstr(line, "\"seq\":");
    if (p != nullptr) ackSeq((uint32_t)strtoul(p + 6, nullptr, 10));
    return;
  }
  if (strstr(line, "\"event\":\"reset\"") != nullptr) {
    if (on_reset_ != nullptr) on_reset_();
  }
}

void HubLink::ackSeq(uint32_t seq) {
  for (int i = 0; i < LinkConfig::outbox_capacity; ++i) {
    if (outbox_[i].used && outbox_[i].seq == seq) {
      outbox_[i].used = false;  // delivered + acknowledged; stop retransmitting
      return;
    }
  }
}
