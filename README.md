# Module 1 Assignment — SmartFactory IoT Protocol Integration

**Real-Time Data Analytics for IoT** · Graduate Course · Module 1

**Student Name:** Darsh Jignesh Pandya

**Student ID:** 101045061

---

## Quick Start

```bash
# 1. Install dependencies and start Docker services
bash setup.sh

# 2. Start infrastructure
docker compose up -d mosquitto

# 3. Run MQTT publisher + subscriber (two terminals)
python -m src.mqtt.publisher       # Terminal 1
python -m src.mqtt.subscriber      # Terminal 2

# 4. Run CoAP server + observer (two terminals)
python -m src.coap.server          # Terminal 1
python -m src.coap.observer        # Terminal 2

# 5. Run all tests
pytest tests/ -v --tb=short

# 6. Run QoS experiment (Task 1.3) — needs running broker
pytest tests/mqtt/test_qos_loss.py -v -s

# 7. Capture packets (Task 4) — needs publisher + CoAP server running
bash scripts/capture.sh
```

---

## Repository Structure

```
module1-assignment/
├── src/
│   ├── mqtt/
│   │   ├── publisher.py      <- Task 1.1  Complete
│   │   └── subscriber.py     <- Task 1.2  Complete
│   ├── coap/
│   │   ├── server.py         <- Task 2.1  Complete
│   │   └── observer.py       <- Task 2.2  Complete
│   └── amqp/
│       ├── topology.py       <- Task 3.1  Skipped
│       ├── producer.py       <- Task 3.2  Skipped
│       └── consumer.py       <- Task 3.3  Skipped
├── tests/
│   ├── mqtt/
│   │   ├── test_publisher.py   Unit tests (mock-based, no broker needed)
│   │   ├── test_subscriber.py  Unit tests (mock-based, no broker needed)
│   │   └── test_qos_loss.py    Integration - needs live Mosquitto
│   ├── coap/
│   │   ├── test_server.py      Integration - in-process server
│   │   └── test_proxy.py       CoAP-HTTP proxy mapping
│   └── amqp/
│       └── test_topology.py    All marked skip
├── report/
│   ├── packet_analysis.md    <- Task 4 annotation tables
│   └── comparison_report.md  <- Task 5 full report (~1650 words)
├── captures/                 <- Run scripts/capture.sh to populate
├── scripts/
│   └── capture.sh
├── config/
│   └── mosquitto.conf
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── setup.sh
```

---

## Infrastructure

| Service | Port | Notes |
|---------|------|-------|
| Mosquitto MQTT | 1883 | `docker compose up -d mosquitto` |
| CoAP server | 5683 | `python -m src.coap.server` |
| RabbitMQ AMQP | 5672 | Task 3 skipped |
| RabbitMQ Management | 15672 | http://localhost:15672 (guest/guest) |

---

## Key Design Decisions

**MQTT Publisher:** Uses `clean_session=False` (persistent session). LWT configured
with `retain=True`. The `online` retained message is published inside `on_connect`
(after CONNACK) to avoid race conditions with stale retained status messages.

**CoAP Server:** Observable resources call `self.updated_state()` after each 5-second
refresh. The `/factory/manifest` resource is padded to >= 3 KB, forcing aiocoap's
automatic Block2 segmented transfer.

**CoAP Observer:** Stale notifications detected by comparing Observe sequence numbers.
Clean deregistration sends GET with Observe=1 in the finally block per RFC 7641 S3.6.

---

*Graduate Course: Real-Time Data Analytics for IoT - Module 1*
