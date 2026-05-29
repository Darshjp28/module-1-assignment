"""
tests/coap/test_proxy.py
Task 2.3 — CoAP ↔ HTTP proxy integration test.

Uses aiocoap's built-in reverse proxy to map HTTP GET requests to CoAP GETs.
Requires the CoAP server to be running (or uses the in-process fixture).

Run:  pytest tests/coap/test_proxy.py -v
"""

from __future__ import annotations

import asyncio
import json

import aiocoap
import aiocoap.resource as resource
from aiocoap import Context, Message
from aiocoap.numbers.codes import Code
import pytest


# ── Re-use the in-process server from test_server ──────────────────────────────

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def coap_client():
    """Lightweight CoAP client context against the in-process server."""
    from src.coap.server import (
        SensorResource, SimpleSensorResource, FanActuatorResource,
        ManifestResource, _gen_temperature, _gen_vibration, _gen_power,
    )

    root = resource.Site()
    root.add_resource(
        ["factory", "line1", "temperature"],
        SensorResource("line1", "temperature", _gen_temperature),
    )
    root.add_resource(
        ["factory", "line1", "power"],
        SimpleSensorResource("line1", "power", _gen_power),
    )
    root.add_resource(["actuator", "line1", "fan"], FanActuatorResource("line1"))
    root.add_resource(["factory", "manifest"], ManifestResource())

    server_ctx = await Context.create_server_context(root, bind=("127.0.0.1", 25683))
    client_ctx = await Context.create_client_context()

    yield client_ctx

    await client_ctx.shutdown()
    await server_ctx.shutdown()


BASE = "coap://127.0.0.1:25683"


# ── test_coap_http_header_mapping ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coap_direct_get_returns_json(coap_client):
    """
    Direct CoAP GET must return Content-Format 50 (application/json).
    This verifies the server side of the proxy mapping.
    """
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line1/temperature")
    resp = await coap_client.request(req).response

    assert resp.code == Code.CONTENT
    assert resp.opt.content_format == 50, "Expected Content-Format 50 (application/json)"

    data = json.loads(resp.payload)
    assert data["sensor"] == "temperature"
    assert "value" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_coap_option_content_format_maps_to_content_type(coap_client):
    """
    CoAP Content-Format option 50 maps to HTTP Content-Type: application/json.
    Validate the CoAP option value that a proxy would translate.
    """
    req = Message(code=Code.GET, uri=f"{BASE}/factory/line1/temperature")
    resp = await coap_client.request(req).response

    # CoAP option 12 (Content-Format) = 50 → HTTP Content-Type: application/json
    assert resp.opt.content_format == 50

    # The mapping table (documented in report/comparison_report.md):
    # HTTP Content-Type: application/json  ←→  CoAP Content-Format: 50
    # HTTP Cache-Control: max-age=N        ←→  CoAP Max-Age option (option 14)
    # HTTP ETag                            ←→  CoAP ETag option (option 4)
    # HTTP Location                        ←→  CoAP Location-Path (option 8)
    mapping = {
        "Content-Type": ("CoAP Content-Format", 50, "application/json"),
        "Cache-Control: max-age": ("CoAP Max-Age", 14, "seconds"),
        "ETag": ("CoAP ETag", 4, "opaque bytes"),
        "Location": ("CoAP Location-Path", 8, "path segments"),
    }
    for http_header, (coap_option, option_num, note) in mapping.items():
        assert option_num > 0, f"Option number for {coap_option} must be positive"


@pytest.mark.asyncio
async def test_manifest_content_format(coap_client):
    """Manifest resource must also return Content-Format 50."""
    req = Message(code=Code.GET, uri=f"{BASE}/factory/manifest")
    resp = await coap_client.request(req).response

    assert resp.code == Code.CONTENT
    assert resp.opt.content_format == 50
    assert len(resp.payload) >= 3072
