"""Idempotent local provisioning of the private Arvor MLflow stack.

Creates, without touching business data:
  * a dedicated PostgreSQL role and database (``mlflow_app`` / ``mlflow``);
  * a dedicated MinIO bucket and least-privilege user (``mlflow-artifacts``);
  * local secret files (0600) and the two configuration files used by systemd.

The script prints only resource names and booleans. It never prints a secret.
Existing business databases, buckets and volumes are only read for isolation
checks. Re-running it converges to the same resources.
"""
import argparse
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def secret_file(path, generator, length=48):
    path = Path(path)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = generator(length)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    return value


def write_private(path, content):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, path)


def provision_postgres(admin_password, host, port, admin_user, admin_db, role, database, password):
    import psycopg
    from psycopg import sql

    with psycopg.connect(host=host, port=port, user=admin_user,
                         password=admin_password, dbname=admin_db,
                         connect_timeout=10, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
        if exists:
            connection.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)))
        else:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT").format(
                    sql.Identifier(role), sql.Literal(password)))
        if not connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(role)))
        # Explicit isolation from business databases; additive ACLs stay intact.
        for business in ("editorial", "postgres"):
            try:
                connection.execute(
                    sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                        sql.Identifier(business), sql.Identifier(role)))
            except psycopg.Error:
                pass
    with psycopg.connect(host=host, port=port, user=role, password=password,
                         dbname=database, connect_timeout=10) as connection:
        assert connection.execute("SELECT current_user").fetchone()[0] == role


def run_mc(mc, host_url, *arguments, check=True):
    environment = dict(os.environ)
    environment["MC_HOST_arvor_provision"] = host_url
    result = subprocess.run(
        [str(mc), "--no-color", *arguments],
        capture_output=True, text=True, timeout=120, env=environment)
    if check and result.returncode != 0:
        raise RuntimeError(f"mc_failed:{arguments[0]}:{result.returncode}")
    return result


