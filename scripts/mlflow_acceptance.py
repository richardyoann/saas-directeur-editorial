"""Real, auditable MLflow acceptance for Arvor (12 checks, no simulation).

Run against the local private stack only:

    acceptance-venv/bin/python scripts/mlflow_acceptance.py \
        --env-file ~/.config/arvor-mlflow/client.env --json-out /tmp/report.json

Real calls: local Qwen (llama.cpp), local sd.cpp image server, real FFmpeg
export, real Piper voice. A missing external engine fails the check instead of
being replaced by a mock. Evidence contains hashes, counts and identifiers, never
prompts, responses, audio content or secrets.
"""
import argparse
import asyncio
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mlflow_healthcheck import load_env_file, wait_ready  # noqa: E402

RESULTS = []
MARKERS = []


def record(name, function, *, required=True, **kwargs):
    print("RUN  " + name, flush=True)
    started = time.monotonic()
    try:
        evidence = function(**kwargs) or {}
        entry = {"name": name, "passed": True, "evidence": evidence}
    except Exception as error:  # noqa: BLE001 - report category, keep going
        entry = {"name": name, "passed": False, "required": required,
                 "error": type(error).__name__, "detail": str(error)[:300]}
    entry["duration_seconds"] = round(time.monotonic() - started, 3)
    RESULTS.append(entry)
    print(("PASS " if entry["passed"] else "FAIL ") + name, flush=True)
    return entry


def systemctl(*arguments):
    return subprocess.run(["systemctl", "--user", *arguments], capture_output=True,
                          text=True, timeout=90)


def mlflow_client():
    import mlflow
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    return mlflow, mlflow.MlflowClient()


def experiment_id(client, name):
    experiment = client.get_experiment_by_name(name)
    return client.create_experiment(name) if experiment is None else experiment.experiment_id


def find_event(client, name, event_id):
    experiment = client.get_experiment_by_name(name)
    assert experiment is not None, "experiment_missing"
    runs = client.search_runs(
        [experiment.experiment_id],
        filter_string=f"tags.`arvor_event_id` = '{event_id}'", max_results=5)
    return runs


def write_basic_request(uri, path, payload, credentials=None):
    if not uri.startswith(("http://", "https://")):
        raise ValueError("http(s) MLflow URI required")
    request = urllib.request.Request(uri + path, method="POST",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    if credentials:
        import base64
        token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
        request.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def check_service():
    state = systemctl("is-active", "arvor-mlflow.service").stdout.strip()
    assert state == "active", f"service_state={state}"
    enabled = systemctl("is-enabled", "arvor-mlflow.service").stdout.strip()
    units = systemctl("show", "arvor-mlflow.service",
                      "-p", "MainPID", "-p", "MemoryCurrent").stdout
    return {"state": state, "enabled": enabled,
            "units": dict(line.split("=", 1) for line in units.splitlines() if "=" in line)}


def check_loopback():
    output = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True,
                            timeout=10).stdout
    lines = [line for line in output.splitlines()
             if "127.0.0.1:5000" in line or "0.0.0.0:5000" in line
             or "[::]:5000" in line or "*:5000" in line]
    assert any(line.split()[3].startswith("127.0.0.1:5000") for line in lines), "no_loopback_listener"
    assert not any(line.split()[3].startswith(("0.0.0.0:5000", "[::]:5000", "*:5000"))
                   for line in lines), "public_listener"
    return {"listeners": [line.split()[3] for line in lines]}


def check_auth():
    uri = os.environ["MLFLOW_TRACKING_URI"]
    payload = {"max_results": 1}
    anonymous = write_basic_request(uri, "/api/2.0/mlflow/experiments/search", payload)
    credentials = f"{os.environ['MLFLOW_TRACKING_USERNAME']}:{os.environ['MLFLOW_TRACKING_PASSWORD']}"
    authenticated = write_basic_request(uri, "/api/2.0/mlflow/experiments/search",
                                        payload, credentials)
    assert anonymous == 401, f"anonymous_status={anonymous}"
    assert authenticated == 200, f"authenticated_status={authenticated}"
    return {"anonymous": anonymous, "authenticated": authenticated}


