from __future__ import annotations

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging import request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        header_name = REQUEST_ID_HEADER.lower().encode("latin-1")
        headers = dict(scope.get("headers") or [])
        raw = headers.get(header_name)
        request_id = raw.decode("latin-1") if raw else str(uuid.uuid4())

        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id
        token = request_id_ctx.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                response_headers.append(
                    (header_name, request_id.encode("latin-1"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_ctx.reset(token)
