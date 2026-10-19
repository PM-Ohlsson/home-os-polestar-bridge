"""Read-only, password-protected Polestar cloud bridge for HOME OS.

Keep secrets in your hosting provider's environment variables; never in GitHub.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from polestar_api import PolestarApi, Vehicle

# All credentials are server-side environment variables, never in index.html.
POLESTAR_EMAIL = os.environ.get("POLESTAR_EMAIL", "")
POLESTAR_PASSWORD = os.environ.get("POLESTAR_PASSWORD", "")
HOME_OS_API_KEY = os.environ.get("HOME_OS_API_KEY", "")
POLESTAR_VIN = os.environ.get("POLESTAR_VIN", "").strip()
ALLOWED_ORIGIN = os.environ.get(
    "ALLOWED_ORIGIN", "https://pm-ohlsson.github.io"
).rstrip("/")

if not HOME_OS_API_KEY or len(HOME_OS_API_KEY) < 24:
    raise RuntimeError("Set HOME_OS_API_KEY to a random value of at least 24 characters")
if not POLESTAR_EMAIL or not POLESTAR_PASSWORD:
    raise RuntimeError("Set POLESTAR_EMAIL and POLESTAR_PASSWORD as server-side secrets")
if POLESTAR_VIN and len(POLESTAR_VIN) != 17:
    raise RuntimeError("POLESTAR_VIN must be the full 17-character VIN")

app = FastAPI(title="HOME OS Polestar bridge", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)

logger = logging.getLogger("homeos.polestar")
_lock = asyncio.Lock()
_cache: dict | None = None
_cache_time: datetime | None = None
CACHE_AGE = timedelta(minutes=10)


@app.get("/health")
async def health():
    """Non-sensitive endpoint for checking that the host is awake."""
    return {"status": "ok", "service": "home-os-polestar"}


def _authorise(authorization: str | None) -> None:
    expected = "Bearer " + HOME_OS_API_KEY
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _enum_text(value) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", str(value)).lower().replace("_", " ")


async def _fetch_vehicle():
    """Fetch read-only vehicle data; allow VIN fallback for linked accounts.

    The API's get_vehicle(vin) only searches get_vehicles(), which can be
    empty for guest/linked accounts. The upstream Home Assistant integration
    instead constructs Vehicle(vin, connection) directly as a fallback.
    This uses a private library connection attribute and may require an
    update if the unofficial package changes its internals.
    """
    logger.info("Polestar diagnostic: starting authentication and endpoint discovery")
    async with PolestarApi(email=POLESTAR_EMAIL, password=POLESTAR_PASSWORD) as api:
        logger.info("Polestar diagnostic: authentication and endpoint discovery completed")
        if POLESTAR_VIN:
            logger.info("Polestar diagnostic: requesting vehicle list for configured VIN")
            try:
                vehicles = await api.get_vehicles()
                logger.info("Polestar diagnostic: vehicle list returned (%d vehicles)", len(vehicles))
            except Exception as exc:
                # Manual VIN fallback can work when vehicle discovery is unavailable.
                logger.warning("Polestar diagnostic: listing failed (%s); testing VIN directly", type(exc).__name__)
                vehicles = []

            vehicle = next((v for v in vehicles if v.vin == POLESTAR_VIN), None)
            if vehicle is None:
                logger.info("Polestar diagnostic: VIN absent from list; trying direct vehicle connection")
                connection = api._connection  # Matches upstream HA integration's VIN fallback.
                if connection is None:
                    raise RuntimeError("No Polestar connection after authentication")
                vehicle = Vehicle(vin=POLESTAR_VIN, connection=connection)
        else:
            logger.info("Polestar diagnostic: requesting vehicle list")
            vehicles = await api.get_vehicles()
            logger.info("Polestar diagnostic: vehicle list returned (%d vehicles)", len(vehicles))
            if not vehicles:
                raise RuntimeError("No vehicles listed; configure POLESTAR_VIN to test direct connection")
            vehicle = vehicles[0]

        logger.info("Polestar diagnostic: requesting battery status")
        battery = await vehicle.get_battery()
        if battery is None:
            raise RuntimeError("Polestar returned no battery data for this VIN")
        logger.info("Polestar diagnostic: battery status received")
        return {
            "soc_percent": round(float(battery.charge_level)),
            "range_km": round(float(battery.range_km)),
            "charging_status": _enum_text(battery.charging_status),
            "plugged_in": bool(battery.is_plugged_in),
            "charging_power_kw": round(float(battery.power_watts) / 1000, 1),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "polestar",
            "stale": False,
        }


@app.get("/api/vehicle")
async def vehicle(authorization: str | None = Header(default=None)):
    global _cache, _cache_time
    _authorise(authorization)
    now = datetime.now(timezone.utc)
    if _cache is not None and _cache_time and now - _cache_time < CACHE_AGE:
        return _cache
    async with _lock:
        now = datetime.now(timezone.utc)
        if _cache is not None and _cache_time and now - _cache_time < CACHE_AGE:
            return _cache
        try:
            fresh = await asyncio.wait_for(_fetch_vehicle(), timeout=55)
        except Exception as exc:
            # Do not include raw Polestar exceptions in HTTP responses: they may
            # contain private information or implementation details.
            logger.warning("Polestar request failed: %s", type(exc).__name__)
            if _cache is not None:
                return {**_cache, "stale": True}
            raise HTTPException(status_code=503, detail="Polestar data temporarily unavailable") from None
        _cache, _cache_time = fresh, datetime.now(timezone.utc)
        return fresh
