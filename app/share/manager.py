from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Optional


class ShareError(RuntimeError):
    pass


class ShareValidationError(ShareError):
    pass


class ShareManager:
    MOUNT_POINT = Path("/music")
    _HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
    _SHARE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,79}$")
    _DOMAIN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
    _FLAG_OPTIONS = {"noserverino", "nounix", "soft"}
    _VALUE_OPTIONS = {
        "vers": {"1.0", "2.0", "2.1", "3.0", "3.1.1"},
        "iocharset": {"utf8"},
    }

    def __init__(
        self,
        mount_point="/music",
        runner=None,
        env: Optional[Mapping[str, str]] = None,
    ):
        if Path(mount_point) != self.MOUNT_POINT:
            raise ShareValidationError("SMB mount point must be /music")
        self._runner = runner or subprocess.run
        self._environ = os.environ if env is None else env
        self._status = {"state": "not_configured", "message": "SMB share is not configured"}

    def apply(self, settings: Mapping[str, str]) -> dict:
        host = settings.get("host", "")
        share = settings.get("share", "")
        if not self._HOST.fullmatch(host) or not self._SHARE.fullmatch(share) or ".." in share:
            raise ShareValidationError("invalid SMB host or share")
        domain = settings.get("domain", "")
        if domain and not self._DOMAIN.fullmatch(domain):
            raise ShareValidationError("invalid SMB domain")
        extra_options = self._validated_options(settings.get("options", ""))
        source = f"//{host}/{share}"
        username = self._environ.get("SMB_USERNAME", "")
        password = self._environ.get("SMB_PASSWORD", "")
        if bool(username) != bool(password):
            raise ShareValidationError("SMB_USERNAME and SMB_PASSWORD must be set together")
        if any(character in username + password for character in ("\n", "\r", "\x00")):
            raise ShareValidationError("invalid SMB credentials")
        if self._cifs_is_mounted():
            self._status = {
                "state": "connected",
                "source": source,
                "mount_point": str(self.MOUNT_POINT),
                "authentication": "credentials" if username else "guest",
            }
            return dict(self._status)
        credentials_path = None
        try:
            if username:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as credentials:
                    credentials.write(f"username={username}\npassword={password}\n")
                    if domain:
                        credentials.write(f"domain={domain}\n")
                    credentials_path = credentials.name
                os.chmod(credentials_path, 0o600)
                authentication = f"credentials={credentials_path}"
            else:
                authentication = "guest"
            mount_options = ["ro", authentication, *extra_options]
            try:
                result = self._runner(
                    ["mount", "-t", "cifs", source, str(self.MOUNT_POINT), "-o", ",".join(mount_options)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except Exception:
                self._status = {"state": "error", "message": "SMB mount failed"}
                return dict(self._status)
        finally:
            if credentials_path:
                Path(credentials_path).unlink(missing_ok=True)
        if result.returncode:
            self._status = {
                "state": "error",
                "message": self._failure_message(result.stderr, authenticated=bool(username)),
                "authentication": "credentials" if username else "guest",
            }
        else:
            self._status = {
                "state": "connected",
                "source": source,
                "mount_point": str(self.MOUNT_POINT),
                "authentication": "credentials" if username else "guest",
            }
        return dict(self._status)

    @staticmethod
    def _failure_message(stderr: str, authenticated: bool = False) -> str:
        """Translate known mount.cifs failures without exposing helper output."""
        detail = (stderr or "").lower()
        if "could not resolve address" in detail:
            return "SMB host could not be resolved; use the NAS IP address"
        if "permission denied" in detail or "error(13)" in detail:
            return "SMB server rejected the configured credentials" if authenticated else "SMB server denied guest access"
        if "unable to apply new capability set" in detail:
            return "Container lacks capabilities required for SMB mounting"
        return "SMB mount failed"

    def status(self) -> dict:
        if self._status["state"] == "connected":
            if not self._cifs_is_mounted():
                return {"state": "error", "message": "SMB share is not mounted"}
        return dict(self._status)

    def _cifs_is_mounted(self) -> bool:
        """A tmpfs mount point exists even before CIFS is mounted over it."""
        try:
            result = self._runner(
                ["findmnt", "--noheadings", "--types", "cifs", "--target", str(self.MOUNT_POINT)],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0

    @classmethod
    def _validated_options(cls, raw: str) -> list:
        if not raw:
            return []
        validated = []
        for option in raw.split(","):
            option = option.strip()
            if option in cls._FLAG_OPTIONS:
                validated.append(option)
                continue
            key, separator, value = option.partition("=")
            if not separator or value not in cls._VALUE_OPTIONS.get(key, set()):
                raise ShareValidationError("unsupported SMB mount option")
            validated.append(option)
        return validated
