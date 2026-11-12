"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api import catalog, onboardings, system, ztp
from app.config import get_settings
from app.core.state_machine import InvalidTransition
from app.core.worker import worker
from app.db import create_all, init_engine

DESCRIPTION = """
**Plug it in. Hatch does the rest.**

Hatch takes a brand-new network device or hypervisor host from *racked and cabled* to
*configured, verified, compliant and in monitoring* with no manual CLI work.

Authenticate with `Authorization: Bearer <token>`. In development the tokens
`dev-requester`, `dev-approver`, `dev-maintainer`, `dev-admin` and `dev-ztp-service`
are accepted.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_engine(settings.database_url)
        create_all()
        yield
        worker.shutdown()

    app = FastAPI(
        title="Hatch",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "onboardings", "description": "Register, preview, approve and drive."},
            {"name": "ztp", "description": "Zero-touch provisioning (edge service only)."},
            {"name": "catalog", "description": "Templates, catalog, inventory, audit, KPIs."},
            {"name": "system", "description": "Health, metrics and live events."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(InvalidTransition)
    async def _invalid_transition(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.include_router(onboardings.router)
    app.include_router(ztp.router)
    app.include_router(catalog.router)
    app.include_router(system.router)
    return app


app = create_app()
