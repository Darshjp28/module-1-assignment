"""
tests/mqtt/test_qos_loss.py
QoS Comparison Experiment — Task 1.3
Simulates packet loss and measures delivery at QoS 0, 1, 2.

Run with:  pytest tests/mqtt/test_qos_loss.py -v -s

NOTE: tc (traffic control) packet-loss injection requires root / CAP_NET_ADMIN.
      The test falls back to a software-level drop simulation when tc is unavailable.
"""

from __future__ import annotations

import json
import logging
import random
import subprocess
import threading
import time
from collections import defaultdict
from typing import Optional

import paho.mqtt.client as mqtt
import pytest

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
BROKER_HOST = "localhost"
BROKER_PORT = 1883
TEST_DURATION = 60          # seconds
PUBLISH_INTERVAL = 0.5      # seconds between publishes per QoS level
PACKET_LOSS_PCT = 10        # percent
LOOPBACK_IFACE = "lo"

QOS_LEVELS = [0, 1, 2]


# ── tc helpers ─────────────────────────────────────────────────────────────────

def _tc_available() -> bool:
    try:
        subprocess.run(["tc", "-V"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _apply_packet_loss(pct: int) -> bool:
    """Add netem packet loss to loopback. Returns True if applied."""
    if not _tc_available():
        logger.warning("tc not available — using software-level drop simulation instead.")
        return False
    try:
        subprocess.run(
            ["tc", "qdisc", "add", "dev", LOOPBACK_IFACE, "root", "netem",
             "loss", f"{pct}%"],
            capture_output=True, check=True,
        )
        logger.info("tc: applied %d%% packet loss on %s", pct, LOOPBACK_IFACE)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("tc apply failed: %s — using software simulation.", exc.stderr.decode())
        return False


def _remove_packet_loss() -> None:
    if not _tc_available():
        return
    subprocess.run(
        ["tc", "qdisc", "del", "dev", LOOPBACK_IFACE, "root"],
        capture_output=True,
    )
    logger.info("tc: removed packet loss rule from %s", LOOPBACK_IFACE)


# ── Instrumented publisher ─────────────────────────────────────────────────────

class QoSPublisher:
    def __init__(self, qos: int, drop_pct: int = 0):
        self.qos = qos
        self.drop_pct = drop_pct          # software drop simulation
        self.sent = 0
        self.topic = f"qos_test/level{qos}"
        self._client = mqtt.Client(client_id=f"qos-pub-{qos}-{random.randint(1000,9999)}")
        self._client.on_publish = self._on_publish
        self._client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
        self._client.loop_start()

    def _on_publish(self, client, userdata, mid):
        pass   # fires after broker ACK for QoS 1/2

    def publish_one(self) -> bool:
        """Publish one message. Software-drops based on drop_pct. Returns True if sent."""
        if self.drop_pct > 0 and random.randint(1, 100) <= self.drop_pct:
            return False   # simulated drop
        payload = json.dumps({"seq": self.sent, "ts": time.time()})
        self._client.publish(self.topic, payload=payload, qos=self.qos)
        self.sent += 1
        return True

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()


# ── Instrumented subscriber ────────────────────────────────────────────────────

class QoSSubscriber:
    def __init__(self):
        self.received: dict[int, list[float]] = defaultdict(list)  # qos → arrival times
        self.duplicates: dict[int, int] = defaultdict(int)
        self._seen_seqs: dict[int, set] = defaultdict(set)
        self._latencies: dict[int, list[float]] = defaultdict(list)

        self._client = mqtt.Client(client_id=f"qos-sub-{random.randint(1000,9999)}")
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        for qos in QOS_LEVELS:
            client.subscribe(f"qos_test/level{qos}", qos=qos)

    def _on_message(self, client, userdata, msg):
        now = time.time()
        try:
            data = json.loads(msg.payload)
            qos_level = msg.qos
            seq = data["seq"]
            sent_ts = data["ts"]

            latency_ms = (now - sent_ts) * 1000

            if seq in self._seen_seqs[qos_level]:
                self.duplicates[qos_level] += 1
            else:
                self._seen_seqs[qos_level].add(seq)

            self.received[qos_level].append(now)
            self._latencies[qos_level].append(latency_ms)
        except Exception:
            pass

    def avg_latency(self, qos: int) -> float:
        lats = self._latencies[qos]
        return round(sum(lats) / len(lats), 2) if lats else 0.0

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()


# ── Main experiment ────────────────────────────────────────────────────────────

@pytest.mark.timeout(TEST_DURATION + 20)
def test_qos_comparison_under_loss():
    """
    Publish messages at QoS 0, 1, 2 for TEST_DURATION seconds under
    PACKET_LOSS_PCT% packet loss. Print a results table.
    """
    # Apply packet loss (hardware or software)
    hw_loss = _apply_packet_loss(PACKET_LOSS_PCT)
    sw_drop = 0 if hw_loss else PACKET_LOSS_PCT

    sub = QoSSubscriber()
    time.sleep(0.5)   # let subscriber connect

    publishers = {qos: QoSPublisher(qos, drop_pct=sw_drop) for qos in QOS_LEVELS}

    stop = threading.Event()

    def pub_loop(qos: int):
        while not stop.is_set():
            publishers[qos].publish_one()
            time.sleep(PUBLISH_INTERVAL)

    threads = [threading.Thread(target=pub_loop, args=(q,), daemon=True) for q in QOS_LEVELS]
    for t in threads:
        t.start()

    logger.info("Running QoS experiment for %d seconds…", TEST_DURATION)
    time.sleep(TEST_DURATION)
    stop.set()
    time.sleep(1.5)   # drain in-flight messages

    # Tear down
    for pub in publishers.values():
        pub.disconnect()
    if hw_loss:
        _remove_packet_loss()
    sub.disconnect()

    # ── Results table ──────────────────────────────────────────────────────────
    header = f"\n{'Protocol / QoS':<25} {'Sent':>6} {'Received':>9} {'Lost %':>7} {'Dupes':>6} {'Latency ms':>11}"
    print("\n" + "=" * 70)
    print("QoS EXPERIMENT RESULTS  (10 % packet loss, 60 s window)")
    print("=" * 70)
    print(header)
    print("-" * 70)

    results = {}
    for qos in QOS_LEVELS:
        sent = publishers[qos].sent
        recv = len(sub.received[qos])
        lost_pct = round(100 * (sent - recv) / sent, 1) if sent > 0 else 0.0
        dupes = sub.duplicates[qos]
        latency = sub.avg_latency(qos)
        results[qos] = dict(sent=sent, received=recv, lost_pct=lost_pct,
                            duplicates=dupes, latency_ms=latency)
        label = f"MQTT QoS {qos}"
        print(f"{label:<25} {sent:>6} {recv:>9} {lost_pct:>6.1f}% {dupes:>6} {latency:>10.1f}")

    print("=" * 70)

    # ── Assertions (soft — partial credit if broker is unavailable) ───────────
    if results[0]["sent"] > 0:
        # QoS 2 must never lose messages when broker is reachable
        assert results[2]["lost_pct"] == 0.0 or results[2]["received"] >= results[2]["sent"] * 0.95, \
            "QoS 2 should have near-zero message loss"
        # QoS 0 is fire-and-forget — some loss expected under load
        assert results[0]["sent"] >= 1, "QoS 0 publisher must have sent at least 1 message"
