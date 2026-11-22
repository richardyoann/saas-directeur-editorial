"""Pure media rules shared by renderers and storage; no IO or adapter imports."""
import hashlib
import ipaddress
import json
import struct
from urllib.parse import urlsplit


MAX_PNG_BYTES = 4 * 1024 * 1024

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

class ImageUnavailable(Exception):
    """Absent provider, inaccessible model, invalid/unsafe output or timeout."""

    def __init__(self, code="image_provider_invalid_or_unavailable"):
        self.code = code
        super().__init__(code)

IMAGE_PARAMETERS = {"n": 1, "size": "512x512", "output_format": "png"}
IMAGE_PROMPT_VERSION = "2.0.0"
# Explicit sampling controls sent through sd.cpp's native extension. They are
# recorded with every generation so two episodes stay comparable; the engine
# defaults in this version are unknown to the caller otherwise.
IMAGE_SAMPLE_PARAMETERS = {
    "sample_steps": 20,
    "sample_method": "euler_a",
    "scheduler": "discrete",
    "txt_cfg": 7.0,
}


def image_seed(scene_id):
    """Deterministic, positive 31-bit seed derived from the stable scene id."""
    digest = hashlib.sha256(str(scene_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def image_provenance(run, scene_number, prompt, seed=None):
    """Snapshot what we actually control, without claiming engine telemetry."""
    references = characters(run.get("storyboard") or {})
    canonical = json.dumps(references, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return {"contract_version": "private-image-v2", "provider": "sd.cpp-compatible",
            "parameters": dict(IMAGE_PARAMETERS),
            "sample_parameters": dict(IMAGE_SAMPLE_PARAMETERS),
            "model": None, "seed": seed,
            "model_seed_reason": ("seed_and_sampling_controlled_by_request"
                                  if seed is not None
                                  else "not_reported_by_image_contract"),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "character_reference_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "character_references": references, "scene_number": scene_number,
            "gpu_verified": False, "vram_peak_bytes": None}

class ImagePromptTooLong(ValueError):
    """A valid storyboard can still exceed the renderer's prompt budget."""

def characters(board):
    """Merge optional Qwen portraits with names used in each scene."""
    entries = {}
    for profile in board.get("cast") or []:
        name = profile["name"].strip()
        key = name.casefold()
        if key not in entries:
            entries[key] = {"name": name, "appearance": profile["appearance"],
                            "personality": profile["personality"], "role": profile["role"],
                            "first_scene": None, "scenes": []}
    for index, scene in enumerate(board.get("scenes", []), 1):
        for raw in scene.get("characters", []):
            name = raw.strip()
            key = name.casefold()
            if key not in entries:
                entries[key] = {"name": name, "appearance": None,
                                "personality": None, "role": None,
                                "first_scene": index, "scenes": []}
            person = entries[key]
            if person["first_scene"] is None:
                person["first_scene"] = index
            if index not in person["scenes"]:
                person["scenes"].append(index)
    return list(entries.values())

def image_prompt(run, scene_number):
    board = run.get("storyboard") or {}
    scenes = board.get("scenes") or []
    if scene_number < 1 or scene_number > len(scenes):
        raise ValueError("invalid_scene_number")
    scene = scenes[scene_number - 1]
    names = ", ".join(scene.get("characters", [])) or "aucun"
    palette = ", ".join(scene.get("colors", []))
    portraits = [
        f"{person['name']} : {person['appearance']}"
        for person in characters(board)
        if person.get("appearance") and any(
            person["name"].casefold() == name.strip().casefold()
            for name in scene.get("characters", [])
        )
    ]
    prompt = (
        "Illustration cinématique cohérente pour une légende bretonne. "
        "Aucune inscription ni texte dans l'image. "
        f"Scène {scene_number} : {scene['title']}. "
        f"Sujet : {scene['visual_description']}. "
        f"Personnages : {names}. "
        f"Repères visuels permanents : {'; '.join(portraits) or 'non définis'}. "
        f"Paysage : {scene['landscape']}. "
        f"Palette : {palette}. "
        f"Cadrage : {scene['shot']}. "
        f"Ambiance : {scene['emotion']}. "
        f"Description artistique : {scene['image_prompt']}."
    )
    if len(prompt) > 14000:
        raise ImagePromptTooLong("image_prompt_too_long")
    return prompt

def validate_png(data):
    """Bound bytes and dimensions before writing user-controlled media."""
    if not isinstance(data, bytes) or len(data) < 45 or len(data) > MAX_PNG_BYTES:
        raise ImageUnavailable()
    if data[:8] != PNG_MAGIC or data[12:16] != b"IHDR" or data[8:12] != b"\x00\x00\x00\r":
        raise ImageUnavailable()
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1 or width > 2048 or height > 2048:
        raise ImageUnavailable()
    return width, height

def private_image_url(value):
    """Only local/private image engines are allowed to receive story prompts."""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path.strip("/")):
            return False
        host = parsed.hostname
        if host == "localhost":
            return True
        address = ipaddress.ip_address(host)
        # Explicit loopback/RFC1918/IPv6 ULA allowlist. ipaddress.is_private
        # also includes link-local metadata IPs (169.254.169.254): never
        # allow a prompt to flow to an infrastructure metadata endpoint.
        allowed = (
            "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
            "192.168.0.0/16", "::1/128", "fc00::/7",
        )
        return any(address in ipaddress.ip_network(net) for net in allowed)
    except ValueError:
        return False
