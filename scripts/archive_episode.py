"""Archive a local production folder in private MinIO and the audited DB."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from editorial.media_storage import put_file
from editorial.store import PostgresStore, RunConflict


def archive(directory, run_id):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("production_directory_invalid")
    tenant = UUID(os.environ["EDITORIAL_TENANT_ID"])
    actor = UUID(os.environ["EDITORIAL_ACTOR_ID"])
    run_id = UUID(str(run_id))
    store = PostgresStore(os.environ["PO_DATABASE_URL"])
    run = store.get(tenant, run_id)
    if run.get("status") != "approved" or run.get("storyboard_stale"):
        raise RunConflict()
    files = []
    for source in sorted(directory.iterdir()):
        name = source.name
        kind = ("image" if re.fullmatch(r"scene-[1-6]\.png", name) else
                {"voice.wav": "voice", "episode.mp4": "video", "production.json": "manifest",
                 "receipt.json": "manifest", "narration.srt": "subtitles"}.get(name))
        if kind:
            if source.is_symlink() or not source.is_file():
                raise ValueError("production_file_invalid")
            files.append((source, kind))
    if not files or not (directory / "episode.mp4").is_file():
        raise ValueError("production_export_required")
    # An existing journal means this operation may have uploaded data already.
    # Reconcile it instead of silently duplicating archives on replay.
    with (directory / "minio-archive.jsonl").open("x", encoding="utf-8") as journal:
        def event(data):
            journal.write(json.dumps(data, sort_keys=True) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
        for source, kind in files:
            asset_id = uuid4()
            event({"state": "started", "tenant": str(tenant), "run_id": str(run_id),
                   "asset_id": str(asset_id), "kind": kind, "file": source.name})
            reference = put_file(source, tenant, run_id, asset_id, kind)
            event({"state": "stored", "asset_id": str(asset_id), "storage": reference})
            # A failed DB acknowledgement preserves both the object and journal.
            store.record_media(tenant, actor, run_id, asset_id, reference)
            event({"state": "recorded", "asset_id": str(asset_id)})
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--run-id", type=UUID, required=True)
    args = parser.parse_args()
    try:
        count = archive(args.directory, args.run_id)
    except Exception:
        parser.exit(2, "Archivage interrompu : conserver les sources et réconcilier le journal privé avant reprise.\n")
    print(json.dumps({"archived": count, "local_sources_preserved": True}))
