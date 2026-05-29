"""
Task 2.1 — CoAP Sensor Resource Server
SmartFactory IoT Protocol Integration

Exposes:
  /factory/line1/temperature  GET (Observable)
  /factory/line2/temperature  GET (Observable)
  /factory/line1/vibration    GET (Observable)
  /factory/line1/power        GET
  /factory/line2/power        GET
  /actuator/line1/fan         GET + PUT
  /factory/manifest           GET  (>= 3 KB, triggers Block2)
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import string
from datetime import datetime, timezone

import aiocoap
import aiocoap.resource as resource
from aiocoap import Context, Message
from aiocoap.numbers.codes import Code

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [COAP-SERVER] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
COAP_HOST: str = "localhost"
COAP_PORT: int = 5683
UPDATE_INTERVAL: float = 5.0        # seconds between observable updates
CONTENT_FORMAT_JSON: int = 50       # application/json
MANIFEST_MIN_BYTES: int = 3072      # >= 3 KB to force Block2
CRITICAL_TEMP: float = 85.0


# ── Value generators ───────────────────────────────────────────────────────────

def _gen_temperature() -> float:
    if random.random() < 0.10:          # 10 % chance of critical spike
        return round(random.uniform(85.5, 97.0), 2)
    return round(random.uniform(60.0, 84.9), 2)

def _gen_vibration() -> float:
    return round(random.uniform(0.1, 5.0), 2)

def _gen_power() -> float:
    return round(random.uniform(10.0, 100.0), 2)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _json_response(code: Code, data: dict) -> Message:
    msg = Message(code=code, payload=json.dumps(data).encode())
    msg.opt.content_format = CONTENT_FORMAT_JSON
    return msg


# ── Observable sensor resource ─────────────────────────────────────────────────

class SensorResource(resource.ObservableResource):
    """
    Generic observable CoAP resource for one (line, sensor_type) pair.
    Notifies registered observers every UPDATE_INTERVAL seconds.
    """

    def __init__(self, line: str, sensor_type: str, generator_fn):
        super().__init__()
        self.line = line
        self.sensor_type = sensor_type
        self._generator_fn = generator_fn
        self._value: float = generator_fn()
        self._units = {"temperature": "°C", "vibration": "mm/s", "power": "kW"}

    # ── CoAP GET ──────────────────────────────────────────────────────────────

    async def render_get(self, request: Message) -> Message:
        data = {
            "line": self.line,
            "sensor": self.sensor_type,
            "value": self._value,
            "unit": self._units.get(self.sensor_type, ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return _json_response(Code.CONTENT, data)

    # ── Background update loop ─────────────────────────────────────────────────

    async def update_loop(self) -> None:
        """Called once at startup. Refreshes sensor value and notifies observers."""
        while True:
            await asyncio.sleep(UPDATE_INTERVAL)
            self._value = self._generator_fn()
            logger.info(
                "UPDATE  factory/%s/%s = %.2f", self.line, self.sensor_type, self._value
            )
            if self.sensor_type == "temperature" and self._value > CRITICAL_TEMP:
                logger.warning(
                    "⚠  CRITICAL TEMP  line=%s  value=%.2f°C", self.line, self._value
                )
            self.updated_state()   # triggers Observe notifications


# ── Non-observable sensor (power line2, etc.) ─────────────────────────────────

class SimpleSensorResource(resource.Resource):
    """Non-observable GET-only sensor resource."""

    def __init__(self, line: str, sensor_type: str, generator_fn):
        super().__init__()
        self.line = line
        self.sensor_type = sensor_type
        self._generator_fn = generator_fn
        self._units = {"temperature": "°C", "vibration": "mm/s", "power": "kW"}

    async def render_get(self, request: Message) -> Message:
        data = {
            "line": self.line,
            "sensor": self.sensor_type,
            "value": self._generator_fn(),
            "unit": self._units.get(self.sensor_type, ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return _json_response(Code.CONTENT, data)


# ── Fan actuator resource ──────────────────────────────────────────────────────

class FanActuatorResource(resource.Resource):
    """
    GET  → returns current fan state
    PUT  → accepts {"state": "ON"} or {"state": "OFF"}, returns 2.04 Changed
    """

    def __init__(self, line: str):
        super().__init__()
        self.line = line
        self._state: str = "OFF"

    async def render_get(self, request: Message) -> Message:
        data = {"line": self.line, "actuator": "fan", "state": self._state}
        return _json_response(Code.CONTENT, data)

    async def render_put(self, request: Message) -> Message:
        try:
            body: dict = json.loads(request.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return _json_response(Code.BAD_REQUEST, {"error": str(exc)})

        new_state: str = str(body.get("state", "")).upper()
        if new_state not in ("ON", "OFF"):
            return _json_response(
                Code.BAD_REQUEST, {"error": "state must be 'ON' or 'OFF'"}
            )

        self._state = new_state
        logger.info("ACTUATOR  line=%s  fan=%s", self.line, self._state)
        data = {"line": self.line, "actuator": "fan", "state": self._state}
        return _json_response(Code.CHANGED, data)


# ── Firmware manifest resource (Block2) ────────────────────────────────────────

class ManifestResource(resource.Resource):
    """
    Returns a firmware manifest >= 3 KB so aiocoap automatically
    triggers Block2 (block-wise) transfer.
    """

    def __init__(self):
        super().__init__()
        self._payload: bytes = self._build_manifest()
        logger.info("Manifest resource ready  size=%d bytes", len(self._payload))

    def _build_manifest(self) -> bytes:
        # Generate a realistic-looking firmware manifest
        file_entries = [
            {
                "name": f"fw_block_{i:04d}.bin",
                "offset": i * 512,
                "size": 512,
                "sha256": "".join(random.choices(string.hexdigits[:16], k=64)),
            }
            for i in range(60)
        ]
        manifest = {
            "manifest_version": "1.0",
            "firmware_version": "2.4.1",
            "release_date": "2026-05-01T00:00:00Z",
            "target_device": "SmartFactory-MCU-v3",
            "target_arch": "ARM Cortex-M4",
            "total_size_bytes": 524288,
            "block_size_bytes": 512,
            "sha256_full": "".join(random.choices(string.hexdigits[:16], k=64)),
            "files": file_entries,
            "dependencies": [
                {"lib": "SmartSensor-SDK", "version": "1.2.0"},
                {"lib": "MQTT-Nano", "version": "0.9.5"},
                {"lib": "TinyTLS", "version": "1.1.3"},
                {"lib": "aiocoap-nano", "version": "0.4.7"},
            ],
            "changelog": (
                "v2.4.1: Fixed temperature calibration offset for Class 2 sensors. "
                "Improved power management during deep-sleep cycles. "
                "Added CoAP Block2 support for OTA updates over constrained networks. "
                "Resolved race condition in MQTT reconnect logic under lossy links. "
                "Updated TinyTLS to 1.1.3 to patch CVE-2026-0042 (buffer overflow). "
                "Expanded vibration sensor range to 0.01–10 mm/s. "
                "Reduced average current draw by 12 % during idle periods. "
                "Fixed watchdog timer reset during Block2 multi-packet transfers. "
            ),
            "signature": {
                "algorithm": "Ed25519",
                "public_key_id": "smartfactory-fw-signing-key-v3",
                "value": "".join(random.choices(string.hexdigits[:16], k=128)),
            },
        }

        data = json.dumps(manifest, indent=2).encode("utf-8")

        # Pad to guarantee >= MANIFEST_MIN_BYTES
        if len(data) < MANIFEST_MIN_BYTES:
            pad_len = MANIFEST_MIN_BYTES - len(data) + 64
            manifest["_pad"] = "x" * pad_len
            data = json.dumps(manifest, indent=2).encode("utf-8")

        return data

    async def render_get(self, request: Message) -> Message:
        msg = Message(code=Code.CONTENT, payload=self._payload)
        msg.opt.content_format = CONTENT_FORMAT_JSON
        return msg


# ── Server bootstrap ───────────────────────────────────────────────────────────

async def main() -> None:
    root = resource.Site()

    # ── Observable temperature resources ──────────────────────────────────────
    temp_l1 = SensorResource("line1", "temperature", _gen_temperature)
    temp_l2 = SensorResource("line2", "temperature", _gen_temperature)

    # ── Observable vibration resource ─────────────────────────────────────────
    vib_l1 = SensorResource("line1", "vibration", _gen_vibration)

    # ── Non-observable power resources ────────────────────────────────────────
    pwr_l1 = SimpleSensorResource("line1", "power", _gen_power)
    pwr_l2 = SimpleSensorResource("line2", "power", _gen_power)

    # ── Fan actuator ──────────────────────────────────────────────────────────
    fan_l1 = FanActuatorResource("line1")

    # ── Manifest ──────────────────────────────────────────────────────────────
    manifest = ManifestResource()

    # Register all resources
    root.add_resource(["factory", "line1", "temperature"], temp_l1)
    root.add_resource(["factory", "line2", "temperature"], temp_l2)
    root.add_resource(["factory", "line1", "vibration"], vib_l1)
    root.add_resource(["factory", "line1", "power"], pwr_l1)
    root.add_resource(["factory", "line2", "power"], pwr_l2)
    root.add_resource(["actuator", "line1", "fan"], fan_l1)
    root.add_resource(["factory", "manifest"], manifest)

    # Start background update loops for observable resources
    asyncio.ensure_future(temp_l1.update_loop())
    asyncio.ensure_future(temp_l2.update_loop())
    asyncio.ensure_future(vib_l1.update_loop())

    await Context.create_server_context(root, bind=(COAP_HOST, COAP_PORT))
    logger.info(
        "CoAP server running on coap://%s:%d  (8 resources registered)",
        COAP_HOST, COAP_PORT,
    )

    # Run forever
    await asyncio.get_event_loop().create_future()


if __name__ == "__main__":
    asyncio.run(main())
