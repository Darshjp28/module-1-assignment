# Task 5 — Protocol Comparison Report
**SmartFactory IoT Protocol Integration**
*Real-Time Data Analytics for IoT — Graduate Course*

---

## 5.1 QoS Comparison Results Table

Measured over a 60-second window with 10% simulated packet loss (`tc netem loss 10%` on the loopback interface). Publisher interval: 0.5 s per QoS level → ~120 messages sent per level.

| Protocol / QoS | Sent | Received | Lost (%) | Duplicates | Latency (ms) |
|---|---|---|---|---|---|
| MQTT QoS 0 | 120 | 108 | 10.0% | 0 | 1.2 |
| MQTT QoS 1 | 120 | 120 | 0.0% | 3 | 4.7 |
| MQTT QoS 2 | 120 | 120 | 0.0% | 0 | 8.9 |
| CoAP NON | 120 | 107 | 10.8% | 0 | 1.1 |
| CoAP CON | 120 | 120 | 0.0% | 0 | 6.3 |
| AMQP (auto-ack off) | — | — | — | — | — |

> **AMQP** skipped per assignment instructions.

### Analysis

**QoS 0 / CoAP NON:** Fire-and-forget. Messages matching the 10% loss rate disappear with no recovery mechanism. Zero duplicates and sub-2 ms latency make this appropriate only for high-frequency, loss-tolerant data where the next reading arrives within milliseconds anyway (e.g., 10 Hz vibration sampling).

**QoS 1 / CoAP CON:** At-least-once delivery. Both protocols retransmit unacknowledged messages, eliminating loss entirely. QoS 1 introduced 3 duplicate deliveries during the 60-second window — these arise when a PUBACK is lost in transit and the broker retransmits a message the subscriber already processed. Applications must handle or deduplicate on the consumer side.

**QoS 2:** Exactly-once delivery via a four-way handshake (PUBLISH → PUBACK → PUBREL → PUBCOMP). Zero loss, zero duplicates, at the cost of roughly double the round-trips versus QoS 1 (~8.9 ms vs ~4.7 ms average latency). The overhead is acceptable for critical safety data but impractical for 1 Hz+ telemetry at scale.

---

## 5.2 CoAP–HTTP Proxy Header Mapping

The aiocoap reverse proxy (tested via `tests/coap/test_proxy.py`) produces the following HTTP response headers from a CoAP GET to `/factory/line1/temperature`:

| HTTP Header | CoAP Option | Option # | Observed Value |
|---|---|---|---|
| `Content-Type` | Content-Format | 12 | `application/json` (CoAP format code 50) |
| `Cache-Control: max-age` | Max-Age | 14 | `max-age=60` (default; explicit if server sets option 14) |
| `ETag` | ETag | 4 | `"a3f1b2c4"` (8-hex opaque tag from CoAP ETag option bytes) |
| `Location` | Location-Path / Location-Query | 8 / 20 | `/factory/line1/temperature` (assembled from path segments) |

**Mapping notes:**
- CoAP **Content-Format 50** maps directly to HTTP `Content-Type: application/json`. The mapping is defined in the CoAP content-format registry (RFC 7252 §12.3).
- CoAP **Max-Age** (seconds as a uint) maps to HTTP `Cache-Control: max-age=N`. If the CoAP server does not set Max-Age, the proxy defaults to 60 seconds per RFC 7252 §5.10.5.
- CoAP **ETag** bytes are hex-encoded and wrapped in quotes to form an HTTP ETag value.
- CoAP **Location-Path** segments are joined with `/` to produce the HTTP `Location` header, used in 2.01 Created responses to new resources.

---

## 5.3 Protocol Selection Recommendation

### SmartFactory CTO — Protocol Recommendation

The following recommendations are grounded in measured wire-level behaviour (see §5.1) and implementation observations during this assignment.

---

#### Data Path 1: Sensor → Cloud (high frequency, <100 ms latency)

**Recommended: MQTT QoS 0**

For high-frequency telemetry (≥1 Hz) flowing from sensors to the cloud, MQTT at QoS 0 is the optimal choice. The wire-level evidence is clear: QoS 0 PUBLISH frames carry no Packet Identifier field (confirmed in the pcap analysis, §4.2), eliminating the PUBACK round-trip entirely. This yields sub-2 ms median latency on the loopback interface, well within the <100 ms budget even after accounting for WAN jitter.

MQTT's persistent TCP connection also amortises connection overhead across thousands of messages, unlike CoAP which re-establishes reliability per message. The Mosquitto broker's fan-out capability means one PUBLISH can be consumed by multiple downstream subscribers (cloud storage, alerting engine, dashboard) without additional network traffic.

Accepted trade-off: at 10% packet loss, ~10% of readings are dropped. At 1 Hz sampling, one lost reading per 10 seconds is tolerable because the next reading arrives one second later. The QoS experiment confirms: 12 messages lost out of 120 over 60 s, none of which were temperature spikes (by statistical chance). For the vibration and power sensors, which are sampled for trend analysis rather than threshold alerting, this loss profile is entirely acceptable.

---

#### Data Path 2: Actuator Commands (safety-critical, exactly-once)

**Recommended: MQTT QoS 2**

Safety-critical commands to the cooling fan actuator must never be lost (fan fails to activate → thermal damage) and must never be delivered twice (duplicate ON/OFF could cause mechanical wear or create a race condition with interlocks). MQTT QoS 2's four-way handshake (PUBLISH → PUBACK → PUBREL → PUBCOMP) is the only mechanism in these three protocols that guarantees exactly-once semantics at the message layer.

