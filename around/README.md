# around Terminal

A Braille-rendered world map for your terminal, with live flight, ship, earthquake,
city weather, and day/night layers. Pan, zoom, search, filter, and click markers
for details — all over `curses`.

## Install

### pipx (recommended for end users)

```bash
pipx install around
around
```

### pip

```bash
pip install around
around
```

### From source (clone and run, no install)

```bash
git clone https://github.com/a-shygun/around.git
cd around
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
around
```

You can also run it straight from the checkout without installing anything, as long
as `numpy` and `Pillow` are available:

```bash
pip install numpy Pillow
PYTHONPATH=src python3 -m around
```

## Requirements

- Python 3.10+
- A terminal that supports UTF-8 and (ideally) 256-color / true-color for the
  altitude and country coloring. Works over SSH.
- On Windows, `windows-curses` is pulled in automatically as a dependency.

## Controls

| Key | Action |
|---|---|
| Arrow keys / W, A, D | Pan |
| `+` / `-` | Zoom in / out |
| `0` | Reset view |
| `/` | Search |
| `O` | Filter |
| `<` / `>` | Cycle through overlapping markers |
| `P` / `E` / `C` / `S` | Toggle plane / earthquake / city / ship |
| `N` | Toggle the day/night terminator |
| Mouse click | Select a marker |
| `Q` | Quit |

CLI options: `around --offline` uses cached data only, `around --list-layers`
lists the available layers, and `around --disable-layer ships` starts with ships
hidden. Repeat `--disable-layer NAME` to disable more than one layer.

## Data sources

- Country borders: [Natural Earth](https://www.naturalearthdata.com/) 1:50m admin-0
  boundaries, fetched once and cached locally.
- Live flights: [OpenSky Network REST API](https://opensky-network.org/apidoc/rest.html)
  (public, unauthenticated, rate-limited).
- Earthquakes: [USGS GeoJSON feeds](https://earthquake.usgs.gov/earthquakes/feed/).
- City weather and forecasts: [Open-Meteo](https://open-meteo.com/) (no API key required).
- Ships: [Fintraffic Digitraffic AIS](https://www.digitraffic.fi/en/marine-traffic/),
  open data with coverage focused on Finnish waters.

Cached map data and layer data are stored under `~/.cache/around/` (or
`$XDG_CACHE_HOME/around` if set). The map and API data load in the background;
cached results remain available while refreshes are in progress.

## Development

```bash
git clone https://github.com/a-shygun/around.git
cd around
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

The layer system is pluggable: anything under `src/around/layers/` that
subclasses `around.core.layer.Layer` is auto-discovered and added to the app at
startup (see `around/layers/__init__.py`).

## Package manager recipes

The files in [`packaging/`](./packaging) are maintainer drafts, not installable
release recipes yet. The Homebrew formula still needs published source and
dependency checksums, and the AUR recipe needs its release source checksum.
Use `pipx install around` for now.

## License

MIT — see [LICENSE](./LICENSE).
