"""Generate a private 75-second voice.wav for a reviewed preproduction bundle.

Requires a locally installed Piper CLI and French .onnx voice; installs nothing.
No PostgreSQL, MinIO, internet call, media overwrite, or publication.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api.llama_provider import strict_json
from production.episode_pipeline import _private_directory, prepare_manifest
from production.voice_timeline import synthesize_voice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Private approved run+crew+media snapshot")
    parser.add_argument("media_directory", type=Path, help="Existing private media directory")
    parser.add_argument("--model", type=Path, required=True, help="Existing Piper French .onnx model")
    parser.add_argument("--piper", default="piper", help="Path to existing Piper executable")
    parser.add_argument("--confirm-human-review", action="store_true")
    args = parser.parse_args()
    try:
        bundle_path = args.bundle
        if (bundle_path.is_symlink() or not bundle_path.is_file()
                or bundle_path.stat().st_size > 512000):
            raise ValueError("production_bundle_file_invalid")
        bundle = strict_json(bundle_path.read_bytes())
        manifest = prepare_manifest(bundle, human_review_confirmed=args.confirm_human_review)
        media_root = _private_directory(args.media_directory)
        name = manifest["voice"]
        if (Path(name).name != name or Path(name).suffix.lower() != ".wav"
                or name in (".", "..")):
            raise ValueError("voice_asset_path_invalid")
        result = synthesize_voice(manifest["scenes"], args.model, media_root / name,
                                  piper=args.piper)
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        parser.exit(2, "Voix refusée : vérifier scénario approuvé, Piper local, modèle français et durées.\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