def check_persistence():
    mlflow, client = mlflow_client()
    name = "arvor-acceptance"
    eid = experiment_id(client, name)
    run = client.create_run(eid, run_name="persistence")
    marker = "persist-" + secrets.token_hex(6)
    client.log_param(run.info.run_id, "persistence_marker", marker)
    stopped = systemctl("stop", "arvor-mlflow.service")
    assert stopped.returncode == 0, "stop_failed"
    started = systemctl("start", "arvor-mlflow.service")
    assert started.returncode == 0, "start_failed"
    assert wait_ready(os.environ["MLFLOW_TRACKING_URI"], 60, 5), "health_after_restart"
    persisted = client.get_run(run.info.run_id)
    value = persisted.data.params.get("persistence_marker")
    assert value == marker, "parameter_not_persisted"
    client.delete_run(run.info.run_id)
    return {"run_id": run.info.run_id, "restarted": True}


def check_postgres_access():
    import psycopg
    password = (Path.home() / ".local/state/arvor-mlflow/secrets/postgres_password"
                ).read_text(encoding="utf-8").strip()
    with psycopg.connect(host="127.0.0.1", port=5432, user="mlflow_app",
                         password=password, dbname="mlflow",
                         connect_timeout=10) as connection:
        current = connection.execute("SELECT current_user").fetchone()[0]
        can_connect = connection.execute(
            "SELECT has_database_privilege(current_user, 'editorial', 'CONNECT')"
        ).fetchone()[0]
    assert current == "mlflow_app", current
    assert can_connect is False, "business_database_privilege_granted"
    refused = False
    try:
        psycopg.connect(host="127.0.0.1", port=5432, user="mlflow_app",
                        password=password, dbname="editorial", connect_timeout=10)
    except psycopg.OperationalError:
        refused = True
    assert refused, "business_database_connect_allowed"
    return {"current_user": current, "business_connect_privilege": can_connect,
            "business_connection_refused": refused}


def check_comparison():
    import httpx
    from apps.api.llama_provider import generate_text
    from editorial.service import SYSTEM_PROMPT
    from infrastructure.observability import mlflow_tracker as tracker
    base_url = os.getenv("ARVOR_QWEN_BASE_URL", "http://172.31.48.1:8081")
    marker = "MARKER_COMPARE_" + secrets.token_hex(8)
    MARKERS.append(marker)
    prompt = f"Résume en une phrase une légende bretonne inventée. {marker}"
    runs = []
    async def generate(max_tokens):
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            return await generate_text(client, base_url, prompt, max_tokens,
                                       system_prompt=SYSTEM_PROMPT)
    for max_tokens in (128, 320):
        response = asyncio.run(generate(max_tokens))
        assert response["finish_reason"] == "stop"
        story_id = uuid.uuid4()
        tracker.record_scenario_step(
            tenant=uuid.uuid4(), story_id=story_id, step="analysis", prompt=prompt,
            response=response["response"], status="success",
            prompt_version="acceptance-comparison", workflow_version="acceptance",
            model=response["model"], usage=response.get("usage"),
            duration_seconds=response["duration_seconds"], max_tokens=max_tokens)
        runs.append((max_tokens, story_id, response))
    tracker.flush(20)
    mlflow, client = mlflow_client()
    identifiers = []
    for max_tokens, story_id, _ in runs:
        event = tracker.event_id(
            "scenario", f"{story_id}:analysis:{tracker.sha256_text(prompt)}")
        found = find_event(client, "arvor-scenario-generation", event)
        assert len(found) == 1, f"comparison_run_missing_{max_tokens}"
        identifiers.append(found[0])
    assert len({run.info.run_id for run in identifiers}) == 2
    first, second = identifiers
    return {"run_ids": [first.info.run_id, second.info.run_id],
            "max_tokens": [run.data.params["max_tokens"] for run in identifiers],
            "duration_seconds": [run.data.metrics["duration_seconds"] for run in identifiers],
            "completion_tokens": [run.data.metrics.get("completion_tokens") for run in identifiers],
            "same_prompt_sha256": len({run.data.tags["arvor_prompt_sha256"]
                                       for run in identifiers}) == 1,
            "compared": True}


