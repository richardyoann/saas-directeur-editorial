"""Private image HTTP adapter; no persistence or filesystem dependency."""
import asyncio
import base64
import binascii
import json
import httpx
from editorial.media_rules import MAX_PNG_BYTES, IMAGE_PARAMETERS, ImageUnavailable, validate_png, private_image_url


async def render_png(client: httpx.AsyncClient, base_url: str, prompt: str):
    if not private_image_url(base_url):
        raise ImageUnavailable()
    try:
        async with asyncio.timeout(120):
            async with client.stream(
                "POST", base_url.rstrip("/") + "/v1/images/generations",
                json={"prompt": prompt, **IMAGE_PARAMETERS},
                timeout=120.0, follow_redirects=False
            ) as response:
                if response.status_code >= 500:
                    raise ImageUnavailable("image_provider_response_uncertain")
                if response.status_code != 200:
                    raise ImageUnavailable("image_provider_rejected")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_PNG_BYTES * 2:
                        raise ImageUnavailable()
                    body.extend(chunk)
                payload = json.loads(body)
        entries = payload.get("data") if isinstance(payload, dict) else None
        encoded = entries[0].get("b64_json") if isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], dict) else None
        if not isinstance(encoded, str) or len(encoded) > MAX_PNG_BYTES * 2:
            raise ImageUnavailable()
        data = base64.b64decode(encoded, validate=True)
        validate_png(data)
        return data
    except (httpx.TimeoutException, TimeoutError):
        raise ImageUnavailable("image_provider_timeout") from None
    except httpx.HTTPError:
        raise ImageUnavailable("image_provider_response_uncertain") from None
    except (ValueError, KeyError, TypeError, binascii.Error, RecursionError):
        raise ImageUnavailable() from None


class PrivateImageRenderer:
    def __init__(self, client, base_url):
        self.client, self.base_url = client, base_url

    def configured(self):
        return private_image_url(self.base_url)

    async def render(self, prompt):
        return await render_png(self.client, self.base_url, prompt)
