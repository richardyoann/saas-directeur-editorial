"""Read-only technical review of an already exported private 75s Arvor episode."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production.media_qc import inspect_export


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_directory", type=Path,
                        help="Private folder containing episode.mp4, receipt.json, narration.srt")
    report = inspect_export(parser.parse_args().export_directory)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["technical_passed"] else 2)