def check_artifact():
    import boto3
    from botocore.config import Config
    mlflow, client = mlflow_client()
    eid = experiment_id(client, "arvor-acceptance")
    run = client.create_run(eid, run_name="artifact")
    payload = "arvor-artifact-" + secrets.token_hex(8)
    try:
        client.log_text(run.info.run_id, payload, "probe.txt")
        local = client.download_artifacts(run.info.run_id, "probe.txt")
        assert Path(local).read_text(encoding="utf-8") == payload, "artifact_roundtrip"
        server = server_environment()
        s3 = boto3.client(
            "s3", endpoint_url=server["MLFLOW_S3_ENDPOINT_URL"],
            aws_access_key_id=server["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=server["AWS_SECRET_ACCESS_KEY"],
            region_name="us-east-1", verify=server["AWS_CA_BUNDLE"],
            config=Config(signature_version="s3v4", retries={"max_attempts": 1}))
        keys = [item["Key"] for item in s3.list_objects_v2(
            Bucket="mlflow-artifacts", Prefix=f"{eid}/").get("Contents", [])
                if run.info.run_id in item["Key"]]
        assert keys, "artifact_absent_from_minio"
        business_denied = False
        try:
            s3.list_objects_v2(Bucket="editorial-artifacts", MaxKeys=1)
        except Exception:
            business_denied = True
        assert business_denied, "business_bucket_reachable"
    finally:
        client.delete_run(run.info.run_id)
    return {"run_id": run.info.run_id, "objects": len(keys),
            "business_bucket_denied": business_denied}


def server_environment():
    values = {}
    for line in Path.home().joinpath(".config/arvor-mlflow/mlflow.env").read_text(
            encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def check_qwen():
    import httpx
    from apps.api.llama_provider import generate_text
    from editorial.service import SYSTEM_PROMPT
    from infrastructure.observability import mlflow_tracker as tracker
    base_url = os.getenv("ARVOR_QWEN_BASE_URL", "http://172.31.48.1:8081")
    marker = "MARKER_QWEN_" + secrets.token_hex(8)
    MARKERS.append(marker)
    prompt = ("Écris deux phrases de fiction inspirées d'une légende bretonne. "
              f"Ne présente aucun fait comme vérifié. {marker}")
    async def generate():
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            return await generate_text(client, base_url, prompt, 512,
                                       system_prompt=SYSTEM_PROMPT)
    response = asyncio.run(generate())
    assert response["finish_reason"] == "stop", "qwen_incomplete"
    assert response["response"].strip(), "qwen_empty"
    tenant, story_id = uuid.uuid4(), uuid.uuid4()
    tracker.record_scenario_step(
        tenant=tenant, story_id=story_id, step="analysis", prompt=prompt,
        response=response["response"], status="success",
        prompt_version="acceptance", workflow_version="acceptance",
        model=response["model"], usage=response.get("usage"),
        duration_seconds=response["duration_seconds"], max_tokens=512)
    tracker.flush(15)
    expected_event = tracker.event_id(
        "scenario", f"{story_id}:analysis:{tracker.sha256_text(prompt)}")
    mlflow, client = mlflow_client()
    runs = find_event(client, "arvor-scenario-generation", expected_event)
    assert runs, "scenario_run_missing"
    run = runs[0]
    assert run.data.metrics.get("duration_seconds", 0) > 0, "duration_missing"
    assert run.data.tags["arvor_status"] == "success", "status_not_success"
    assert run.data.tags["arvor_prompt_sha256"] == tracker.sha256_text(prompt)
    trace_id = run.data.tags.get("arvor_trace_id")
    assert trace_id, "trace_id_missing"
    trace = client.get_trace(trace_id)
    span_names = [span.name for span in trace.data.spans]
    assert "arvor.scenario.analysis" in span_names, "scenario_span_missing"
    assert trace.info.status == "OK", "trace_status"
    return {"run_id": run.info.run_id, "trace_id": trace_id,
            "model": run.data.params.get("model"),
            "duration_seconds": run.data.metrics.get("duration_seconds"),
            "total_tokens": run.data.metrics.get("total_tokens"),
            "response_chars": run.data.metrics.get("output_chars"),
            "spans": span_names}


def check_image():
    import httpx
    from infrastructure.images.sdcpp import render_png
    from editorial.media_rules import validate_png
    from infrastructure.observability import mlflow_tracker as tracker
    base_url = os.getenv("ARVOR_IMAGE_BASE_URL", "http://172.31.48.1:8082")
    marker = "MARKER_IMAGE_" + secrets.token_hex(8)
    MARKERS.append(marker)
    prompt = ("Illustration cinématique d'un rivage breton sous la brume, "
              f"aucune inscription, {marker}")
    async def render():
        async with httpx.AsyncClient(timeout=httpx.Timeout(420.0, connect=5.0)) as client:
            started = time.monotonic()
            png = await render_png(client, base_url, prompt)
            return png, round(time.monotonic() - started, 3)
    png, duration = asyncio.run(render())
    width, height = validate_png(png)
    import hashlib
    sha = hashlib.sha256(png).hexdigest()
    story_id, scene_id = uuid.uuid4(), uuid.uuid4()
    tracker.record_image(tenant=uuid.uuid4(), story_id=story_id, scene_id=scene_id,
                         prompt=prompt, status="ready", model="sd.cpp-compatible",
                         width=width, height=height, duration_seconds=duration,
                         png_sha256=sha, byte_count=len(png), resolution="512x512")
    tracker.flush(15)
    mlflow, client = mlflow_client()
    runs = client.search_runs(
        [experiment_id(client, "arvor-image-generation")],
        filter_string=f"tags.`arvor_scene_id` = '{scene_id}'", max_results=5)
    assert runs, "image_run_missing"
    run = runs[0]
    assert run.data.metrics["width"] == width
    assert run.data.metrics["height"] == height
    assert run.data.tags["arvor_png_sha256"] == sha
    assert run.data.tags.get("arvor_trace_id"), "image_trace_missing"
    return {"run_id": run.info.run_id, "scene_id": str(scene_id),
            "width": width, "height": height, "byte_count": len(png),
            "duration_seconds": duration, "png_sha256": sha,
            "image_path": str(write_media(png))}


def write_media(png):
    directory = Path("/tmp/opencode/mlflow-acceptance-media")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "scene.png"
    path.write_bytes(png)
    os.chmod(path, 0o600)
    return path


def check_video(image_path, voice_path=None):
    from infrastructure.observability import mlflow_tracker as tracker
    from scripts.render_episode import render
    root = Path("/tmp/opencode/mlflow-acceptance-video")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700)
    shutil.copyfile(image_path, root / "scene.png")
    story_id = uuid.uuid4()
    manifest = root / "production.json"
    document = {
        "schema_version": 1, "approved": True,
        "preproduction": {"run_id": str(story_id)},
        "scenes": [{"image": "scene.png", "duration_seconds": 25,
                    "narration": f"Scène {index} d'un rivage breton."}
                   for index in (1, 2, 3)],
    }
    if voice_path is not None:
        shutil.copyfile(voice_path, root / "voice.wav")
        document["voice"] = "voice.wav"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    started = time.monotonic()
    receipt = render(manifest, root / "export", arvor_75=True)
    elapsed = round(time.monotonic() - started, 3)
    assert receipt["duration_seconds"] == 75
    assert receipt["audio"] is (voice_path is not None)
    tracker.flush(15)
    mlflow, client = mlflow_client()
    runs = client.search_runs(
        [experiment_id(client, "arvor-video-generation")],
        filter_string=f"tags.`arvor_story_id` = '{story_id}'", max_results=5)
    assert runs, "video_run_missing"
    run = runs[0]
    assert run.data.metrics["real_seconds"] == 75
    assert run.data.tags["arvor_video_sha256"] == receipt["video_sha256"]
    voice_run = None
    if voice_path is not None:
        assert receipt.get("voice_sha256"), "voice_sha_missing"
        voice_runs = client.search_runs(
            [experiment_id(client, "arvor-voice-generation")],
            filter_string=("tags.`arvor_audio_sha256` = "
                           f"'{receipt['voice_sha256']}' and "
                           "params.engine = 'external-wav'"), max_results=5)
        assert voice_runs, "external_wav_voice_track_missing_for_export"
        voice_run = voice_runs[0].info.run_id
    return {"run_id": run.info.run_id, "story_id": str(story_id),
            "duration_seconds": receipt["duration_seconds"], "render_seconds": elapsed,
            "video_sha256": receipt["video_sha256"],
            "video_bytes": (root / "export/episode.mp4").stat().st_size,
            "audio": receipt["audio"], "voice_run_id": voice_run,
            "ffmpeg_version": receipt["ffmpeg_version"],
            "export_dir": str(root / "export")}


def check_voice():
    from infrastructure.observability import mlflow_tracker as tracker
    from production.voice_timeline import synthesize_voice
    piper = os.getenv("ARVOR_PIPER", str(Path.home() / ".local/state/arvor-mlflow/piper/piper"))
    model = os.getenv("ARVOR_PIPER_MODEL",
                      str(Path.home() / ".local/share/arvor/voices/fr_FR-siwis-medium.onnx"))
    assert Path(piper).is_file(), "piper_missing"
    assert Path(model).is_file(), "piper_model_missing"
    root = Path("/tmp/opencode/mlflow-acceptance-voice")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700)
    story_id = uuid.uuid4()
    scenes = [{"duration_seconds": 25,
               "narration": f"Voix de recette Arvor, scène {index}, légende bretonne."}
              for index in (1, 2, 3)]
    MARKERS.append("Voix de recette Arvor")
    started = time.monotonic()
    result = synthesize_voice(scenes, model, root / "voice.wav", piper=piper,
                              tenant=uuid.uuid4(), story_id=story_id)
    elapsed = round(time.monotonic() - started, 3)
    assert result["duration_seconds"] == 75
    assert Path(root / "voice.wav").is_file()
    tracker.flush(15)
    mlflow, client = mlflow_client()
    runs = client.search_runs(
        [experiment_id(client, "arvor-voice-generation")],
        filter_string=f"tags.`arvor_story_id` = '{story_id}'", max_results=5)
    assert runs, "voice_run_missing"
    run = runs[0]
    assert run.data.tags["arvor_audio_sha256"] == result["voice_sha256"]
    assert run.data.params["engine"] == "piper"
    return {"run_id": run.info.run_id, "story_id": str(story_id),
            "audio_seconds": result["duration_seconds"], "wall_seconds": elapsed,
            "audio_sha256": result["voice_sha256"],
            "voice_bytes": (root / "voice.wav").stat().st_size,
            "model": Path(model).name, "voice_path": str(root / "voice.wav")}


