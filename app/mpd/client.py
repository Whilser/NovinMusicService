from __future__ import annotations

import random
import socket
from pathlib import PurePosixPath
from typing import Any, Iterable, Optional
from urllib.parse import urlparse


class MpdError(Exception):
    """Base error exposed by the MPD boundary."""


class MpdConnectionError(MpdError):
    """MPD could not be reached or returned an invalid protocol response."""


class MpdCommandError(MpdError):
    """MPD rejected a command, or the requested command is not permitted."""


class MpdConfigurationError(MpdError):
    """Saved MPD settings cannot describe a valid connection."""


_COMMAND_PARAMS = {
    "play": frozenset({"song"}),
    "pause": frozenset({"paused"}),
    "previous": frozenset(),
    "next": frozenset(),
    "seek": frozenset({"position"}),
    "volume": frozenset({"volume"}),
}
_INTEGER_FIELDS = {"volume", "repeat", "random", "single", "consume", "playlist", "playlistlength", "song", "songid", "nextsong", "nextsongid", "bitrate"}
_FLOAT_FIELDS = {"elapsed", "duration"}


def _quote(value: str) -> str:
    return '"{}"'.format(value.replace("\\", "\\\\").replace('"', '\\"'))


class MpdClient:
    def __init__(
        self,
        host: str = "host.docker.internal",
        port: int = 6600,
        password: Optional[str] = None,
        timeout: float = 1.0,
        uri_prefix: str = "",
    ):
        if not isinstance(host, str) or not host.strip():
            raise MpdConfigurationError("mpd_host must be a non-empty string")
        try:
            resolved_port = int(port)
        except (TypeError, ValueError) as error:
            raise MpdConfigurationError(
                "mpd_port must be an integer between 1 and 65535"
            ) from error
        if not 1 <= resolved_port <= 65535:
            raise MpdConfigurationError("mpd_port must be an integer between 1 and 65535")
        self.host = host
        self.port = resolved_port
        self.uri_prefix = uri_prefix
        self.password = password
        self.timeout = timeout

    @staticmethod
    def _read_response(stream) -> dict[str, Any]:
        values: dict[str, Any] = {}
        while True:
            raw = stream.readline()
            if not raw:
                raise MpdConnectionError("MPD closed the connection before completing a response")
            line = raw.decode("utf-8", "strict").rstrip("\r\n")
            if line == "OK":
                return values
            if line.startswith("ACK "):
                message = line.split("}", 1)[-1].strip() or line
                raise MpdCommandError(message)
            if ": " not in line:
                raise MpdConnectionError("invalid MPD response")
            key, value = line.split(": ", 1)
            normalized = key.lower()
            converted: Any = value
            try:
                if normalized in _INTEGER_FIELDS:
                    converted = int(value)
                elif normalized in _FLOAT_FIELDS:
                    converted = float(value)
            except ValueError:
                converted = value
            if normalized in values:
                previous = values[normalized]
                values[normalized] = previous + [converted] if isinstance(previous, list) else [previous, converted]
            else:
                values[normalized] = converted

    def _run(self, commands: Iterable[str]) -> list[dict[str, Any]]:
        try:
            connection = socket.create_connection((self.host, self.port), self.timeout)
            connection.settimeout(self.timeout)
            with connection, connection.makefile("rwb") as stream:
                greeting = stream.readline().decode("utf-8", "strict").rstrip("\r\n")
                if not greeting.startswith("OK MPD "):
                    raise MpdConnectionError("invalid MPD greeting")
                results = []
                all_commands = list(commands)
                if self.password:
                    all_commands.insert(0, "password {}".format(_quote(self.password)))
                for command in all_commands:
                    stream.write((command + "\n").encode("utf-8"))
                    stream.flush()
                    try:
                        response = self._read_response(stream)
                    except MpdCommandError as error:
                        if self.password and command.startswith("password "):
                            raise MpdConnectionError("MPD authentication failed") from error
                        raise
                    if not (self.password and command.startswith("password ")):
                        results.append(response)
                return results
        except MpdError:
            raise
        except (OSError, UnicodeError) as error:
            raise MpdConnectionError(str(error)) from error

    def status(self) -> dict[str, Any]:
        status, song = self._run(["status", "currentsong"])
        return {"online": True, **status, "song": song or None}

    def command(self, name: str, **params: Any) -> dict[str, Any]:
        if name not in _COMMAND_PARAMS:
            raise MpdCommandError("command is not allowed")
        if set(params) - _COMMAND_PARAMS[name]:
            raise MpdCommandError("command parameters are not allowed")
        try:
            if name == "play":
                command = "play" if "song" not in params else "play {}".format(int(params["song"]))
            elif name == "pause":
                paused = params.get("paused", True)
                if not isinstance(paused, bool):
                    raise MpdCommandError("paused must be a boolean")
                command = "pause {}".format(1 if paused else 0)
            elif name in ("previous", "next"):
                command = name
            elif name == "seek":
                if "position" not in params:
                    raise MpdCommandError("seek requires a position")
                command = "seekcur {}".format(float(params["position"]))
            else:
                if "volume" not in params or not 0 <= int(params["volume"]) <= 100:
                    raise MpdCommandError("volume must be between 0 and 100")
                command = "setvol {}".format(int(params["volume"]))
        except (TypeError, ValueError, OverflowError) as error:
            raise MpdCommandError("invalid command value") from error
        self._run([command])
        return self.status()

    def _uri(self, path: str) -> str:
        if not isinstance(path, str) or not path or any(ord(character) < 32 or ord(character) == 127 for character in path):
            raise MpdCommandError("invalid track path")
        normalized = path.replace("\\", "/")
        candidate = PurePosixPath(normalized)
        if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
            raise MpdCommandError("track path must stay below the music root")
        prefix = self.uri_prefix.replace("\\", "/").strip("/")
        prefix_path = PurePosixPath(prefix)
        if any(ord(character) < 32 or ord(character) == 127 for character in prefix) or any(
            part in ("", ".", "..") for part in prefix_path.parts
        ):
            raise MpdCommandError("URI prefix must stay below the music root")
        return "/".join(part for part in (prefix, candidate.as_posix()) if part)

    def play_uris(self, paths: Iterable[str], shuffle: bool = False) -> dict[str, Any]:
        uris = [self._uri(path) for path in paths]
        if not uris:
            raise MpdCommandError("at least one track is required")
        if shuffle:
            random.shuffle(uris)
        commands = ["clear"] + ["add {}".format(_quote(uri)) for uri in uris] + ["play"]
        self._run(commands)
        return self.status()

    def play_stream(self, stream_url: str) -> dict[str, Any]:
        """Replace only the temporary queue with a trusted directory stream."""
        if not isinstance(stream_url, str) or len(stream_url) > 2048 or any(ord(char) < 32 for char in stream_url):
            raise MpdCommandError("invalid radio stream URL")
        parsed = urlparse(stream_url)
        if parsed.scheme != "https" or parsed.netloc != "yp.shoutcast.com" or not parsed.path.endswith(".pls"):
            raise MpdCommandError("radio stream URL is not an allowed Shoutcast playlist")
        self._run(["clear", "add {}".format(_quote(stream_url)), "play"])
        return self.status()
