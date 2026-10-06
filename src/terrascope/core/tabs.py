# tabs.py — THE TOP-ROW TABS (what each tab shows)
# Responsible for: building the list of tabs shown on the top row from
# default.yaml (tabs: items:). Each tab says which layers are switched on while
# it is active (by Layer.name). Tabs are numbered in the order listed there
# (1-9 select them from the keyboard).
# Edit default.yaml to: add / remove / reorder tabs, rename them, change the
# colours, or change which layers a tab turns on.
# Not here: how the tab bar is drawn (ui.py) or clicked (app.py). The
# "how everything works" guide is a modal (ui.draw_welcome_modal), not a tab
# — app.py shows it at launch and reopens it on the "?" / ABOUT control.

from __future__ import annotations

from dataclasses import dataclass
from terrascope.core.config import CFG

@dataclass(frozen=True)
class Tab:
    name: str
    label: str  # text on the tab; a number is added in front
    color: str  # "#rrggbb"
    blurb: str  # one line shown in the welcome modal's tab list
    layers: tuple[str, ...] = ()  # Layer.name values switched ON for this tab
    # Full map detail while this tab is active: state / province borders and
    # every city name. Other tabs keep the map clean (country
    # borders, capitals and major cities only).
    detailed: bool = False
    # State / province borders (from map.zoom.province_min). Defaults to the
    # value of `detailed`.
    provinces: bool = False
    # False = the basemap leaves out capital / city names because a layer of this
    # tab labels the cities itself (the WEATHER tab).
    place_names: bool = True
    country_names: bool = True  # False = basemap leaves out country names
    attribution: str = ""  # small credit drawn at the map's bottom-left

def _build(item: dict) -> Tab:
    return Tab(
        name=str(item["name"]),
        label=str(item["label"]),
        color=str(item["color"]),
        blurb=str(item.get("blurb") or ""),
        layers=tuple(item.get("layers") or ()),
        detailed=bool(item.get("detailed", False)),
        provinces=bool(item.get("provinces", item.get("detailed", False))),
        place_names=bool(item.get("place_names", True)),
        country_names=bool(item.get("country_names", True)),
        attribution=str(item.get("attribution") or ""),
    )

TABS: tuple[Tab, ...] = tuple(_build(item) for item in CFG["tabs"]["items"])

START_TAB = int(CFG["tabs"]["start_tab"])  # index of the tab shown at launch