def check_failure_isolation():
    from infrastructure.observability import mlflow_tracker as tracker
    mlflow, client = mlflow_client()
    story_id, scene_id = uuid.uuid4(), uuid.uuid4()
    event = tracker.image_event(
        tenant=uuid.uuid4(), story_id=story_id, scene_id=scene_id,
        prompt="isolation", status="ready", png_sha256="d" * 64,
        width=512, height=512, duration_seconds=1.0)
    # Warm up the daemon thread and the lazy MLflow import while healthy, so
    # the outage window measures publication failure, not import latency.
    warmup = tracker.image_event(
        tenant=uuid.uuid4(), story_id=uuid.uuid4(), scene_id=uuid.uuid4(),
        prompt="warmup", status="ready", png_sha256="c" * 64,
        width=512, height=512, duration_seconds=1.0)
    assert tracker.record(warmup) == "queued"
    tracker.flush(60)
    assert tracker.stats().get("published", 0) >= 1, "warmup_not_published"
    stopped = systemctl("stop", "arvor-mlflow.service")
    assert stopped.returncode == 0
    time.sleep(1)
    started = time.monotonic()
    accepted = tracker.record(event)
    submit_seconds = round(time.monotonic() - started, 4)
    assert accepted in {"queued", "spooled"}, accepted
    spool = Path(os.environ.get("ARVOR_MLFLOW_SPOOL", ""))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not (spool.exists() and spool.stat().st_size):
        time.sleep(0.2)
    spooled = spool.exists() and spool.stat().st_size > 0
    started = systemctl("start", "arvor-mlflow.service")
    assert started.returncode == 0
    assert wait_ready(os.environ["MLFLOW_TRACKING_URI"], 60, 5), "restart_failed"
    report = tracker.flush_spool(30)
    runs = find_event(client, "arvor-image-generation", event["event_id"])
    assert len(runs) == 1, f"duplicate_or_missing_runs={len(runs)}"
    return {"submit_seconds": submit_seconds, "spooled": spooled,
            "flush": report, "runs": len(runs), "event_id": event["event_id"]}


