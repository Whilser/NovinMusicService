from __future__ import annotations

from typing import Any

from .browser import RadioBrowserDirectory
from .shoutcast import ShoutcastDirectory


class HybridRadioDirectory:
    """Uses the Shoutcast partner directory when configured, otherwise Radio Browser."""

    def __init__(self, shoutcast: ShoutcastDirectory, radio_browser: RadioBrowserDirectory) -> None:
        self.shoutcast = shoutcast
        self.radio_browser = radio_browser

    @property
    def active(self):
        return self.shoutcast if self.shoutcast.configured else self.radio_browser

    def list_stations(self, genre: str = "Pop", search: str = "", limit: int = 18, refresh: bool = False) -> dict[str, Any]:
        directory = self.radio_browser if genre == "Russian" else self.active
        result = directory.list_stations(genre=genre, search=search, limit=limit, refresh=refresh)
        result["source"] = "shoutcast" if directory is self.shoutcast else "radio_browser"
        return result

    def station(self, station_id: str | int) -> dict[str, Any] | None:
        return self.active.station(station_id)
