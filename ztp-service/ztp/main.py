"""Hatch ZTP edge service.

The only Hatch component that brand-new devices talk to. It runs next to the management
network (centrally, or as a small edge pod per site) and:

* serves Day-0 bootstraps in each vendor's native format and URL convention
  (NX-OS POAP script, Junos config, FortiOS / PAN-OS bootstrap, ESXi kickstart),
* relays call-homes to the orchestrator,
* serves OS images from a local directory,
* rate-limits every client IP and never exposes the orchestrator API to devices.

It holds no state and no secrets other than its own service token.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

__version__ = "0.1.0"

log = logging.getLogger("hatch.ztp")

ORCHESTRATOR_URL = os.getenv("HATCH_ORCHESTRATOR_URL", "http://localhost:8000").rstrip("/")
SERVICE_TOKEN = os.getenv("HATCH_ZTP_SERVICE_TOKEN", "dev-ztp-service")
IMAGE_DIR = Path(os.getenv("HATCH_ZTP_IMAGE_DIR", "./images"))
RATE_LIMIT = int(os.getenv("HATCH_ZTP_RATE_LIMIT", "30"))  # requests per minute per IP

CONTENT_TYPES = {
    "nxos": "text/x-python",
    "junos": "text/plain",
    "fortios": "text/plain",
    "panos": "text/plain",
    "esxi": "text/plain",
}


class RateLimiter:
    """Sliding one-minute window per client IP."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            window = self._hits[key]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True


class CallHome(BaseModel):
    serial: str
    token: str
    model: str | None = None
    ip: str | None = None
    os_version: str | None = None


def create_app(transport: httpx.BaseTransport | None = None) -> FastAPI:
    app = FastAPI(title="Hatch ZTP service", version=__version__)
    limiter = RateLimiter(RATE_LIMIT)
    client = httpx.Client(
        base_url=ORCHESTRATOR_URL,
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        timeout=15,
        transport=transport,
    )

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _guard(request: Request) -> str:
        ip = _client_ip(request)
        if not limiter.allow(ip):
            raise HTTPException(429, "slow down")
        return ip

    def _bootstrap(serial: str, request: Request, vendor: str | None = None) -> PlainTextResponse:
        ip = _guard(request)
        try:
            response = client.get(f"/api/v1/ztp/bootstrap/{serial}", headers={"X-Client-IP": ip})
        except httpx.HTTPError as exc:
            log.error("orchestrator unreachable: %s", exc)
            raise HTTPException(503, "bootstrap temporarily unavailable") from exc
        if response.status_code != 200:
            log.warning("bootstrap refused for serial=%s ip=%s (%s)", serial, ip, response.status_code)
            raise HTTPException(404, "not found")  # never reveal why
        actual = response.headers.get("X-Hatch-Vendor", "")
        if vendor and actual and vendor != actual:
            raise HTTPException(404, "not found")
        log.info("bootstrap served serial=%s vendor=%s ip=%s", serial, actual, ip)
        return PlainTextResponse(
            response.text,
            media_type=CONTENT_TYPES.get(actual, "text/plain"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "version": __version__, "orchestrator": ORCHESTRATOR_URL}

    @app.get("/bootstrap/{serial}")
    def bootstrap(serial: str, request: Request):
        return _bootstrap(serial, request)

    # Vendor-native URL conventions (point the DHCP options at these).
    @app.get("/poap/{serial}.py")
    def poap(serial: str, request: Request):
        return _bootstrap(serial, request, "nxos")

    @app.get("/junos/{serial}.conf")
    def junos(serial: str, request: Request):
        return _bootstrap(serial, request, "junos")

    @app.get("/fortios/{serial}.conf")
    def fortios(serial: str, request: Request):
        return _bootstrap(serial, request, "fortios")

    @app.get("/panos/{serial}/init-cfg.txt")
    def panos(serial: str, request: Request):
        return _bootstrap(serial, request, "panos")

    @app.get("/esxi/{serial}.ks")
    def esxi(serial: str, request: Request):
        return _bootstrap(serial, request, "esxi")

    def _relay(body: CallHome, request: Request) -> dict:
        ip = _guard(request)
        payload = body.model_dump()
        payload["ip"] = payload.get("ip") or ip
        try:
            response = client.post("/api/v1/ztp/callhome", json=payload)
        except httpx.HTTPError as exc:
            raise HTTPException(503, "call-home temporarily unavailable") from exc
        if response.status_code != 200:
            log.warning("call-home refused serial=%s ip=%s: %s", body.serial, ip, response.text)
            raise HTTPException(403, "call-home refused")
        data = response.json()
        log.info("call-home accepted serial=%s onboarding=%s", body.serial, data["id"])
        return {"status": "accepted", "onboarding": data["id"], "hostname": data["hostname"]}

    @app.post("/callhome")
    def callhome(body: CallHome, request: Request) -> dict:
        return _relay(body, request)

    @app.get("/callhome")
    def callhome_get(serial: str, token: str, request: Request, model: str | None = None) -> dict:
        """For platforms whose Day-0 can only issue a GET (e.g. Junos op-script URL)."""
        return _relay(CallHome(serial=serial, token=token, model=model), request)

    @app.get("/images/{name}")
    def image(name: str, request: Request):
        _guard(request)
        path = (IMAGE_DIR / name).resolve()
        if IMAGE_DIR.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path)

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
