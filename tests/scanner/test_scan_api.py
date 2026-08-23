import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.scan import ScanJobs, get_scanner, get_share_manager
from app.api.player import get_mpd_client
from app.catalog import Catalog
from app.dependencies import get_catalog
from app.main import create_app
from app.scanner import CoverAsset, ScanSnapshot
from app.share import ShareValidationError


class ScanApiTests(unittest.TestCase):
    def test_scan_status_is_restored_from_existing_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            application = create_app(data_dir=Path(directory) / "data", music_root=directory)
            application.state.catalog.reconcile_tracks([{"path": "song.flac", "title": "Song"}])

            with TestClient(application) as client:
                restored = client.get("/api/scan/status").json()

            self.assertEqual(restored["state"], "completed")
            self.assertEqual(restored["counters"]["indexed"], 1)

    def test_cover_cache_survives_new_job_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            cover_id = "c" * 64
            payload = b"\x89PNG\r\n\x1a\ncover-bytes"
            cover_dir = Path(directory) / "covers"

            jobs = ScanJobs(cover_dir)
            jobs._persist_covers({cover_id: CoverAsset(payload, "image/png", cover_id)})

            restored = ScanJobs(cover_dir).cover(cover_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.data, payload)
            self.assertEqual(restored.mime_type, "image/png")

    def test_scan_reconciles_catalog_and_rejects_parallel_start(self):
        with tempfile.TemporaryDirectory() as directory:
            entered = threading.Event()
            release = threading.Event()

            class BlockingScanner:
                def scan(self, root, progress=None, cached_tracks=None):
                    progress({"discovered": 1, "indexed": 0, "unreadable": 0, "unsupported": 0})
                    entered.set()
                    release.wait(2)
                    return ScanSnapshot(
                        ({"path": "Artist/song.flac", "title": "Scanned", "cover_url": "/api/covers/placeholder"},),
                        {"discovered": 1, "indexed": 1, "unreadable": 0, "unsupported": 0},
                        {},
                        1,
                    )

            class MpdUpdater:
                def __init__(self):
                    self.calls = 0

                def update_database(self):
                    self.calls += 1

            application = create_app(data_dir=Path(directory) / "data", music_root=directory)
            mpd = MpdUpdater()
            application.dependency_overrides[get_scanner] = lambda: BlockingScanner()
            application.dependency_overrides[get_mpd_client] = lambda: mpd
            application.state.catalog.update_settings({"mpd_host": "novin"})
            with TestClient(application) as client:
                started = client.post("/api/scan")
                self.assertEqual(started.status_code, 202)
                self.assertTrue(entered.wait(1))
                running = client.get("/api/scan/status").json()
                self.assertEqual(running["counters"]["discovered"], 1)
                duplicate = client.post("/api/scan")
                self.assertEqual(duplicate.status_code, 409)
                release.set()
                for _ in range(50):
                    status = client.get("/api/scan/status").json()
                    if status["state"] != "running":
                        break
                    time.sleep(0.01)
                self.assertEqual(status["state"], "completed")
                tracks = client.get("/api/tracks").json()
                self.assertEqual([track["title"] for track in tracks["items"]], ["Scanned"])
                self.assertEqual(mpd.calls, 1)
                placeholder_url = tracks["items"][0]["cover_url"]
                placeholder = client.get(placeholder_url)
                self.assertEqual(placeholder.status_code, 200)
                self.assertEqual(placeholder.headers["content-type"], "image/svg+xml")

    def test_failed_scan_preserves_previous_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            class FailingScanner:
                def scan(self, root, progress=None, cached_tracks=None):
                    raise OSError("share unavailable")

            application = create_app(data_dir=Path(directory) / "data", music_root=directory)
            catalog = Catalog(Path(directory) / "override.sqlite3")
            catalog.reconcile_tracks([{"path": "existing.flac", "title": "Existing"}])
            application.dependency_overrides[get_catalog] = lambda: catalog
            application.dependency_overrides[get_scanner] = lambda: FailingScanner()
            with TestClient(application) as client:
                self.assertEqual(client.post("/api/scan").status_code, 202)
                for _ in range(50):
                    scan_status = client.get("/api/scan/status").json()
                    if scan_status["state"] != "running":
                        break
                    time.sleep(0.01)
                self.assertEqual(scan_status["state"], "error")
                tracks = client.get("/api/tracks").json()
                self.assertEqual([track["title"] for track in tracks["items"]], ["Existing"])
            catalog.close()

    def test_cover_is_addressed_by_opaque_id_with_mime_etag_and_safe_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            cover_id = "a" * 64
            oversized_id = "b" * 64

            class CoveredScanner:
                def scan(self, root, progress=None, cached_tracks=None):
                    return ScanSnapshot(
                        ({"path": "song.flac", "title": "Song", "cover_url": f"/api/covers/{cover_id}"},),
                        {"discovered": 1, "indexed": 1, "unreadable": 0, "unsupported": 0},
                        {
                            cover_id: CoverAsset(b"image-bytes", "image/jpeg", cover_id),
                            oversized_id: CoverAsset(b"x" * (5 * 1024 * 1024 + 1), "image/jpeg", oversized_id),
                        },
                    )

            application = create_app(data_dir=Path(directory) / "data", music_root=directory)
            application.dependency_overrides[get_scanner] = lambda: CoveredScanner()
            with TestClient(application) as client:
                client.post("/api/scan")
                for _ in range(50):
                    if client.get("/api/scan/status").json()["state"] == "completed":
                        break
                    time.sleep(0.01)
                image = client.get(f"/api/covers/{cover_id}")
                self.assertEqual(image.content, b"image-bytes")
                self.assertEqual(image.headers["content-type"], "image/jpeg")
                self.assertEqual(image.headers["etag"], f'"{cover_id}"')
                cached = client.get(f"/api/covers/{cover_id}", headers={"If-None-Match": f'"{cover_id}"'})
                self.assertEqual(cached.status_code, 304)
                unsafe = client.get("/api/covers/etc-passwd")
                self.assertEqual(unsafe.headers["content-type"], "image/svg+xml")
                oversized = client.get(f"/api/covers/{oversized_id}")
                self.assertEqual(oversized.headers["content-type"], "image/svg+xml")
                self.assertLess(len(oversized.content), 1024)

    def test_share_http_success_error_status_and_saved_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeShare:
                def __init__(self):
                    self.applied = []
                    self.current = {"state": "not_configured"}

                def apply(self, settings):
                    self.applied.append(dict(settings))
                    self.current = {"state": "connected", "mount_point": "/music"}
                    return dict(self.current)

                def status(self):
                    return dict(self.current)

            manager = FakeShare()
            application = create_app(data_dir=Path(directory) / "data", music_root=directory)
            application.dependency_overrides[get_share_manager] = lambda: manager
            with TestClient(application) as client:
                connected = client.post(
                    "/api/share",
                    json={"host": "nas.local", "share": "Music", "domain": "HOME", "options": "vers=3.0"},
                )
                self.assertEqual(connected.status_code, 200)
                self.assertEqual(client.get("/api/share/status").json()["state"], "connected")
                settings = client.get("/api/settings").json()
                self.assertEqual(
                    {key: settings[key] for key in ("smb_host", "smb_share", "smb_domain", "smb_options")},
                    {"smb_host": "nas.local", "smb_share": "Music", "smb_domain": "HOME", "smb_options": "vers=3.0"},
                )
                manager.applied.clear()

                class EmptyScanner:
                    def scan(self, root, progress=None, cached_tracks=None):
                        return ScanSnapshot(
                            (),
                            {"discovered": 0, "indexed": 0, "unreadable": 0, "unsupported": 0},
                            {},
                        )

                application.dependency_overrides[get_scanner] = lambda: EmptyScanner()
                self.assertEqual(client.post("/api/scan").status_code, 202)
                for _ in range(50):
                    if client.get("/api/scan/status").json()["state"] == "completed":
                        break
                    time.sleep(0.01)
                self.assertEqual(
                    manager.applied,
                    [{"host": "nas.local", "share": "Music", "domain": "HOME", "options": "vers=3.0"}],
                )

            class InvalidShare(FakeShare):
                def apply(self, settings):
                    raise ShareValidationError("invalid SMB host or share")

            application = create_app(data_dir=Path(directory) / "other", music_root=directory)
            application.dependency_overrides[get_share_manager] = lambda: InvalidShare()
            with TestClient(application) as client:
                rejected = client.post("/api/share", json={"host": "bad;host", "share": "Music"})
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(rejected.json()["error"]["code"], "invalid_share")

            class FailedMount(FakeShare):
                def apply(self, settings):
                    self.current = {"state": "error", "message": "SMB mount failed"}
                    return dict(self.current)

            application = create_app(data_dir=Path(directory) / "failed", music_root=directory)
            failed_manager = FailedMount()
            application.dependency_overrides[get_share_manager] = lambda: failed_manager
            with TestClient(application) as client:
                failed = client.post("/api/share", json={"host": "nas", "share": "Music"})
                self.assertEqual(failed.status_code, 503)
                self.assertEqual(failed.json()["error"]["code"], "share_mount_failed")
                self.assertEqual(failed.json()["error"]["message"], "SMB mount failed")
                self.assertEqual(client.get("/api/share/status").json()["state"], "error")


if __name__ == "__main__":
    unittest.main()
