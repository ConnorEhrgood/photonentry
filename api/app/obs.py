"""Logs and request ids (photon-suite OPERATIONS.md §2.5): one JSON object per line on stdout, with `ts`, `level`, `service`, `msg`,
`request_id` (from `X-Request-ID`, or made up) and `org_id` where known. Never secrets: tokens, passwords and keys are not logged anywhere."""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
org_id: contextvars.ContextVar[str] = contextvars.ContextVar("org_id", default="")
_GOOD_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Addresses whose path is a secret: an intercom's provisioning token, a visitor's pass link. Access log lines name them; the token is cut out.
_SECRET_PATH = re.compile(r"(/(?:provision|passes)/v1/)[^/\s\"?]+")


def redact(msg: str) -> str:
    return _SECRET_PATH.sub(r"\1…", msg)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                               "level": record.levelname.lower(), "service": self.service, "logger": record.name, "msg": redact(record.getMessage())}
        if request_id.get():
            out["request_id"] = request_id.get()
        if org_id.get():
            out["org_id"] = org_id.get()
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure(service: str, level: int = logging.INFO) -> None:
    """JSON lines on stdout for the whole process (uvicorn's own loggers included)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True


def take_request_id(header: Optional[str]) -> str:
    """The caller's X-Request-ID when it is a sane token (so a request can be followed across Photon's services), else a new one."""
    return header if header and _GOOD_ID.match(header) else uuid.uuid4().hex


class RequestIds:
    """ASGI middleware: every request gets a request id (answered in X-Request-ID too) for the logs it causes."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = take_request_id(dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1"))
        token = request_id.set(rid)

        async def with_id(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + [(b"x-request-id", rid.encode())]}
            await send(message)
        try:
            await self.app(scope, receive, with_id)
        finally:
            request_id.reset(token)
