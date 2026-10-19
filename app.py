"""Read-only, password-protected Polestar cloud bridge for HOME OS.

Keep secrets in your hosting provider's environment variables; never in GitHub.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import re
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from polestar_api import PolestarApi

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
    """Fetch only the data displayed on HOME OS. No remote vehicle commands."""
    # Temporary diagnostic markers. No tokens, passwords, or vehicle identifiers logged.
    logger.warning("Polestar diagnostic: starting authentication and endpoint discovery")
    async with PolestarApi(email=POLESTAR_EMAIL, password=POLESTAR_PASSWORD) as api:
        logger.warning("Polestar diagnostic: authentication and endpoint discovery completed")
        if POLESTAR_VIN:
            logger.warning("Polestar diagnostic: looking up configured vehicle")
            vehicle = await api.get_vehicle(POLESTAR_VIN)
        else:
            logger.warning("Polestar diagnostic: requesting vehicle list")
            vehicles = await api.get_vehicles()
            logger.warning("Polestar diagnostic: vehicle list returned (%d vehicles)", len(vehicles))
            if not vehicles:
                raise RuntimeError("No vehicle available in this Polestar account")
            vehicle = vehicles[0]
        logger.warning("Polestar diagnostic: requesting battery data")
        battery = await vehicle.get_battery()
        logger.warning("Polestar diagnostic: battery request completed (has data: %s)", battery is not None)
        if battery is None:
            raise RuntimeError("Polestar did not return battery data for this vehicle")
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


def _safe_polestar_failure(exc: Exception) -> str:
    """Describe known login failures without logging credentials, tokens or redirect URLs.

    Some AuthError messages include a full redirect URL. Never log the raw
    exception message because those URLs can contain authentication codes.
    """
    name = type(exc).__name__
    if name == "AuthError":
        message = str(exc)
        if message == "Invalid username or password":
            return "AuthError: credentials rejected by Polestar"
        if message.startswith("Could not find resume path in auth response"):
            match = re.search(r"status (\d{3})", message)
            status = match.group(1) if match else "unknown"
            return f"AuthError: unexpected login page (HTTP {status}); login flow may have changed or been blocked"
        if message.startswith("Auth failed with status"):
            match = re.search(r"status (\d{3})", message)
            status = match.group(1) if match else "unknown"
            return f"AuthError: credential submission returned HTTP {status}"
        if message.startswith("No auth code in redirect"):
            return "AuthError: no authorization code after login (redirect/consent/verification flow)"
        if message.startswith("Token refresh failed"):
            match = re.search(r"(\d{3})", message)
            status = match.group(1) if match else "unknown"
            return f"AuthError: token refresh returned HTTP {status}"
        if message == "Not authenticated":
            return "AuthError: no active authentication session"
        return "AuthError: other authentication problem (details hidden to protect tokens)"
    if isinstance(exc, asyncio.TimeoutError):
        return "TimeoutError: Polestar request took too long"
    if isinstance(exc, RuntimeError):
        if str(exc) == "No vehicle available in this Polestar account":
            return "RuntimeError: authentication succeeded, but vehicle list was empty"
        if str(exc) == "Polestar did not return battery data for this vehicle":
            return "RuntimeError: vehicle found, but battery data was unavailable"
    return f"{name}: request unsuccessful (details hidden)"


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
            logger.warning("Polestar request failed: %s", _safe_polestar_failure(exc))
            if _cache is not None:
                return {**_cache, "stale": True}
            raise HTTPException(status_code=503, detail="Polestar data temporarily unavailable") from None
        _cache, _cache_time = fresh, datetime.now(timezone.utc)
        return fresh