def check_redaction():
    secrets_values = []
    state = Path.home() / ".local/state/arvor-mlflow/secrets"
    for name in ("postgres_password", "minio_secret_key", "basic_auth_password",
                 "secret_key"):
        secrets_values.append((name, (state / name).read_text(encoding="utf-8").strip()))
    matches = scan_database(MARKERS + [value for _, value in secrets_values])
    artifact_matches = scan_artifacts(MARKERS)
    assert matches == 0, f"database_matches={matches}"
    assert artifact_matches == 0, f"artifact_matches={artifact_matches}"
    return {"markers": len(MARKERS), "secrets": len(secrets_values),
            "database_matches": matches, "artifact_matches": artifact_matches}


def scan_database(needles):
    import psycopg
    from psycopg import sql
    password = (Path.home() / ".local/state/arvor-mlflow/secrets/postgres_password"
                ).read_text(encoding="utf-8").strip()
    matches = 0
    with psycopg.connect(host="127.0.0.1", port=5432, user="mlflow_app",
                         password=password, dbname="mlflow") as connection:
        columns = connection.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND data_type IN "
            "('text','character varying','character','json','jsonb')").fetchall()
        for table, column in columns:
            for needle in needles:
                if not needle:
                    continue
                query = sql.SQL("SELECT COUNT(*) FROM {} WHERE CAST({} AS TEXT) LIKE %s"
                                ).format(sql.Identifier(table), sql.Identifier(column))
                count = connection.execute(query, (f"%{needle}%",)).fetchone()[0]
                matches += int(count)
    return matches


