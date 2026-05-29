#!/usr/bin/env bash
# scripts/capture.sh — Task 4 Packet Capture
# Captures MQTT (1883) and CoAP (5683) traffic simultaneously for 30 seconds.
# Output: captures/mqtt.pcap  captures/coap.pcap
#
# Prerequisites: tshark installed (part of Wireshark)
#   sudo apt install tshark   OR   brew install wireshark

set -e

CAPTURE_DIR="$(dirname "$0")/../captures"
mkdir -p "$CAPTURE_DIR"

DURATION=30

echo "=================================================="
echo " SmartFactory — Packet Capture (Task 4)"
echo "=================================================="
echo " Capturing for ${DURATION} seconds on all interfaces…"
echo " Make sure publisher and CoAP server are running!"
echo "--------------------------------------------------"

# ── Check tshark ──────────────────────────────────────────────────────────────
if ! command -v tshark &>/dev/null; then
    echo "ERROR: tshark not found. Install Wireshark/tshark first."
    echo "  sudo apt install tshark   # Debian/Ubuntu"
    echo "  brew install wireshark    # macOS"
    exit 1
fi

# ── MQTT capture (port 1883) ──────────────────────────────────────────────────
echo "[1/2] Capturing MQTT traffic (port 1883) → captures/mqtt.pcap"
tshark \
    -i any \
    -f "tcp port 1883" \
    -a duration:${DURATION} \
    -w "${CAPTURE_DIR}/mqtt.pcap" \
    -q &

MQTT_PID=$!

# ── CoAP capture (port 5683) ──────────────────────────────────────────────────
echo "[2/2] Capturing CoAP traffic (port 5683) → captures/coap.pcap"
tshark \
    -i any \
    -f "udp port 5683" \
    -a duration:${DURATION} \
    -w "${CAPTURE_DIR}/coap.pcap" \
    -q &

COAP_PID=$!

echo ""
echo "Captures running for ${DURATION} seconds…"
wait $MQTT_PID
wait $COAP_PID

echo ""
echo "=================================================="
echo " Captures complete:"
ls -lh "${CAPTURE_DIR}"/*.pcap 2>/dev/null || echo "  (no pcap files — check tshark permissions)"
echo ""
echo " Quick inspection:"
echo "   tshark -r captures/mqtt.pcap -V | head -80"
echo "   tshark -r captures/coap.pcap -V | head -80"
echo "=================================================="
