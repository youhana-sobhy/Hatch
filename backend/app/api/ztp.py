"""/api/v1/ztp: Day-0 bootstrap and device call-home (called by the ZTP edge service)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, require
from app.core import onboarding as svc
from app.core.rendering import RenderError
from app.schemas import CallHome, OnboardingOut

router = APIRouter(prefix="/api/v1/ztp", tags=["ztp"])


@router.get(
    "/bootstrap/{serial}",
    response_class=PlainTextResponse,
    summary="Day-0 bootstrap for a pre-registered serial",
)
def bootstrap(
    serial: str,
    x_client_ip: str | None = Header(default=None),
    session: Session = SessionDep,
    principal: svc.Principal = Depends(require("service")),
) -> PlainTextResponse:
    try:
        ob, config = svc.bootstrap(session, serial, x_client_ip)
    except LookupError as exc:
        # Unknown or not-yet-approved serials get nothing, by design.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no bootstrap for this serial") from exc
    except RenderError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return PlainTextResponse(
        config,
        headers={"X-Hatch-Onboarding": ob.id, "X-Hatch-Vendor": ob.vendor, "Cache-Control": "no-store"},
    )


@router.post("/callhome", response_model=OnboardingOut, summary="Device call-home")
def callhome(
    body: CallHome,
    session: Session = SessionDep,
    principal: svc.Principal = Depends(require("service")),
) -> OnboardingOut:
    try:
        ob = svc.callhome(session, body.serial, body.token, body.ip, body.model)
    except svc.ActionRefused as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    session.commit()
    session.refresh(ob)
    return OnboardingOut.model_validate(ob)
