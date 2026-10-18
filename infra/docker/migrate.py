"""Verified backups and empty-volume restores; source data is never overwritten."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VOLUMES = {"app_data": "lab-agent-local_app_data", "uploads": "lab-agent-local_uploads",
    "chroma": "lab-agent-local_chroma_data"}


def file_manifest(directory):
    root = Path(directory)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not supported in migration snapshots")
        if path.is_file():
            with path.open("rb") as content:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(content, "sha256").hexdigest()
    return result


def restore_volume(target, stream):
    target = Path(target).resolve()
    if any(path.is_file() or path.is_symlink() for path in target.rglob("*")):
        raise FileExistsError("Target volume is not empty; refusing to overwrite")
    # Spool before validation so no member is extracted until all paths are checked.
    with tempfile.TemporaryFile() as staged:
        shutil.copyfileobj(stream, staged)
        staged.seek(0)
        with tarfile.open(fileobj=staged, mode="r:*") as archive:
            for member in archive.getmembers():
                path = Path(member.name)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.name
                        or not (member.isfile() or member.isdir())
                        or not (target / path).resolve().is_relative_to(target)):
                    raise ValueError("Unsafe archive member")
            archive.extractall(target, filter="data")


def compose(*args, **kwargs):
    command = ["docker", "compose", "--project-directory", str(ROOT), "--env-file",
        str(ROOT / "infra/docker/.env"), "-f", str(ROOT / "compose.yaml"), *args]
    return subprocess.run(command, check=True, **kwargs)


def table_counts(engine):
    from sqlalchemy import inspect, text
    with engine.connect() as db:
        return {table: db.scalar(text(f"SELECT COUNT(*) FROM `{table}`"))
            for table in sorted(inspect(engine).get_table_names())}


def chroma_counts(directory):
    path = Path(directory) / "chroma.sqlite3"
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
        return dict(db.execute("SELECT c.name, COUNT(e.id) FROM collections c "
            "LEFT JOIN segments s ON s.collection=c.id "
            "LEFT JOIN embeddings e ON e.segment_id=s.id GROUP BY c.name").fetchall())


def snapshot(mysqldump):
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import settings, UPLOAD_DIR
    from app.database import engine
    from sqlalchemy.engine import make_url
    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() != "mysql" or url.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Only the configured local MySQL source is supported")
    backup = ROOT / "backend/data/docker-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    app_data = backup / "app_data"
    app_data.mkdir()
    for source, target in ((Path(settings.KNOWLEDGE_DIR), app_data / "knowledge"),
            (UPLOAD_DIR, backup / "uploads"), (ROOT / "backend/data/chroma", backup / "chroma")):
        if not source.is_dir():
            raise FileNotFoundError(f"Required source directory is missing: {source}")
        shutil.copytree(source, target)
    checkpoint = Path(settings.AGENT_CHECKPOINT_PATH)
    if checkpoint.exists():
        (app_data / "agent").mkdir()
        with sqlite3.connect(f"{checkpoint.as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(app_data / "agent/checkpoints.sqlite") as destination:
                source.backup(destination)
    # Use a private temporary option file, never command-line passwords.
    def option(value):
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'
    with tempfile.TemporaryDirectory(prefix="lab-agent-dump-") as directory:
        config = Path(directory) / "client.cnf"
        config.write_text("[client]\n" + "".join(f"{key}={option(value)}\n" for key, value in {
            "host": url.host, "port": url.port or 3306, "user": url.username,
            "password": url.password or ""}.items()), encoding="utf-8")
        subprocess.run([mysqldump, f"--defaults-extra-file={config}", "--single-transaction",
            "--set-gtid-purged=OFF", "--column-statistics=0", "--hex-blob", "--no-tablespaces",
            "--routines", "--triggers", f"--result-file={backup / 'database.sql'}", url.database], check=True)
    manifest = {"source_database": url.database, "tables": table_counts(engine), "files": {},
        "database_sha256": file_manifest(backup)["database.sql"], "chroma": chroma_counts(backup / "chroma")}
    for key in VOLUMES:
        manifest["files"][key] = file_manifest(backup / key)
        with tarfile.open(backup / f"{key}.tar", "w") as archive:
            for child in (backup / key).iterdir():
                archive.add(child, arcname=child.name)
    (backup / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(backup), "tables": len(manifest["tables"]),
        "rows": sum(manifest["tables"].values()), "files": {key: len(value) for key, value in manifest["files"].items()}}, ensure_ascii=False))
    return backup


def restore(backup):
    backup = Path(backup).resolve()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if file_manifest(backup)["database.sql"] != manifest["database_sha256"]:
        raise ValueError("SQL backup checksum mismatch")
    # Check all destinations before modifying any of them.
    for key, name in VOLUMES.items():
        if file_manifest(backup / key) != manifest["files"][key]:
            raise ValueError(f"Snapshot checksum mismatch: {key}")
        subprocess.run(["docker", "volume", "create", "--label", "com.docker.compose.project=lab-agent-local",
            "--label", f"com.docker.compose.volume={'chroma_data' if key == 'chroma' else key}", name], check=True, stdout=subprocess.DEVNULL)
        result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{name}:/target",
            "--entrypoint", "python", "lab-agent-backend:local", "/opt/deploy/migrate.py", "inspect-volume", "/target"],
            check=True, capture_output=True, text=True)
        if json.loads(result.stdout):
            raise FileExistsError(f"Nonempty target volume: {name}")
    # Starting MySQL alone initializes its volume, but does not create application tables.
    compose("up", "-d", "--wait", "mysql", stdout=subprocess.DEVNULL)
    check_sql = "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='lab_agent'"
    result = compose("exec", "-T", "mysql", "sh", "-c",
        'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" -N -B lab_agent -e "' + check_sql + '"',
        capture_output=True, text=True)
    if result.stdout.strip() != "0":
        raise FileExistsError("Docker database already contains tables; refusing to overwrite")
    for key, name in VOLUMES.items():
        with (backup / f"{key}.tar").open("rb") as archive:
            subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "-v", f"{name}:/target",
                "--entrypoint", "python", "lab-agent-backend:local", "/opt/deploy/migrate.py", "restore-volume", "/target"],
                stdin=archive, check=True)
        result = subprocess.run(["docker", "run", "--rm", "--network", "none", "-v", f"{name}:/target:ro",
            "--entrypoint", "python", "lab-agent-backend:local", "/opt/deploy/migrate.py", "inspect-volume", "/target"],
            check=True, capture_output=True, text=True)
        if json.loads(result.stdout) != manifest["files"][key]:
            raise ValueError(f"Restored volume checksum mismatch: {name}")
    with (backup / "database.sql").open("rb") as sql:
        compose("exec", "-T", "mysql", "sh", "-c",
            'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u "$MYSQL_USER" --default-character-set=utf8mb4 lab_agent', stdin=sql)
    print("All file hashes verified; SQL imported into the independent Docker database.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["snapshot", "restore", "restore-volume", "inspect-volume"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--mysqldump", default="mysqldump")
    args = parser.parse_args()
    if args.operation == "snapshot":
        snapshot(args.mysqldump)
    elif args.operation == "restore":
        restore(args.path)
    elif args.operation == "restore-volume":
        restore_volume(Path(args.path), sys.stdin.buffer)
    else:
        print(json.dumps(file_manifest(Path(args.path))))


if __name__ == "__main__":
    main()
