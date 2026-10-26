"""Render a reviewed offline preproduction bundle with existing local PNG/WAV."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production.episode_pipeline import render_production


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("media_directory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--confirm-human-review", action="store_true",
                        help="Declare manual review of these exact offline snapshots and assets")
    args = parser.parse_args()
    try:
        report = render_production(args.bundle, args.media_directory, args.destination,
                                   human_review_confirmed=args.confirm_human_review)
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        parser.exit(2, "Rendu refusé ou interrompu : vérifier les snapshots, la relecture, les médias et FFmpeg.\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["technical_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
