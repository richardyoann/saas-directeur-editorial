"""Restore archived media to a new private local working directory."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editorial.media_storage import get_file


def restore(journal, destination, tenant, run_id):
    journal, destination = Path(journal), Path(destination)
    if journal.stat().st_size > 1024 * 1024:
        raise ValueError("journal_too_large")
    started, stored = {}, {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        asset_id = UUID(item["asset_id"])
        if item["state"] == "started":
            if (item["tenant"] != str(tenant) or item["run_id"] != str(run_id)
                    or not re.fullmatch(r"scene-[1-6]\.png|voice\.wav|episode\.mp4|production\.json|receipt\.json|narration\.srt", item["file"])
                    or asset_id in started):
                raise ValueError("journal_invalid")
            started[asset_id] = item
        elif item["state"] == "stored":
            if asset_id in stored:
                raise ValueError("journal_invalid")
            stored[asset_id] = item["storage"]
        elif item["state"] != "recorded":
            raise ValueError("journal_invalid")
    if not started or set(started) != set(stored) or len({item["file"] for item in started.values()}) != len(started):
        raise ValueError("archive_incomplete_reconciliation_required")
    destination.mkdir(mode=0o700)
    try:
        for asset_id, item in started.items():
            get_file(stored[asset_id], destination / item["file"], tenant, run_id,
                     asset_id, item["kind"])
    except Exception:
        shutil.rmtree(destination)
        raise
    return len(started)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--run-id", type=UUID, required=True)
    args = parser.parse_args()
    try:
        count = restore(args.journal, args.destination, UUID(os.environ["EDITORIAL_TENANT_ID"]), args.run_id)
    except Exception:
        parser.exit(2, "Restauration impossible : contrôler le journal privé, la destination et MinIO.\n")
    print(json.dumps({"restored": count}))
