"""Shared API dependencies: database session and token authentication / RBAC."""

from __future__ import annotations

import secrets as pysecrets
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings
from app.core.onboarding import Principal
from app.db import get_session

SessionDep = Depends(get_session)


def principal_for_token(token: str | None) -> Principal | None:
    if not token:
        return None
    for entry in get_settings().tokens():
        if pysecrets.compare_digest(entry.token, token):
            return Principal(user=entry.user, role=entry.role, sites=tuple(entry.sites))
    return None


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    principal = principal_for_token(token)
    if principal is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require(*roles: str) -> Callable[[Principal], Principal]:
    def _check(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role: {' or '.join(roles)}")
        return principal

    return _check