The pcap evidence supports this: every QoS 2 exchange in the 60-second loss experiment was delivered exactly once with zero duplicates (§5.1), despite 10% packet loss. The 8.9 ms median latency is irrelevant for infrequent actuator commands — a cooling fan command is issued perhaps once per minute, not once per millisecond.

CoAP CON also delivered zero losses, but its ACK/retransmit mechanism provides at-most-once semantics (a retransmitted CON may fire the actuator again if the server processes both). CoAP lacks application-layer deduplication without adding custom sequence tokens. MQTT QoS 2's broker-side deduplication (via the in-flight store keyed on Packet Identifier) handles this transparently.

---

#### Data Path 3: Backend Service-to-Service Routing

**Recommended: AMQP (RabbitMQ)**

While AMQP was not implemented in this assignment, the architectural requirement for backend routing warrants an informed recommendation. Service-to-service communication within the SmartFactory backend (e.g., telemetry ingester → alert engine → SCADA system → audit logger) involves different delivery guarantees, routing rules, and processing rates per consumer.

AMQP's topic exchange model (as specified in Task 3) provides exactly this: routing keys like `factory.line1.temperature.critical` allow a single message to be selectively delivered to the alerts queue, the all-telemetry queue, and the line1-specific queue simultaneously. Dead Letter Exchanges handle processing failures gracefully without message loss. Publisher Confirms provide end-to-end acknowledgement from the broker.

Neither MQTT's simple topic hierarchy nor CoAP's request-response model supports this fanout-with-filtering pattern natively. MQTT wildcard subscriptions deliver all matching messages to all subscribers with no per-subscriber filtering at the broker. AMQP bindings provide server-side routing before delivery.

---

#### Data Path 4: OTA Firmware Delivery to Constrained MCU (Class 2)

**Recommended: CoAP with Block2**

Class 2 constrained devices (≤256 KB RAM, ≤1 MB flash — RFC 7228 classification) cannot maintain TCP connections or handle large payloads. CoAP was designed specifically for this environment: it runs over UDP, uses a compact binary header (4 bytes fixed + variable options), and implements Block2 transfer (RFC 7959) for reliable segmented delivery of large payloads.

The implementation evidence is direct: `src/coap/server.py` serves a 3 KB+ firmware manifest, and aiocoap's client (`src/coap/observer.py`) reassembles it transparently via Block2 without the client application managing segment ordering. The `/factory/manifest` resource in our capture showed the payload arriving in 1024-byte blocks, each independently acknowledged at the CoAP layer — exactly the behaviour needed for firmware images that may be hundreds of kilobytes.

MQTT cannot deliver large payloads to Class 2 devices because it requires TCP, which is impractical on MCUs with minimal network stacks. HTTP is even heavier. CoAP with DTLS (port 5684) adds transport-layer security with a much smaller footprint than TLS.

---

## 5.4 Reflection

### Technical Challenge: CoAP Observable Resource Deregistration

The most significant implementation challenge was achieving clean Observe deregistration in `src/coap/observer.py`. The RFC 7641 specification states that a client deregisters by sending a GET request with the **Observe option set to 1**. In practice, aiocoap's observation API exposes observations as an async generator, and cancelling the generator does not automatically send the deregister request — the server simply times out the subscription after the Max-Age window.

The resolution required explicitly sending a second GET (with `observe=1`) after the async generator loop exited, inside the `finally` block of `observe_resource()`. Without this, the CoAP server continued emitting notifications to a client that was no longer processing them, wasting network resources and producing spurious errors in the server log. This taught a concrete lesson: protocol compliance at the wire level (sending the correct option byte) and library abstraction levels do not always align — reading the RFC directly was essential.

### Most Surprising Difference: MQTT's Per-Message Overhead vs. CoAP's Per-Request Overhead

The most surprising observation during the packet capture task was how differently the two protocols distribute their overhead. MQTT amortises connection setup across all messages — the CONNECT handshake (≈50 bytes) is a one-time cost, and each subsequent PUBLISH at QoS 0 is just 2 bytes fixed header + topic + payload. CoAP, by contrast, includes a full 4-byte header on every single datagram, plus option bytes for Uri-Path on every GET. For a six-character topic like `line1` versus repeated `/factory/line1/temperature` Uri-Path options, the per-message overhead in CoAP is noticeably larger for polling-style communication.

What made this surprising was the inversion for observable resources: once an Observe subscription is registered, CoAP notifications carry only the response code and payload — the Uri-Path is not repeated — making them as compact as MQTT PUBLISH frames for the same data. The choice between protocols thus depends fundamentally on the communication pattern, not just the protocol's reputation for "lightness."

### Most Complex Protocol: MQTT (Persistent Sessions + QoS State Machine)

MQTT was the most complex to implement correctly. The QoS 2 state machine (PUBLISH → PUBACK → PUBREL → PUBCOMP) and its interaction with the `clean_session=False` persistent session created subtle correctness requirements. With `clean_session=False`, the broker retains the in-flight QoS 2 store across disconnections; on reconnect, incomplete exchanges are resumed. This means the publisher must assign globally unique Packet Identifiers and the subscriber must handle duplicate deliveries from resumed sessions correctly.

The LWT configuration added another layer: the retained `online`/`offline` status messages interact with the broker's retain store in ways that required careful ordering — `online` must be published after the CONNACK is received (not before), or the broker may overwrite it with a stale retained message from a previous session. Getting the on_connect callback timing exactly right, and verifying it with the pcap (checking the retained flag on the status PUBLISH frames), required multiple iterations.

---

*Word count: approximately 1,650 words (sections 5.3 + 5.4)*
