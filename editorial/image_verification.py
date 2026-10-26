"""Read-only media checks; technical integrity never proves GPU or artistry."""
import hashlib
import math
import struct
import zlib

from editorial.media_rules import ImageUnavailable, validate_png


def check_png_integrity(png):
    """Check chunks, CRCs and bounded scanlines for non-interlaced PNGs."""
    width, height = validate_png(png)
    offset, idat, ended = 8, bytearray(), False
    bit_depth, color, compression, filtering, interlace = png[24:29]
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
              4: {8, 16}, 6: {8, 16}}
    if (bit_depth not in depths.get(color, set()) or compression != 0
            or filtering != 0 or interlace != 0):
        raise ImageUnavailable()
    palette = False
    while offset + 12 <= len(png):
        length = struct.unpack(">I", png[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(png):
            raise ImageUnavailable()
        kind = png[offset + 4:offset + 8]
        body = png[offset + 8:end - 4]
        crc = struct.unpack(">I", png[end - 4:end])[0]
        if zlib.crc32(kind + body) != crc:
            raise ImageUnavailable()
        if kind == b"IDAT":
            idat.extend(body)
        elif kind == b"PLTE":
            palette = bool(length and length % 3 == 0 and length <= 768)
        elif kind == b"IHDR" and offset != 8:
            raise ImageUnavailable()
        elif kind == b"IEND":
            ended = length == 0 and end == len(png)
            break
        offset = end
    if not ended or not idat or (color == 3 and not palette):
        raise ImageUnavailable()
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = (width * channels * bit_depth + 7) // 8 + 1
    expected = stride * height
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(idat), expected + 1)
    except zlib.error:
        raise ImageUnavailable() from None
    if (len(raw) != expected or not decoder.eof or decoder.unused_data
            or decoder.unconsumed_tail or any(raw[i] > 4 for i in range(0, expected, stride))):
        raise ImageUnavailable()
    return width, height


def verify_scene(scene, png, audit_count):
    generation = scene.get("generation") or {}
    provenance = generation.get("provenance") or {}
    reasons = []
    if scene.get("image_status") != "ready":
        reasons.append("image_not_ready")
    if png is None:
        reasons.append("private_file_unavailable")
    else:
        try:
            dimensions = check_png_integrity(png)
            if dimensions != (512, 512):
                reasons.append("unexpected_dimensions")
            if dimensions != (generation.get("width"), generation.get("height")):
                reasons.append("dimension_metadata_mismatch")
        except ImageUnavailable:
            reasons.append("invalid_png")
        if hashlib.sha256(png).hexdigest() != generation.get("png_sha256"):
            reasons.append("image_digest_mismatch_or_missing")
        if len(png) != generation.get("byte_count"):
            reasons.append("byte_count_mismatch_or_missing")
    duration = generation.get("duration_seconds")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or duration < 0):
        reasons.append("duration_unavailable")
    if not provenance.get("character_reference_sha256"):
        reasons.append("character_reference_unavailable")
    if audit_count < 2:
        reasons.append("audit_outbox_incomplete")
    return {"scene_number": scene["scene_number"], "scene_id": scene["scene_id"],
            "passed": not reasons, "reasons": reasons,
            "audit_outbox_count": audit_count, "duration_seconds": duration}


def verification_report(plan, checks, expected_scenes):
    references = {(s.get("generation") or {}).get("provenance", {}).get(
        "character_reference_sha256") for s in plan["scenes"]
        if (s.get("generation") or {}).get("provenance")}
    reference_consistent = len(references) == 1 and None not in references
    count_matches = len(plan["scenes"]) == expected_scenes
    hashes = [(s.get("generation") or {}).get("png_sha256") for s in plan["scenes"]]
    duplicates = len([h for h in hashes if h]) != len({h for h in hashes if h})
    return {"run_id": plan["run_id"], "expected_scenes": expected_scenes,
            "scene_count_matches": count_matches, "approved": plan["approved"],
            "character_reference_consistent": reference_consistent,
            "duplicate_image_digests": duplicates,
            "technical_passed": bool(plan["approved"] and count_matches
                                     and reference_consistent and checks
                                     and all(c["passed"] for c in checks)),
            "scenes": checks, "gpu_verified": False, "vram_peak_bytes": None,
            "human_visual_review_required": True,
            "model_and_seed_verified": False}
