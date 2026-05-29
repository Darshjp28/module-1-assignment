"""
Task 2.2 — CoAP Observer Client
SmartFactory IoT Protocol Integration

Registers Observe on both temperature resources simultaneously,
runs for 60 s, then deregisters cleanly and fetches the manifest
via Block2.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiocoap
from aiocoap import Context, Message
from aiocoap.numbers.codes import Code

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [COAP-OBSERVER] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
SERVER_BASE: str = "coap://localhost:5683"
OBSERVE_DURATION: float = 60.0     # seconds before clean deregistration

TEMP_URIS: list[str] = [
    f"{SERVER_BASE}/factory/line1/temperature",
    f"{SERVER_BASE}/factory/line2/temperature",
]
MANIFEST_URI: str = f"{SERVER_BASE}/factory/manifest"


# ── Per-resource observation state ────────────────────────────────────────────

class ObserveTracker:
    """Tracks sequence numbers and detects stale / out-of-order notifications."""

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.last_seq: int = -1
        self.notification_count: int = 0
        self.stale_count: int = 0

    def handle(self, observe_seq: int | None, payload: dict | str) -> None:
        self.notification_count += 1
        ts = datetime.now(timezone.utc).isoformat()
        seq_val = observe_seq if observe_seq is not None else -1

        if seq_val >= 0 and seq_val < self.last_seq:
            # Stale notification — sequence went backwards
            self.stale_count += 1
            logger.warning(
                "STALE NOTIFICATION  uri=%-48s  seq=%d  (last=%d)  value=%s  ts=%s",
                self.uri, seq_val, self.last_seq, payload, ts,
            )
        else:
            logger.info(
                "OBSERVE NOTIFY  uri=%-48s  seq=%06d  value=%s  ts=%s",
                self.uri, seq_val, payload, ts,
            )

        if seq_val >= 0:
            self.last_seq = seq_val


# ── Single resource observation coroutine ─────────────────────────────────────

async def observe_resource(
    protocol: Context,
    tracker: ObserveTracker,
    stop_event: asyncio.Event,
) -> None:
    """
    Register an Observe subscription, consume notifications until stop_event
    is set, then send an Observe=1 (cancel) request.
    """
    request = Message(code=Code.GET, uri=tracker.uri, observe=0)

    try:
        pr = protocol.request(request)

        # Collect first response (confirms subscription)
        first_response = await pr.response
        obs_seq = first_response.opt.observe
        try:
            payload = json.loads(first_response.payload.decode("utf-8"))
        except Exception:
            payload = first_response.payload.decode("utf-8", errors="replace")
        tracker.handle(obs_seq, payload)

        # Stream subsequent notifications
        async for response in pr.observation:
            if stop_event.is_set():
                break
            obs_seq = response.opt.observe
            try:
                payload = json.loads(response.payload.decode("utf-8"))
            except Exception:
                payload = response.payload.decode("utf-8", errors="replace")
            tracker.handle(obs_seq, payload)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Observation error  uri=%s  exc=%s", tracker.uri, exc)
    finally:
        # Deregister: send GET with Observe=1 (RFC 7641 §3.6)
        try:
            cancel_req = Message(code=Code.GET, uri=tracker.uri, observe=1)
            await protocol.request(cancel_req).response
            logger.info("Deregistered  uri=%s", tracker.uri)
        except Exception as exc:
            logger.warning("Deregister failed  uri=%s  exc=%s", tracker.uri, exc)


# ── Block2 manifest fetch ──────────────────────────────────────────────────────

async def fetch_manifest(protocol: Context) -> tuple[int, int]:
    """
    GET /factory/manifest — aiocoap reassembles Block2 automatically.
    Returns (total_bytes, block_count).
    """
    logger.info("Fetching manifest via Block2  uri=%s", MANIFEST_URI)
    request = Message(code=Code.GET, uri=MANIFEST_URI)
    response = await protocol.request(request).response

    total_bytes: int = len(response.payload)
    # aiocoap uses 1 024-byte blocks by default (SZX=6)
    block_size: int = 1024
    block_count: int = (total_bytes + block_size - 1) // block_size

    logger.info(
        "MANIFEST  total_bytes=%d  estimated_blocks=%d  content_format=%s",
        total_bytes, block_count, response.opt.content_format,
    )

    # Validate JSON is intact after reassembly
    try:
        manifest = json.loads(response.payload.decode("utf-8"))
        logger.info("Manifest JSON valid  firmware_version=%s", manifest.get("firmware_version"))
    except Exception as exc:
        logger.warning("Manifest JSON decode error: %s", exc)

    return total_bytes, block_count


# ── Main ───────────────────────────────────────────────────────────────────────

async def main() -> None:
    protocol = await Context.create_client_context()

    trackers = [ObserveTracker(uri) for uri in TEMP_URIS]
    stop_event = asyncio.Event()

    # Launch observation tasks concurrently
    tasks = [
        asyncio.ensure_future(observe_resource(protocol, tracker, stop_event))
        for tracker in trackers
    ]

    logger.info(
        "Observing %d temperature resources for %.0f seconds…",
        len(TEMP_URIS), OBSERVE_DURATION,
    )
    await asyncio.sleep(OBSERVE_DURATION)

    # Signal observers to deregister
    logger.info("Observation window ended — deregistering…")
    stop_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Fetch firmware manifest with Block2 reassembly
    total_bytes, block_count = await fetch_manifest(protocol)

    # ── Final summary ──────────────────────────────────────────────────────────
    logger.info("━" * 60)
    logger.info("OBSERVATION SUMMARY")
    for t in trackers:
        logger.info(
            "  %-50s  notifications=%d  stale=%d  last_seq=%d",
            t.uri, t.notification_count, t.stale_count, t.last_seq,
        )
    logger.info("MANIFEST FETCH  total_bytes=%d  blocks=%d", total_bytes, block_count)
    logger.info("━" * 60)

    await protocol.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
