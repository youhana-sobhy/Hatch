"""Health, Prometheus metrics and the live event stream."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select, text

from app import __version__
from app.api.deps import principal_for_token
from app.core.events import bus
from app.db import session_scope
from app.models import ComplianceResult, Onboarding, StageRun

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/readyz", summary="Readiness (database reachable)")
def readyz() -> dict:
    with session_scope() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics")
def metrics() -> str:
    lines = [
        "# HELP hatch_onboardings Onboardings by status.",
        "# TYPE hatch_onboardings gauge",
    ]
    with session_scope() as session:
        for state, count in session.execute(
            select(Onboarding.status, func.count()).group_by(Onboarding.status)
        ):
            lines.append(f'hatch_onboardings{{status="{state}"}} {count}')
        lines += [
            "# HELP hatch_stage_runs_total Pipeline stage runs by stage and result.",
            "# TYPE hatch_stage_runs_total counter",
        ]
        for stage, result, count in session.execute(
            select(StageRun.stage, StageRun.status, func.count()).group_by(StageRun.stage, StageRun.status)
        ):
            lines.append(f'hatch_stage_runs_total{{stage="{stage}",result="{result}"}} {count}')
        lines += [
            "# HELP hatch_compliance_results_total Compliance rule evaluations.",
            "# TYPE hatch_compliance_results_total counter",
        ]
        for passed, count in session.execute(
            select(ComplianceResult.passed, func.count()).group_by(ComplianceResult.passed)
        ):
            lines.append(f'hatch_compliance_results_total{{result="{"pass" if passed else "fail"}"}} {count}')
    return "\n".join(lines) + "\n"


@router.websocket("/api/v1/events")
async def events(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live stream of status and stage events. Authenticate with ``?token=``."""
    principal = principal_for_token(token)
    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    subscriber = bus.subscribe()
    try:
        await websocket.send_json({"type": "hello", "user": principal.user})
        while True:
            try:
                event = await asyncio.wait_for(subscriber.queue.get(), timeout=25)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(subscriber)
