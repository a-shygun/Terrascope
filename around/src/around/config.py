import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Runtime cache/data lives under the user's cache dir, never inside the
# installed package (site-packages is often read-only and gets wiped on
# upgrade/reinstall). Honors XDG_CACHE_HOME on Linux when set.
_XDG_CACHE_HOME = os.environ.get("XDG_CACHE_HOME")
CACHE_DIR = (
    Path(_XDG_CACHE_HOME) if _XDG_CACHE_HOME else Path.home() / ".cache"
) / "around"
DATA_DIR = CACHE_DIR

FETCH_NEW_DATA_FROM_API = True

NATURAL_EARTH_BASE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
)
MAP_FILE = "ne_50m_admin_0_countries.geojson"

MAP_CONFIG = {
    "country_color": "#c0c0c0",
    "city_color": "#66ff99",
    "min_zoom": 1.0,
    "max_zoom": 32.0,
    "zoom_step": 2.0,
    "pan_step": 0.12,
}

OUTER_MARGIN = [2, 1]
BOX_GAP = [1, 1]
SIDEBAR_WIDTH = 46
CONTROL_BAR_HEIGHT = 4

KM_PER_DEGREE_LAT = 111.32

RESERVED_KEYS = frozenset("qwado/+=-_0")
