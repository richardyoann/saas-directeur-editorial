"""Bound incoming HTTP bodies before framework JSON decoding/auth dependencies."""
import asyncio
import json


MAX_REQUEST_BYTES = 256000
REQUEST_BODY_TIMEOUT = 15
MAX_JSON_DEPTH = 128


class JSONTooDeep(ValueError):
    """JSON container depth exceeds the application contract."""


def load_bounded_json(raw):
    """Enforce the same depth contract even with a non-recursive decoder."""
    value = json.loads(raw)
    pending = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        if not isinstance(item, (dict, list)):
            continue
        if depth > MAX_JSON_DEPTH:
            raise JSONTooDeep("JSON nesting too deep")
        children = item.values() if isinstance(item, dict) else item
        pending.extend((child, depth + 1) for child in children
                       if isinstance(child, (dict, list)))
    return value


class RequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(REQUEST_BODY_TIMEOUT):
                while True:
                    event = await receive()
                    if event["type"] == "http.disconnect":
                        return
                    chunk = event.get("body", b"")
                    if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                        return await self.reject(send, 413)
                    body.extend(chunk)
                    if not event.get("more_body", False):
                        break
        except TimeoutError:
            return await self.reject(send, 408)
        # FastAPI decodes JSON before resolving authentication dependencies.
        # Enforce a stable limit; decoder recursion differs by Python version.
        if any(key.lower() == b"content-type" and b"application/json" in value.lower()
               for key, value in scope.get("headers", [])):
            try:
                load_bounded_json(body)
            except (JSONTooDeep, RecursionError):
                return await self.reject(send, 422)
            except (ValueError, UnicodeDecodeError):
                pass  # Route/framework keeps its existing malformed-JSON response.
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def reject(send, status):
        message = {413: "Request body too large.", 408: "Request body timeout.",
                   422: "JSON nesting too deep."}[status]
        body = json.dumps({"detail": message}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"cache-control", b"no-store"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