def provision_minio(mc, endpoint, root_user, root_password, bucket, access_key,
                    secret_key, policy_name):
    if not Path(mc).is_file():
        raise RuntimeError("mc_missing")
    host_url = (f"{endpoint.split('://')[0]}://{quote(root_user, safe='')}:"
                f"{quote(root_password, safe='')}@"
                f"{endpoint.split('://', 1)[1].split('@')[-1]}")
    run_mc(mc, host_url, "mb", "--ignore-existing", f"arvor_provision/{bucket}")
    run_mc(mc, host_url, "admin", "user", "add", "arvor_provision", access_key, secret_key)
    policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Action": ["s3:GetBucketLocation", "s3:ListBucket",
                        "s3:ListBucketMultipartUploads"],
             "Resource": [f"arn:aws:s3:::{bucket}"]},
            {"Effect": "Allow",
             "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject",
                        "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
             "Resource": [f"arn:aws:s3:::{bucket}/*"]},
        ],
    }, indent=2)
    with tempfile.TemporaryDirectory(prefix="arvor-mlflow-policy-") as temporary:
        policy_file = Path(temporary) / "policy.json"
        policy_file.write_text(policy, encoding="utf-8")
        created = run_mc(mc, host_url, "admin", "policy", "info", "arvor_provision",
                         policy_name, check=False)
        if created.returncode != 0:
            run_mc(mc, host_url, "admin", "policy", "create", "arvor_provision",
                   policy_name, str(policy_file))
    run_mc(mc, host_url, "admin", "policy", "attach", "arvor_provision",
           policy_name, "--user", access_key)
    listing = run_mc(mc, host_url, "ls", f"arvor_provision/{bucket}", check=False)
    if listing.returncode != 0:
        raise RuntimeError("bucket_unreadable")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path,
                        default=Path.home() / ".local/state/arvor-mlflow")
    parser.add_argument("--config-dir", type=Path,
                        default=Path.home() / ".config/arvor-mlflow")
    parser.add_argument("--pg-admin-password-file", type=Path, required=True)
    parser.add_argument("--pg-host", default="127.0.0.1")
    parser.add_argument("--pg-port", type=int, default=5432)
    parser.add_argument("--pg-admin-user", default="editorial")
    parser.add_argument("--pg-admin-db", default="editorial")
    parser.add_argument("--minio-root-user-file", type=Path, required=True)
    parser.add_argument("--minio-root-password-file", type=Path, required=True)
    parser.add_argument("--minio-endpoint", default="https://127.0.0.1:9000")
    parser.add_argument("--minio-ca", type=Path, required=True)
    parser.add_argument("--mc", type=Path, default=Path.home() / ".local/bin/mc")
    parser.add_argument("--force-secrets", action="store_true",
                        help="Rotate local secrets (updates DB role and MinIO user)")
    args = parser.parse_args(argv)
    if args.force_secrets:
        for name in ("postgres_password", "minio_access_key", "minio_secret_key",
                     "basic_auth_password", "secret_key"):
            (args.state_dir / "secrets" / name).unlink(missing_ok=True)
    secrets_directory = args.state_dir / "secrets"
    secrets_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    alphabet = string.ascii_lowercase + string.digits
    pg_password = secret_file(secrets_directory / "postgres_password",
                              lambda n: secrets.token_urlsafe(n))
    access_key = secret_file(
        secrets_directory / "minio_access_key",
        lambda n: "mlflow" + "".join(secrets.choice(alphabet) for _ in range(14)))
    secret_key = secret_file(secrets_directory / "minio_secret_key",
                             lambda n: secrets.token_urlsafe(40))
    auth_password = secret_file(secrets_directory / "basic_auth_password",
                                lambda n: secrets.token_urlsafe(32))
    flask_key = secret_file(secrets_directory / "secret_key",
                            lambda n: secrets.token_hex(32))
    admin_password = args.pg_admin_password_file.read_text(encoding="utf-8").strip()
    root_user = args.minio_root_user_file.read_text(encoding="utf-8").strip()
    root_password = args.minio_root_password_file.read_text(encoding="utf-8").strip()
    provision_postgres(admin_password, args.pg_host, args.pg_port,
                       args.pg_admin_user, args.pg_admin_db,
                       "mlflow_app", "mlflow", pg_password)
    provision_minio(args.mc, args.minio_endpoint, root_user, root_password,
                    "mlflow-artifacts", access_key, secret_key,
                    "mlflow-artifacts-rw")
    backend = (f"postgresql+psycopg://mlflow_app:{quote(pg_password, safe='')}@"
               f"{args.pg_host}:{args.pg_port}/mlflow")
    write_private(args.config_dir / "basic_auth.ini", (
        "[mlflow]\n"
        "default_permission = READ\n"
        f"database_uri = {backend}\n"
        "admin_username = arvor-admin\n"
        f"admin_password = {auth_password}\n"
    ))
    write_private(args.config_dir / "mlflow.env", "\n".join([
        f"MLFLOW_BACKEND_STORE_URI={backend}",
        "MLFLOW_ARTIFACTS_DESTINATION=s3://mlflow-artifacts",
        f"MLFLOW_S3_ENDPOINT_URL={args.minio_endpoint}",
        f"AWS_ACCESS_KEY_ID={access_key}",
        f"AWS_SECRET_ACCESS_KEY={secret_key}",
        f"AWS_CA_BUNDLE={args.minio_ca.resolve()}",
        "AWS_DEFAULT_REGION=us-east-1",
        f"MLFLOW_AUTH_CONFIG_PATH={(args.config_dir / 'basic_auth.ini').resolve()}",
        f"MLFLOW_FLASK_SERVER_SECRET_KEY={flask_key}",
        "MLFLOW_SERVER_ALLOWED_HOSTS=127.0.0.1:5000,localhost:5000",
        "MLFLOW_DISABLE_AGENT_HINT=1",
        "MLFLOW_HTTP_REQUEST_TIMEOUT=3",
        "",
    ]))
    write_private(args.config_dir / "client.env", "\n".join([
        "ARVOR_MLFLOW_ENABLED=true",
        "MLFLOW_TRACKING_URI=http://127.0.0.1:5000",
        "MLFLOW_TRACKING_USERNAME=arvor-admin",
        f"MLFLOW_TRACKING_PASSWORD={auth_password}",
        f"ARVOR_MLFLOW_SPOOL={(args.state_dir / 'spool/pending.jsonl').resolve()}",
        "MLFLOW_HTTP_REQUEST_TIMEOUT=3",
        "MLFLOW_HTTP_REQUEST_MAX_RETRIES=1",
        "",
    ]))
    print(json.dumps({
        "postgres_database": "mlflow", "postgres_role": "mlflow_app",
        "minio_bucket": "mlflow-artifacts", "minio_user": access_key,
        "config_files": ["mlflow.env", "basic_auth.ini", "client.env"],
        "secrets_created_or_kept": 5,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