def scan_artifacts(needles):
    import boto3
    from botocore.config import Config
    server = server_environment()
    s3 = boto3.client(
        "s3", endpoint_url=server["MLFLOW_S3_ENDPOINT_URL"],
        aws_access_key_id=server["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=server["AWS_SECRET_ACCESS_KEY"],
        region_name="us-east-1", verify=server["AWS_CA_BUNDLE"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 1}))
    matches = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket="mlflow-artifacts"):
        for item in page.get("Contents", []):
            if item["Size"] > 5 * 1024 * 1024:
                continue
            body = s3.get_object(Bucket="mlflow-artifacts", Key=item["Key"])["Body"].read()
            text = body.decode("utf-8", "ignore")
            matches += sum(1 for needle in needles if needle and needle in text)
    return matches


def check_retention():
    import psycopg
    server = server_environment()
    password = (Path.home() / ".local/state/arvor-mlflow/secrets/postgres_password"
                ).read_text(encoding="utf-8").strip()
    with psycopg.connect(host="127.0.0.1", port=5432, user="mlflow_app",
                         password=password, dbname="mlflow") as connection:
        size = connection.execute("SELECT pg_database_size('mlflow')").fetchone()[0]
        experiments = connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=server["MLFLOW_S3_ENDPOINT_URL"],
        aws_access_key_id=server["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=server["AWS_SECRET_ACCESS_KEY"],
        region_name="us-east-1", verify=server["AWS_CA_BUNDLE"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 1}))
    objects = 0
    artifact_bytes = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket="mlflow-artifacts"):
        for item in page.get("Contents", []):
            objects += 1
            artifact_bytes += item["Size"]
    memory_text = systemctl("show", "arvor-mlflow.service", "-p", "MemoryCurrent"
                            ).stdout.split("=", 1)[-1].strip()
    memory = int(memory_text) if memory_text.isdigit() else 0
    if memory >= 2 ** 63 - 4096:  # systemd "infinity" sentinel
        memory = 0
    assert size < 1024 ** 3, "database_growth"
    assert artifact_bytes < 1024 ** 3, "artifact_growth"
    assert memory < 3 * 1024 ** 3, "memory_growth"
    return {"database_bytes": size, "experiments": experiments,
            "artifact_objects": objects, "artifact_bytes": artifact_bytes,
            "memory_bytes": memory,
            "policy": "manual retention; no automatic deletion of business evidence"}


