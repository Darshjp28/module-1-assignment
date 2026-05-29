# Task 4 — Packet Capture & Protocol Analysis
**SmartFactory IoT Protocol Integration**

---

## 4.1 Capture Setup

```bash
bash scripts/capture.sh
# Produces:
#   captures/mqtt.pcap  (port 1883, TCP)
#   captures/coap.pcap  (port 5683, UDP)
```

Tshark commands used for annotation:

```bash
# MQTT — show all frames verbosely
tshark -r captures/mqtt.pcap -V | head -200

# Filter only CONNECT packets
tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 1" -V

# Filter QoS 1 PUBLISH + PUBACK
tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 3 && mqtt.qos == 1" -V
tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 4" -V

# CoAP — filter CON GET requests
tshark -r captures/coap.pcap -Y "coap.type == 0 && coap.code == 1" -V

# CoAP — filter Observe notifications
tshark -r captures/coap.pcap -Y "coap.opt.observe" -V
```

---

## 4.2 MQTT Packet Annotation

### Annotation 1 — CONNECT Packet

Located from: `tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 1" -V`

| Field | Raw Bytes | Decoded Value |
|---|---|---|
| **Fixed header byte** | `0x10` | Message type = 1 (CONNECT), Flags = 0000 |
| **Remaining length** | `0x2F` (example) | 47 bytes (variable, depends on Client ID length) |
| **Protocol name length** | `0x00 0x04` | 4 bytes |
| **Protocol name** | `4D 51 54 54` | `MQTT` (ASCII) |
| **Protocol version** | `0x04` | Version 4 (MQTT 3.1.1) |
| **Connect flags** | `0xC4` | See bit expansion below |
| **Connect flags — bit expansion** | | |
| · bit 7: Username flag | `1` | Username present |
| · bit 6: Password flag | `1` | Password present |
| · bit 5: Will Retain | `0` | Will message not retained (see LWT below) |
| · bit 4–3: Will QoS | `00` | Will QoS = 0 |
| · bit 2: Will flag | `1` | LWT configured |
| · bit 1: Clean Session | `0` | **Persistent session** (clean_session=False) |
| · bit 0: Reserved | `0` | Always 0 |
| **Keep-alive** | `0x00 0x3C` | 60 seconds |
| **Client ID** | variable | `smartfactory-publisher-line1` |

> **Note:** Clean Session bit = 0 confirms the persistent session requirement (Task 1.1). The broker retains session state (subscriptions, queued QoS 1/2 messages) across reconnections.

---

### Annotation 2 — QoS 1 PUBLISH Packet

Located from: `tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 3 && mqtt.qos == 1" -V`

| Field | Raw Bytes | Decoded Value |
|---|---|---|
| **Fixed header byte** | `0x32` | See bit expansion below |
| · bits 7–4: Message type | `0011` | Type = 3 (PUBLISH) |
| · bit 3: DUP flag | `0` | First delivery (not a duplicate) |
| · bits 2–1: QoS level | `01` | **QoS 1** |
| · bit 0: RETAIN flag | `0` | Not retained |
| **Remaining length** | `0x39` (example) | 57 bytes |
| **Topic length** | `0x00 0x19` | 25 bytes |
| **Topic string** | ASCII | `factory/line1/temperature` |
| **Packet Identifier** | `0x00 0x01` | PID = 1 (increments per QoS 1/2 message) |
| **Payload** | UTF-8 JSON | `{"line":"line1","sensor":"temperature","value":72.35,"unit":"°C","timestamp":"..."}` |

> **Why QoS 1 for temperature?** Temperature readings require at-least-once delivery — a missed reading could delay a critical alert. QoS 1 adds minimal overhead (one PUBACK round-trip) versus QoS 2.

---

### Annotation 3 — PUBACK Packet

Located from: `tshark -r captures/mqtt.pcap -Y "mqtt.msgtype == 4" -V`

| Field | Raw Bytes | Decoded Value |
|---|---|---|
| **Fixed header byte** | `0x40` | Message type = 4 (PUBACK), Flags = 0000 |
| **Remaining length** | `0x02` | 2 bytes |
| **Packet Identifier** | `0x00 0x01` | PID = **1** ← matches PUBLISH above ✓ |

> The matching Packet Identifier confirms the broker's acknowledgement of the specific QoS 1 message. After receiving PUBACK, the publisher removes the message from its in-flight store.

---

## 4.3 CoAP Packet Annotation

### Annotation 4 — CON GET Request

Located from: `tshark -r captures/coap.pcap -Y "coap.type == 0 && coap.code == 1" -V`

| Field | Raw Bytes | Decoded Value |
|---|---|---|
| **Fixed header — byte 0** | `0x44` | See bit expansion below |
| · bits 7–6: Version | `01` | CoAP version 1 |
| · bits 5–4: Type | `00` | **CON** (Confirmable) |
| · bits 3–0: Token Length | `0100` | TKL = 4 bytes |
| **Fixed header — byte 1: Code** | `0x01` | **0.01 GET** |
| **Fixed header — bytes 2–3: Message ID** | `0xA1 0xB2` (example) | Message ID = 41394 |
| **Token** | `DE AD BE EF` (4 bytes) | Client-generated random token |
| **Option: Uri-Path (delta encoding)** | | |
| · Option 1: delta=11, len=7 | `0xB7` + `factory` | Uri-Path = "factory" (option 11) |
| · Option 2: delta=0, len=5 | `0x05` + `line1` | Uri-Path = "line1" (same option, delta 0) |
| · Option 3: delta=0, len=11 | `0x0B` + `temperature` | Uri-Path = "temperature" |

> **Delta encoding** compresses option numbers: only the difference from the previous option's number is transmitted, saving bytes on constrained networks.

---

### Annotation 5 — ACK 2.05 Content Response

Located from: `tshark -r captures/coap.pcap -Y "coap.type == 2 && coap.code == 69" -V`

| Field | Raw Bytes | Decoded Value |
|---|---|---|
| **Fixed header — byte 0** | `0x64` | Version=1, Type=**ACK**, TKL=4 |
| **Fixed header — byte 1: Code** | `0x45` | **2.05 Content** |
| **Message ID** | `0xA1 0xB2` | Matches CON request ✓ |
| **Token** | `DE AD BE EF` | **Matches request token ✓** |
| **Option: Content-Format (11)** | `0xC1 0x32` | delta=12, value=**50** (application/json) |
| **Payload Marker** | `0xFF` | Separates options from payload |
| **Payload** | UTF-8 JSON | `{"line":"line1","sensor":"temperature","value":72.35,...}` |

> The token match between request and response is the CoAP equivalent of MQTT's Packet Identifier — it correlates async responses to their originating requests over UDP.

---

### Annotation 6 — Observe Notification

Located from: `tshark -r captures/coap.pcap -Y "coap.opt.observe" -V`

| Field | Value |
|---|---|
| **Observe option number** | **Option 6** (CoAP Observe, RFC 7641) |
| **Observe sequence value** | e.g. `0x000003` = 3 (increments each notification) |
| **Message type** | CON (server uses Confirmable for reliability) or NON |
| **Code** | 2.05 Content |

> Observe sequence values are 24-bit counters (0–16,777,215). They allow clients to detect stale notifications: if a notification arrives with a lower sequence number than the last received (accounting for wraparound per RFC 7641 §3.4), it is discarded as stale. Our observer client (`src/coap/observer.py`) implements this check explicitly.

---

*End of packet analysis — see `report/comparison_report.md` for protocol trade-off discussion.*
