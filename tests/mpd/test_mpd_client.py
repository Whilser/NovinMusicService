import socketserver
import threading
import time
import unittest
from unittest.mock import patch

from app.mpd import MpdClient, MpdCommandError, MpdConnectionError


class _MpdHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.wfile.write(b"OK MPD 0.23.12\n")
            self.wfile.flush()
            while line := self.rfile.readline():
                command = line.decode("utf-8").rstrip("\r\n")
                self.server.commands.append(command)
                response = self.server.responses.get(command, ["OK"])
                for item in response:
                    if isinstance(item, tuple) and item[0] == "delay":
                        time.sleep(item[1])
                        continue
                    self.wfile.write((item + "\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError) as error:
            if not self.server.expect_disconnect:
                self.server.errors.append(error)
        except Exception as error:
            self.server.errors.append(error)


class FakeMpdServer:
    def __init__(self, responses, expect_disconnect=False):
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _MpdHandler)
        self.server.daemon_threads = True
        self.server.responses = responses
        self.server.commands = []
        self.server.errors = []
        self.server.expect_disconnect = expect_disconnect
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        if self.server.errors:
            raise AssertionError("fake MPD server errors: {!r}".format(self.server.errors))

    @property
    def port(self):
        return self.server.server_address[1]


class MpdClientTests(unittest.TestCase):
    def test_status_parses_multiline_response_and_ack(self):
        responses = {
            "status": ["volume: 37", "state: play", "elapsed: 12.5", "OK"],
            "currentsong": ["file: jazz/Blue Train.flac", "Artist: John Coltrane", "OK"],
            "next": ["ACK [5@0] {next} player error"],
        }
        with FakeMpdServer(responses) as server:
            client = MpdClient("127.0.0.1", server.port, timeout=0.5)
            self.assertEqual(
                client.status(),
                {
                    "online": True,
                    "volume": 37,
                    "state": "play",
                    "elapsed": 12.5,
                    "song": {"file": "jazz/Blue Train.flac", "artist": "John Coltrane"},
                },
            )
            with self.assertRaisesRegex(MpdCommandError, "player error"):
                client.command("next")

    def test_status_honors_socket_timeout(self):
        with FakeMpdServer(
            {"status": [("delay", 0.1), "OK"]}, expect_disconnect=True
        ) as server:
            client = MpdClient("127.0.0.1", server.port, timeout=0.01)
            with self.assertRaises(MpdConnectionError):
                client.status()

    def test_play_uris_uses_only_temporary_queue_and_safely_quotes_paths(self):
        responses = {
            "status": ["state: play", "OK"],
            "currentsong": ["file: library/B.flac", "OK"],
        }
        with FakeMpdServer(responses) as server:
            client = MpdClient(
                "127.0.0.1",
                server.port,
                "not-stored-by-client",
                timeout=0.5,
                uri_prefix="library/",
            )
            with patch("app.mpd.client.random.shuffle", side_effect=lambda items: items.reverse()):
                result = client.play_uris(['A "live".flac', "B.flac"], shuffle=True)

            queue_commands = [
                command for command in server.server.commands
                if not command.startswith("password ") and command not in ("status", "currentsong")
            ]
            self.assertEqual(
                queue_commands,
                ["clear", 'add "library/B.flac"', 'add "library/A \\"live\\".flac"', "play"],
            )
            self.assertEqual(
                [command for command in server.server.commands if command.startswith("password ")],
                ['password "not-stored-by-client"', 'password "not-stored-by-client"'],
            )
            self.assertEqual(result["state"], "play")
            self.assertFalse(
                {"save", "load", "playlistadd", "playlistdelete"}
                & {command.split(" ", 1)[0] for command in server.server.commands}
            )
            with self.assertRaises(MpdCommandError):
                client.play_uris(["../outside.flac"])
            with self.assertRaises(MpdCommandError):
                client.command("save")

    def test_uri_prefix_cannot_escape_music_root(self):
        client = MpdClient(uri_prefix="../outside")
        with self.assertRaisesRegex(MpdCommandError, "music root"):
            client.play_uris(["album/song.flac"])

    def test_play_stream_accepts_only_shoutcast_https_playlists(self):
        responses = {"status": ["state: play", "OK"], "currentsong": ["file: station.pls", "OK"]}
        with FakeMpdServer(responses) as server:
            client = MpdClient("127.0.0.1", server.port, timeout=0.5)
            client.play_stream("https://yp.shoutcast.com/sbin/tunein-station.pls?id=42")
            self.assertIn('add "https://yp.shoutcast.com/sbin/tunein-station.pls?id=42"', server.server.commands)
            with self.assertRaises(MpdCommandError):
                client.play_stream("http://example.test/stream")

    def test_transport_whitelist_maps_to_mpd_commands_and_returns_status(self):
        responses = {"status": ["state: pause", "OK"], "currentsong": ["OK"]}
        with FakeMpdServer(responses) as server:
            client = MpdClient("127.0.0.1", server.port, timeout=0.5)
            cases = [
                ("play", {}, "play"),
                ("pause", {}, "pause 1"),
                ("previous", {}, "previous"),
                ("next", {}, "next"),
                ("seek", {"position": 42}, "seekcur 42.0"),
                ("volume", {"volume": 55}, "setvol 55"),
            ]
            for name, params, expected_command in cases:
                result = client.command(name, **params)
                self.assertEqual(result["state"], "pause")
                self.assertIn(expected_command, server.server.commands)


if __name__ == "__main__":
    unittest.main()
