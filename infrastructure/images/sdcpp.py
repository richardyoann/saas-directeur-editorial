"""Private image HTTP adapter; no persistence or filesystem dependency."""
import asyncio
import base64
import binascii
import json
import os
import httpx
from editorial.media_rules import (
    MAX_PNG_BYTES, IMAGE_PARAMETERS, IMAGE_SAMPLE_PARAMETERS,
    ImageUnavailable, validate_png, private_image_url)


DEFAULT_IMAGE_TIMEOUT_SECONDS = 300


def image_timeout_seconds():
    """Bound a local diffusion call; sd.cpp can exceed two minutes on CPU/Vulkan."""
    raw = os.getenv("ARVOR_IMAGE_TIMEOUT_SECONDS", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_IMAGE_TIMEOUT_SECONDS
    return min(600, max(30, value))


def native_extension(seed, sample_parameters=None):
    """Encode explicit sampling controls for the OpenAI-compatible endpoint.

    sd.cpp strips this block before generation; it only carries native sampling
    fields.  Keeping the block deterministic makes the request reproducible.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0x7FFFFFFF:
        raise ImageUnavailable()
    sample = dict(sample_parameters or IMAGE_SAMPLE_PARAMETERS)
    payload = {
        "seed": seed,
        "sample_params": {
            "sample_steps": int(sample["sample_steps"]),
            "sample_method": str(sample["sample_method"]),
            "scheduler": str(sample["scheduler"]),
            "guidance": {"txt_cfg": float(sample["txt_cfg"])},
        },
    }
    return ("<sd_cpp_extra_args>"
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "</sd_cpp_extra_args>")


async def render_png(client: httpx.AsyncClient, base_url: str, prompt: str,
                     seed=None, sample_parameters=None):
    if not private_image_url(base_url):
        raise ImageUnavailable()
    request_prompt = prompt
    if seed is not None:
        request_prompt = prompt + " " + native_extension(seed, sample_parameters)
    timeout = image_timeout_seconds()
    try:
        async with asyncio.timeout(timeout):
            async with client.stream(
                "POST", base_url.rstrip("/") + "/v1/images/generations",
                json={"prompt": request_prompt, **IMAGE_PARAMETERS},
                timeout=float(timeout), follow_redirects=False
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

    async def render(self, prompt, seed=None):
        return await render_png(self.client, self.base_url, prompt, seed=seed)