def check_business_untouched():
    server = server_environment()
    import boto3
    from botocore.config import Config
    root_user = Path.home().joinpath(
        "saas-directeur-editorial/.security-secrets/minio_root_user")
    root_password = Path.home().joinpath(
        "saas-directeur-editorial/.security-secrets/minio_root_password")
    assert root_user.is_file() and root_password.is_file()
    s3 = boto3.client(
        "s3", endpoint_url=server["MLFLOW_S3_ENDPOINT_URL"],
        aws_access_key_id=root_user.read_text(encoding="utf-8").strip(),
        aws_secret_access_key=root_password.read_text(encoding="utf-8").strip(),
        region_name="us-east-1", verify=server["AWS_CA_BUNDLE"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 1}))
    buckets = sorted(bucket["Name"] for bucket in s3.list_buckets()["Buckets"])
    assert "editorial-artifacts" in buckets and "mlflow-artifacts" in buckets
    business_objects = sum(page.get("KeyCount", 0) for page in
                           s3.get_paginator("list_objects_v2").paginate(
                               Bucket="editorial-artifacts"))
    return {"buckets": buckets, "business_objects": business_objects}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path,
                        default=Path.home() / ".config/arvor-mlflow/client.env")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--sha", default=None)
    parser.add_argument("--only", default="",
                        help="Comma-separated check names, for diagnosis only")
    args = parser.parse_args(argv)
    if args.env_file:
        os.environ.update(load_env_file(args.env_file))
    os.environ.setdefault("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    # Presigned MinIO downloads happen in this process: trust only the private CA.
    server = server_environment()
    if server.get("AWS_CA_BUNDLE"):
        os.environ.setdefault("AWS_CA_BUNDLE", server["AWS_CA_BUNDLE"])
        os.environ.setdefault("REQUESTS_CA_BUNDLE", server["AWS_CA_BUNDLE"])
    sha = args.sha or os.getenv("ARVOR_CODE_VERSION") or "unknown"
    os.environ["ARVOR_CODE_VERSION"] = sha
    report = {"sha": sha, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "python": platform.python_version(), "checks": []}
    selected = {item.strip() for item in args.only.split(",") if item.strip()}

    def run(name, function, **kwargs):
        if selected and name not in selected:
            return None
        return record(name, function, **kwargs)

    run("service_active_and_enabled", check_service)
    run("loopback_only", check_loopback)
    run("authentication_required", check_auth)
    run("postgres_access_and_business_isolation", check_postgres_access)
    run("postgres_persistence_across_restart", check_persistence)
    run("minio_artifact_roundtrip_and_isolation", check_artifact)
    run("real_qwen_generation_tracked", check_qwen)
    run("two_runs_comparable", check_comparison)
    image = run("real_image_generation_tracked", check_image)
    voice = run("real_piper_voice_tracked", check_voice)
    voice_path = (Path(voice["evidence"]["voice_path"])
                  if voice and voice["passed"] else None)
    if image and image["passed"]:
        run("real_video_75s_tracked", check_video,
            image_path=Path(image["evidence"]["image_path"]),
            voice_path=voice_path)
    elif not selected or "real_video_75s_tracked" in selected:
        RESULTS.append({"name": "real_video_75s_tracked", "passed": False,
                        "error": "image_prerequisite_failed", "required": True})
    run("mlflow_outage_isolation_and_no_duplicates", check_failure_isolation)
    run("no_content_or_secret_in_traces_or_artifacts", check_redaction)
    run("retention_and_footprint_bounded", check_retention)
    run("business_bucket_untouched", check_business_untouched)
    report["checks"] = RESULTS
    report["passed"] = all(item["passed"] for item in RESULTS)
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.chmod(args.json_out, 0o600)
    print(json.dumps({"passed": report["passed"],
                      "checks": len(RESULTS),
                      "failed": [item["name"] for item in RESULTS if not item["passed"]]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
