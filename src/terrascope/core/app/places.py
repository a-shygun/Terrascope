"""Place search (the / key on the tabs without a search box of their own)."""

from __future__ import annotations

import difflib
import unicodedata

from .shared import (
    KEYS,
    TABS,
    curses
)

PLACE_SEARCH_LIMIT = 100  # entries listed at most; type more to narrow it down


def _fold(text: str) -> str:
    """Lower case without accents, so "sao paulo" finds "São Paulo"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def place_matches(places: list[tuple], query: str, limit: int = PLACE_SEARCH_LIMIT) -> list[tuple]:
    """The places matching `query`, best first: exact names, then names that
    start with it, then a word that does ("york" -> New York), then any name
    or country containing it. `places` is sorted biggest first, so ties go to
    the bigger place. Only when none of those match, the closest spellings
    ("seol" -> Seoul). Nothing typed = the biggest places."""
    needle = " ".join(_fold(query).replace(",", " ").split())
    if not needle:
        return places[:limit]
    tiers: tuple[list, list, list, list] = ([], [], [], [])
    for place in places:
        name = _fold(place[2])
        if name == needle:
            tiers[0].append(place)
        elif name.startswith(needle):
            tiers[1].append(place)
        elif any(word.startswith(needle) for word in name.replace("-", " ").split()):
            tiers[2].append(place)
        elif needle in f"{name} {_fold(place[5])}":
            tiers[3].append(place)
        if len(tiers[0]) >= limit:
            break  # nothing later can outrank these
    found = [place for tier in tiers for place in tier][:limit]
    if found:
        return found
    names = {_fold(place[2]) for place in places}
    close = difflib.get_close_matches(needle, names, n=limit, cutoff=0.75)
    rank = {name: index for index, name in enumerate(close)}
    return sorted(
        (place for place in places if _fold(place[2]) in rank),
        key=lambda place: rank[_fold(place[2])],
    )[:limit]


def place_label(place: tuple) -> str:
    _lon, _lat, name, _capital, _population, country = place
    return f"{name} \u00b7 {country}" if country else name


class PlaceSearchMixin:

    def _layer(self, name: str):
        return next((layer for layer in self.world.layers if layer.name == name), None)

    def place_choices(self) -> list[tuple[str, tuple]]:
        """(label, place) entries for the current query. Cached: the list is
        drawn every frame but only changes when the query does."""
        basemap = self._layer("basemap")
        places = basemap.places() if basemap is not None else []
        cache_key = (self.place_query, id(places), len(places))
        if self._place_cache is None or self._place_cache[0] != cache_key:
            choices = [(place_label(place), place) for place in place_matches(places, self.place_query)]
            self._place_cache = (cache_key, choices)
        return self._place_cache[1]

    def places_loaded(self) -> bool:
        basemap = self._layer("basemap")
        return basemap is not None and bool(basemap.places())

    def open_place_search(self) -> None:
        self.place_query = ""
        self.place_index = 0
        self.place_search_open = True
        self.world.dirty = True

    def close_place_search(self) -> None:
        self.place_search_open = False
        self.place_query = ""
        self.world.dirty = True

    def _place_move(self, delta: int) -> None:
        total = len(self.place_choices())
        self.place_index = max(0, min(max(0, total - 1), self.place_index + delta))
        self.world.dirty = True

    def _place_choose(self, index: int) -> None:
        """Fly to entry `index` and close the search. On the WEATHER tab the
        city is also selected, so its info and forecast fill the panel; on
        other tabs its name is highlighted on the map. With nothing listed the
        search just stays open."""
        choices = self.place_choices()
        if not choices:
            return
        place = choices[max(0, min(index, len(choices) - 1))][1]
        self.close_place_search()
        self.world.clear_selection()
        self.world.focus_location(place[0], place[1])
        weather = self._layer("weather")
        if TABS[self.active_tab].name == "weather" and weather is not None and weather.enabled:
            weather.show_cities = True  # searching for a city means wanting to see it
            self.world.select_item(weather, weather.city_item(place))
            self.info_visible = True
            return
        basemap = self._layer("basemap")
        if basemap is not None:
            basemap.highlight_place(place)

    def handle_place_key(self, key: int) -> None:
        """Keys while the place search is open: typing searches, Up/Down
        (PgUp/PgDn) move the highlight, Enter flies there, Esc closes."""
        if key in KEYS["cancel"]:
            self.close_place_search()
            return
        if key in KEYS["confirm"]:
            self._place_choose(self.place_index)
            return
        if key in KEYS["backspace"]:
            self.place_query = self.place_query[:-1]
            self.place_index = 0
        elif key == curses.KEY_UP:
            self._place_move(-1)
        elif key == curses.KEY_DOWN:
            self._place_move(1)
        elif key == curses.KEY_PPAGE:
            self._place_move(-8)
        elif key == curses.KEY_NPAGE:
            self._place_move(8)
        elif 32 <= key <= 126:
            self.place_query += chr(key)
            self.place_index = 0
        self.world.dirty = True

    def _click_place_search(self, x: int, y: int) -> None:
        """A click while the place search is open: on an entry, fly there;
        elsewhere inside the box, nothing; outside it, close the search."""
        layout = self._place_search_layout
        if layout is not None:
            top, left, height, width = layout.rect
            if left <= x < left + width and top <= y < top + height:
                if y in layout.option_rows:
                    self._place_choose(layout.first_index + layout.option_rows.index(y))
                return
        self.close_place_search()
