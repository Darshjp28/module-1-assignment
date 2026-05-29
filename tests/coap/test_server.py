"""
tests/coap/test_server.py
Integration tests for src/coap/server.py

Requires the CoAP server to be running:
    python -m src.coap.server   (in a separate terminal)

OR the tests spin up a temporary server in-process using pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import json
import threading

import aiocoap
import aiocoap.resource as resource
from aiocoap import Context, Message
from aiocoap.numbers.codes import Code
import pytest


# ── In-process server fixture ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def coap_context():
    """Start server + client context for the entire test module."""
    # Import lazily to avoid import-time side effects
    from src.coap.server import (
        SensorResource, SimpleSensorResource, FanActuatorResource,
        ManifestResource, _gen_temperature, _gen_vibration, _gen_power,
    )

    root = resource.Site()
    temp_l1 = SensorResource("line1", "temperature", _gen_temperature)
    temp_l2 = SensorResource("line2", "temperature", _gen_temperature)
    vib_l1  = SensorResource("line1", "vibration", _gen_vibration)
    pwr_l1  = SimpleSensorResource("line1", "power", _gen_power)
    pwr_l2  = SimpleSensorResource("line2", "power", _gen_power)
    fan_l1  = FanActuatorResource("line1")
    manifest = ManifestResource()

    root.add_resource(["factory", "line1", "temperature"], temp_l1)
    root.add_resource(["factory", "line2", "temperature"], temp_l2)
    root.add_resource(["factory", "line1", "vibration"], vib_l1)
    root.add_resource(["factory", "line1", "power"], pwr_l1)
    root.add_resource(["factory", "line2", "power"], pwr_l2)
    root.add_resource(["actuator", "line1", "fan"], fan_l1)
    root.add_resource(["factory", "manifest"], manifest)

    server_ctx = await Context.create_server_context(root, bind=("127.0.0.1", 15683))
    client_ctx = await Context.create_client_context()

    yield client_ctx

    await client_ctx.shutdown()
    await server_ctx.shutdown()


BASE = "coap://127.0.0.1:15683"


# ── test_get_temperature ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_temperature(coap_context):
    """GET /factory/line1/temperature must return 2.05 Content with JSON body."""
    client = coap_context
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line1/temperature")
    resp = await client.request(req).response

    assert resp.code == Code.CONTENT
    assert resp.opt.content_format == 50   # application/json

    data = json.loads(resp.payload)
    assert data["sensor"] == "temperature"
    assert data["line"] == "line1"
    assert isinstance(data["value"], (int, float))
    assert 60.0 <= data["value"] <= 98.0


@pytest.mark.asyncio
async def test_get_line2_temperature(coap_context):
    """GET /factory/line2/temperature must return valid data for line2."""
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line2/temperature")
    resp = await coap_context.request(req).response

    assert resp.code == Code.CONTENT
    data = json.loads(resp.payload)
    assert data["line"] == "line2"


@pytest.mark.asyncio
async def test_get_vibration(coap_context):
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line1/vibration")
    resp = await coap_context.request(req).response
    assert resp.code == Code.CONTENT
    data = json.loads(resp.payload)
    assert data["sensor"] == "vibration"
    assert 0.1 <= data["value"] <= 5.0


@pytest.mark.asyncio
async def test_get_power(coap_context):
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line1/power")
    resp = await coap_context.request(req).response
    assert resp.code == Code.CONTENT
    data = json.loads(resp.payload)
    assert data["sensor"] == "power"


# ── test_put_actuator ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_put_actuator_on(coap_context):
    """PUT {"state":"ON"} must return 2.04 Changed."""
    payload = json.dumps({"state": "ON"}).encode()
    req = Message(code=Code.PUT, uri=f"{BASE}/actuator/line1/fan", payload=payload)
    req.opt.content_format = 50
    resp = await coap_context.request(req).response

    assert resp.code == Code.CHANGED
    data = json.loads(resp.payload)
    assert data["state"] == "ON"


@pytest.mark.asyncio
async def test_put_actuator_off(coap_context):
    """PUT {"state":"OFF"} must return 2.04 Changed."""
    payload = json.dumps({"state": "OFF"}).encode()
    req = Message(code=Code.PUT, uri=f"{BASE}/actuator/line1/fan", payload=payload)
    req.opt.content_format = 50
    resp = await coap_context.request(req).response

    assert resp.code == Code.CHANGED
    data = json.loads(resp.payload)
    assert data["state"] == "OFF"


@pytest.mark.asyncio
async def test_put_actuator_bad_state(coap_context):
    """PUT with invalid state must return 4.00 Bad Request."""
    payload = json.dumps({"state": "MAYBE"}).encode()
    req = Message(code=Code.PUT, uri=f"{BASE}/actuator/line1/fan", payload=payload)
    req.opt.content_format = 50
    resp = await coap_context.request(req).response

    assert resp.code == Code.BAD_REQUEST


# ── test_block2_manifest ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_block2_manifest(coap_context):
    """GET /factory/manifest must return >= 3 072 bytes (triggers Block2)."""
    req = Message(code=Code.GET, uri=f"{BASE}/factory/manifest")
    resp = await coap_context.request(req).response

    assert resp.code == Code.CONTENT
    assert len(resp.payload) >= 3072, (
        f"Manifest too small: {len(resp.payload)} bytes (need >= 3072)"
    )
    # Must be valid JSON
    data = json.loads(resp.payload)
    assert "firmware_version" in data
    assert "files" in data
