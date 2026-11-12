"""Outbound integrations as plain JSON webhooks.

Notifications (chat/email gateways), monitoring registration and ticket updates are all
delivered as plain JSON POSTs, so Hatch plugs into whatever a team already runs
without vendor SDKs. An unset URL means the integration is disabled and the call is a
recorded no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class Delivery:
    target: str
    delivered: bool
    detail: str


def post(kind: str, url: str, payload: dict[str, Any]) -> Delivery:
    if not url:
        return Delivery(kind, False, f"{kind} integration not configured; recorded locally")
    try:
        response = httpx.post(url, json={"source": "hatch", "kind": kind, **payload}, timeout=10)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("%s webhook failed: %s", kind, exc)
        return Delivery(kind, False, f"{kind} webhook failed: {exc}")
    return Delivery(kind, True, f"{kind} webhook accepted ({response.status_code})")


def notify(event: dict[str, Any]) -> Delivery:
    return post("notification", get_settings().notify_webhook_url, {"event": event})


def register_monitoring(device: dict[str, Any]) -> Delivery:
    return post("monitoring", get_settings().monitoring_webhook_url, {"device": device})


def update_ticket(ticket_ref: str | None, summary: dict[str, Any]) -> Delivery:
    if not ticket_ref:
        return Delivery("itsm", False, "no ticket reference on this onboarding")
    return post("itsm", get_settings().itsm_webhook_url, {"ticket": ticket_ref, **summary})
