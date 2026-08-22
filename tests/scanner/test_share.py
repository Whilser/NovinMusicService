import os
import inspect
import stat
import unittest
from pathlib import Path

from app.share import ShareManager, ShareValidationError


class ShareManagerTests(unittest.TestCase):
    def test_constructor_has_only_the_public_contract_parameters(self):
        self.assertEqual(
            list(inspect.signature(ShareManager).parameters),
            ["mount_point", "runner", "env"],
        )

    def test_mount_point_is_fixed_by_constructor(self):
        with self.assertRaises(ShareValidationError):
            ShareManager(mount_point="/tmp/music", runner=lambda *args, **kwargs: None, env={})

    def test_guest_mount_is_read_only_at_fixed_mountpoint(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        manager = ShareManager(mount_point="/music", runner=run, env={})
        status = manager.apply({"host": "nas.local", "share": "Music"})

        self.assertEqual(status["state"], "connected")
        self.assertEqual(calls, [["mount", "-t", "cifs", "//nas.local/Music", "/music", "-o", "ro,guest"]])

    def test_rejects_command_injection_and_writable_options(self):
        manager = ShareManager(runner=lambda *args, **kwargs: None, env={})

        for settings in (
            {"host": "nas;reboot", "share": "Music"},
            {"host": "nas", "share": "../Music"},
            {"host": "nas", "share": "Music", "options": "rw"},
            {"host": "nas", "share": "Music", "domain": "HOME\npassword=hijack"},
        ):
            with self.subTest(settings=settings), self.assertRaises(ShareValidationError):
                manager.apply(settings)

    def test_credentials_are_kept_out_of_mount_arguments_and_status(self):
        calls = []
        credential_paths = []

        def run(command, **kwargs):
            calls.append(command)
            credentials_path = command[-1].split("credentials=", 1)[1].split(",", 1)[0]
            credential_paths.append(credentials_path)
            self.assertEqual(stat.S_IMODE(os.stat(credentials_path).st_mode), 0o600)
            with open(credentials_path, encoding="utf-8") as credentials:
                self.assertEqual(credentials.read(), "username=alice\npassword=very-secret\ndomain=HOME\n")
            return type("Result", (), {"returncode": 0, "stderr": ""})()

        manager = ShareManager(
            runner=run,
            env={"SMB_USERNAME": "alice", "SMB_PASSWORD": "very-secret"},
        )
        status = manager.apply({"host": "nas", "share": "Music", "domain": "HOME"})

        rendered = repr(calls)
        self.assertNotIn("alice", rendered)
        self.assertNotIn("very-secret", rendered)
        self.assertNotIn("very-secret", repr(status))
        self.assertEqual(status["state"], "connected")
        self.assertFalse(Path(credential_paths[0]).exists())

    def test_mount_failure_reports_sanitized_error_status(self):
        def run(command, **kwargs):
            return type("Result", (), {"returncode": 32, "stderr": "password=leaked-by-helper"})()

        manager = ShareManager(runner=run, env={})
        status = manager.apply({"host": "nas", "share": "Music"})

        self.assertEqual(status, {"state": "error", "message": "SMB mount failed"})

    def test_mount_failure_classifies_safe_actionable_errors(self):
        cases = (
            ("mount error: could not resolve address", "SMB host could not be resolved; use the NAS IP address"),
            ("mount error(13): Permission denied", "SMB server denied guest access"),
            ("Unable to apply new capability set.", "Container lacks capabilities required for SMB mounting"),
        )
        for stderr, expected in cases:
            with self.subTest(stderr=stderr):
                runner = lambda command, **kwargs: type(
                    "Result", (), {"returncode": 32, "stderr": stderr}
                )()
                status = ShareManager(runner=runner, env={}).apply({"host": "nas", "share": "Music"})
                self.assertEqual({"state": "error", "message": expected}, status)

    def test_runner_exception_reports_sanitized_error_status(self):
        def run(command, **kwargs):
            raise OSError("secret helper detail")

        manager = ShareManager(runner=run, env={})

        self.assertEqual(
            manager.apply({"host": "nas", "share": "Music"}),
            {"state": "error", "message": "SMB mount failed"},
        )

    def test_status_detects_when_successful_mount_is_no_longer_present(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            returncode = 1 if command[0] == "mountpoint" else 0
            return type("Result", (), {"returncode": returncode, "stderr": ""})()

        manager = ShareManager(runner=run, env={})
        manager.apply({"host": "nas", "share": "Music"})

        self.assertEqual(manager.status()["state"], "error")
        self.assertEqual(calls[-1], ["mountpoint", "-q", "/music"])

if __name__ == "__main__":
    unittest.main()
