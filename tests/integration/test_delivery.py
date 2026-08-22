import contextlib
import io
import json
import os
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

from fastapi.testclient import TestClient
import yaml

from app.api.player import get_mpd_client
from app.api.scan import get_share_manager
from app.catalog import Catalog
from app.mpd import MpdConnectionError
from app.share import ShareManager


ROOT = Path(__file__).parents[2]
DOCKER = shutil.which("docker")
_IMPORT_DATA_DIRECTORY = tempfile.TemporaryDirectory(prefix="novin-delivery-import-")
with patch.dict(os.environ, {"NOVIN_DATA_DIR": _IMPORT_DATA_DIRECTORY.name}):
    from app.main import create_app


class DeliveryIntegrationTests(unittest.TestCase):
    def test_api_health_without_nas_or_mpd(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(data_dir=Path(directory), music_root=Path(directory) / "music")
            with TestClient(app) as client:
                response = client.get("/api/health")

            self.assertEqual(200, response.status_code)
            self.assertEqual({"status": "ok"}, response.json())

    def test_catalog_state_persists_after_close_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            catalog = Catalog(database)
            track_ids = catalog.reconcile_tracks(
                [
                    {"path": "artist/album/first.flac", "title": "First"},
                    {"path": "artist/album/second.flac", "title": "Second"},
                ]
            )["track_ids"]
            playlist_id = catalog.create_playlist("Persistent order")["id"]
            catalog.set_playlist_tracks(playlist_id, [track_ids[1], track_ids[0]])
            catalog.set_preference(track_ids[0], rating=4, favorite=True)
            catalog.update_settings({"mpd_host": "host.docker.internal", "mpd_port": "6600"})
            catalog.close()

            restarted = Catalog(database)
            tracks = restarted.list_tracks(limit=50, offset=0)
            playlist = restarted.get_playlist(playlist_id)
            settings = restarted.get_settings()
            restarted.close()

            self.assertEqual(2, tracks["total"])
            preferred = next(track for track in tracks["items"] if track["id"] == track_ids[0])
            self.assertEqual(4, preferred["rating"])
            self.assertIs(True, preferred["favorite"])
            self.assertEqual([track_ids[1], track_ids[0]], [track["id"] for track in playlist["tracks"]])
            self.assertEqual("Persistent order", playlist["name"])
            self.assertEqual({"mpd_host": "host.docker.internal", "mpd_port": "6600"}, settings)

    def test_compose_exposes_only_the_required_runtime_contract(self):
        compose_path = ROOT / "docker-compose.yml"
        compose = compose_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(compose)
        service = parsed["services"]["novin-music"]

        self.assertEqual(["ALL"], service["cap_drop"])
        self.assertEqual(
            ["SYS_ADMIN", "DAC_READ_SEARCH", "DAC_OVERRIDE", "SETPCAP"],
            service["cap_add"],
        )
        self.assertEqual(["no-new-privileges:true"], service["security_opt"])
        self.assertNotRegex(compose, r"(?m)^\s*privileged\s*:")
        self.assertEqual(
            ["host.docker.internal:host-gateway", "novincloud.local:10.0.1.52"],
            service["extra_hosts"],
        )
        self.assertIn("novin_data:/data", service["volumes"])
        self.assertIs(True, service["read_only"])
        self.assertIn("healthcheck", service)
        self.assertEqual("unless-stopped", service["restart"])

        override = yaml.safe_load((ROOT / "docker-compose.apparmor-unconfined.yml").read_text(encoding="utf-8"))
        self.assertEqual(
            ["apparmor:unconfined"],
            override["services"]["novin-music"]["security_opt"],
        )

    def test_image_creates_configured_tmpdir_before_package_install(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        create_tmpdir = dockerfile.index("RUN mkdir -p /run/novin")
        package_install = dockerfile.index("apt-get install")
        self.assertLess(create_tmpdir, package_install)

    @unittest.skipUnless(DOCKER, "Docker CLI unavailable: compose config was not executed")
    def test_docker_compose_config_is_structurally_valid(self):
        completed = subprocess.run(
            [DOCKER, "compose", "config", "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        service = json.loads(completed.stdout)["services"]["novin-music"]
        self.assertEqual(["ALL"], service["cap_drop"])
        self.assertEqual(
            ["SYS_ADMIN", "DAC_READ_SEARCH", "DAC_OVERRIDE", "SETPCAP"],
            service["cap_add"],
        )
        self.assertIs(True, service["read_only"])
        self.assertIn("healthcheck", service)

    @unittest.skipUnless(DOCKER, "Docker CLI unavailable: build/start/health smoke was not executed")
    def test_docker_build_start_and_health_smoke(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        project = f"novin-ticket05-{os.getpid()}"
        environment = {**os.environ, "NOVIN_BIND_ADDRESS": "127.0.0.1", "NOVIN_PORT": str(port)}
        command = [DOCKER, "compose", "--project-name", project]
        try:
            started = subprocess.run(
                [*command, "up", "-d", "--build"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
            )
            self.assertEqual(0, started.returncode, started.stdout + started.stderr)
            deadline = time.monotonic() + 60
            last_error = None
            while time.monotonic() < deadline:
                try:
                    with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
                        if response.status == 200 and json.load(response) == {"status": "ok"}:
                            break
                except (OSError, URLError, ValueError) as error:
                    last_error = error
                time.sleep(1)
            else:
                self.fail(f"container health endpoint did not become ready: {last_error}")
        finally:
            subprocess.run(
                [*command, "down", "--volumes", "--remove-orphans"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )

    def test_example_environment_has_names_but_no_secret_values(self):
        example_path = ROOT / ".env.example"
        entries = dict(
            line.split("=", 1)
            for line in example_path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )

        self.assertEqual(
            {"SMB_USERNAME", "SMB_PASSWORD", "MPD_PASSWORD", "SHOUTCAST_API_KEY", "NOVIN_BIND_ADDRESS", "NOVIN_PORT"},
            set(entries),
        )
        self.assertTrue(all(value == "" for value in entries.values()))

    def test_secret_sentinels_never_reach_http_status_or_captured_output(self):
        secrets = {
            "SMB_USERNAME": "smb-user-sentinel",
            "SMB_PASSWORD": "smb-secret-sentinel",
            "MPD_PASSWORD": "mpd-secret-sentinel",
        }
        calls = []

        def failed_mount(arguments, **options):
            calls.append((arguments, options))
            leaked = " ".join(secrets.values())
            return SimpleNamespace(returncode=1, stdout=leaked, stderr=leaked)

        class FailedMpd:
            def status(self):
                raise MpdConnectionError(" ".join(secrets.values()))

        manager = ShareManager(runner=failed_mount, env=secrets)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, secrets):
            app = create_app(data_dir=Path(directory), music_root=Path(directory) / "music")
            app.dependency_overrides[get_share_manager] = lambda: manager
            app.dependency_overrides[get_mpd_client] = lambda: FailedMpd()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                with TestClient(app) as client:
                    responses = [
                        client.post("/api/share", json={"host": "nas", "share": "music"}),
                        client.get("/api/share/status"),
                        client.get("/api/settings"),
                        client.get("/api/player/status"),
                    ]

        captured = "\n".join([*(response.text for response in responses), repr(manager.status()), repr(calls), output.getvalue()])
        self.assertEqual([503, 200, 200, 200], [response.status_code for response in responses])
        for sentinel in secrets.values():
            self.assertNotIn(sentinel, captured)

    def test_image_contract_includes_cifs_helper_and_explicit_mount_user(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        locked = (ROOT / "requirements-prod.lock").read_text(encoding="utf-8").splitlines()
        entrypoint = (ROOT / "scripts/entrypoint.sh").read_text(encoding="utf-8")

        self.assertRegex(dockerfile, r"(?m)^FROM python:3\.12\.13-slim-bookworm$")
        self.assertIn("cifs-utils", dockerfile)
        self.assertIn("util-linux", dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER root$")
        self.assertIn('NOVIN_DATA_DIR=/data', dockerfile)
        self.assertIn('NOVIN_MUSIC_ROOT=/music', dockerfile)
        self.assertIn('TMPDIR=/run/novin', dockerfile)
        self.assertIn("requirements-prod.lock", dockerfile)
        self.assertTrue(locked)
        self.assertTrue(all("==" in requirement for requirement in locked))
        self.assertIn("mkdir -p /data /music /run/novin", entrypoint)
        self.assertLess(entrypoint.index("mkdir -p"), entrypoint.index("for directory"))

    def test_backup_command_creates_a_consistent_sqlite_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.sqlite3"
            destination = Path(directory) / "backup.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
                connection.execute("INSERT INTO marker VALUES (?)", ("known-backup-value",))

            result = subprocess.run(
                [sys.executable, "scripts/backup.py", str(source), str(destination)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            with sqlite3.connect(destination) as connection:
                value = connection.execute("SELECT value FROM marker").fetchone()[0]
            self.assertEqual("known-backup-value", value)

    def test_backup_refuses_to_replace_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.sqlite3"
            destination = Path(directory) / "backup.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE marker (value TEXT)")
            destination.write_bytes(b"existing-backup-sentinel")

            result = subprocess.run(
                [sys.executable, "scripts/backup.py", str(source), str(destination)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(b"existing-backup-sentinel", destination.read_bytes())

    def test_backup_failure_cleans_exclusive_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.sqlite3"
            destination = Path(directory) / "backup.sqlite3"
            source.write_bytes(b"not a sqlite database")

            result = subprocess.run(
                [sys.executable, "scripts/backup.py", str(source), str(destination)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(destination.exists())
            self.assertEqual([], list(Path(directory).glob(".backup.sqlite3.*.tmp")))

    def test_backup_is_a_consistent_snapshot_during_active_write(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalog.sqlite3"
            destination = Path(directory) / "backup.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
                connection.execute("INSERT INTO marker VALUES ('committed')")

            writer = sqlite3.connect(source)
            try:
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("INSERT INTO marker VALUES ('uncommitted')")
                result = subprocess.run(
                    [sys.executable, "scripts/backup.py", str(source), str(destination)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            finally:
                writer.rollback()
                writer.close()

            self.assertEqual(0, result.returncode, result.stderr)
            with sqlite3.connect(destination) as connection:
                values = [row[0] for row in connection.execute("SELECT value FROM marker")]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(["committed"], values)
            self.assertEqual("ok", integrity)


if __name__ == "__main__":
    unittest.main()
