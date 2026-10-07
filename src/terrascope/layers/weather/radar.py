"""RainViewer radar catalog, tile fetching, and raster sampling."""

from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request
from queue import Empty, Queue
import numpy as np
from PIL import Image
from terrascope.core.config import CACHE_DIR, USER_AGENT
from terrascope.core.mapdata import set_live_progress
from terrascope.core.ui import hex_to_rgb
from terrascope.core.view import View
from terrascope.layers.weather.config import (
    CATALOG_REFRESH_SECONDS,
    CATALOG_RETRY_SECONDS,
    HISTORY_MINUTES,
    INTENSITY_MIN,
    RAINVIEWER_URL,
    MAX_CONCURRENT_TILE_REQUESTS,
    PAST_FRAMES,
    RADAR_MODE,
    RADAR_OPACITY,
    REQUEST_TIMEOUT_SECONDS,
    SUPERSAMPLE,
    TILE_SIZE,
    WORLD_ZOOM,
    _CLOUD_STOPS,
    _PALETTE_STOPS,
    _RADAR_BLEND_RGB,
    _RADAR_COLOR_STEPS,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def _interpolate_palette(stops: list[tuple[float, str]], fraction: float, snap: bool = True) -> str:
    fraction = max(0.0, min(1.0, fraction))
    if snap:
        fraction = round(fraction * _RADAR_COLOR_STEPS) / _RADAR_COLOR_STEPS
    for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
        if fraction <= f1:
            span = f1 - f0
            local = 0.0 if span <= 0 else (fraction - f0) / span
            r0, g0, b0 = hex_to_rgb(c0)
            r1, g1, b1 = hex_to_rgb(c1)
            red = round(r0 + (r1 - r0) * local)
            green = round(g0 + (g1 - g0) * local)
            blue = round(b0 + (b1 - b0) * local)
            return f"#{red:02x}{green:02x}{blue:02x}"
    return stops[-1][1]

def intensity_to_color(fraction: float, mode: str) -> str:
    stops = _CLOUD_STOPS if mode == "satellite" else _PALETTE_STOPS
    return _interpolate_palette(stops, fraction)

# One colour per intensity level, spread over the whole palette (lowest level =
# first stop, highest = last stop). Only these colours are ever drawn.
_LEVEL_COUNT = max(2, _RADAR_COLOR_STEPS)

def _fade(color: str) -> str:
    """Blend a colour towards RADAR_BLEND_RGB by (1 - RADAR_OPACITY)."""
    mixed = (
        round(c * RADAR_OPACITY + b * (1.0 - RADAR_OPACITY))
        for c, b in zip(hex_to_rgb(color), _RADAR_BLEND_RGB)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)

RADAR_LEVEL_COLORS = [
    _fade(
        _interpolate_palette(
            _CLOUD_STOPS if RADAR_MODE == "satellite" else _PALETTE_STOPS,
            index / (_LEVEL_COUNT - 1),
            snap=False,
        )
    )
    for index in range(_LEVEL_COUNT)
]

def radar_level_color(fraction: float) -> str:
    """The level colour a raw intensity fraction (0..1) is drawn in."""
    return RADAR_LEVEL_COLORS[max(0, min(_LEVEL_COUNT - 1, int(fraction * _LEVEL_COUNT)))]

# ---------------------------------------------------------------------------
# RainViewer Weather Maps API client
# ---------------------------------------------------------------------------

class RadarFetchError(Exception):
    pass

def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        raise RadarFetchError(f"Request failed: {error}") from error

def fetch_catalog(mode: str) -> list[dict]:
    """Return the frames to animate, oldest first.

    Each frame includes the tile host from the catalog, its path, timestamp,
    and a nowcast flag (RainViewer currently publishes past radar frames only).
    """
    if mode == "satellite":
        raise RadarFetchError("RainViewer no longer provides satellite frames")
    try:
        payload = json.loads(_http_get(f"{RAINVIEWER_URL}/public/weather-maps.json"))
    except json.JSONDecodeError as error:
        raise RadarFetchError(f"Bad catalog JSON: {error}") from error

    host = payload.get("host")
    if not isinstance(host, str) or not host.startswith(("https://", "http://")):
        raise RadarFetchError("Catalog did not include a valid tile host")
    host = host.rstrip("/")
    frames: list[dict] = []
    radar = payload.get("radar") or {}
    past = radar.get("past") or []
    past = sorted((item for item in past if "time" in item), key=lambda item: item["time"])
    if past and HISTORY_MINUTES > 0:
        cutoff = past[-1]["time"] - HISTORY_MINUTES * 60
        past = [item for item in past if item["time"] >= cutoff]
    for item in past[-PAST_FRAMES:]:
        frames.append({**item, "host": host, "nowcast": False})
    frames = [f for f in frames if "time" in f and "path" in f]
    if not frames:
        raise RadarFetchError("Catalog contained no frames")
    frames.sort(key=lambda f: f["time"])
    return frames

def tile_url(frame: dict, mode: str, x: int, y: int) -> str:
    # RainViewer's free API currently offers only its Universal Blue palette.
    # Its tile host is supplied in the catalog and color scheme 2 is Universal Blue.
    base = f"{frame['host']}{frame['path']}/{TILE_SIZE}/{WORLD_ZOOM}/{x}/{y}"
    return f"{base}/2/1_0.png"

def fetch_frame_raster(frame: dict, mode: str) -> np.ndarray:
    """Stitch every tile of the world at WORLD_ZOOM into one uint8 array.

    0 means "no data / transparent"; 1..255 is intensity.
    """
    count = 2**WORLD_ZOOM
    side = count * TILE_SIZE
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    loaded = 0
    for x in range(count):
        for y in range(count):
            try:
                data = _http_get(tile_url(frame, mode, x, y))
                tile = Image.open(io.BytesIO(data)).convert("RGBA")
            except (RadarFetchError, OSError):
                continue  # a missing tile is just a hole in the overlay
            canvas.paste(tile, (x * TILE_SIZE, y * TILE_SIZE))
            loaded += 1
    if loaded == 0:
        raise RadarFetchError("No tiles could be fetched for frame")
    return rgba_to_intensity(np.asarray(canvas))

def rgba_to_intensity(rgba: np.ndarray) -> np.ndarray:
    # Convert RainViewer's Universal Blue colors back to a monotonic intensity
    # scale so the existing terminal palette and opacity controls still apply.
    # These representative RGB/dBZ pairs follow RainViewer's published color table.
    stops = np.array([
        (130, 123, 105, -10), (206, 192, 135, 10), (136, 221, 238, 15),
        (0, 163, 224, 20), (0, 119, 170, 25), (0, 85, 136, 30),
        (255, 238, 0, 35), (255, 170, 0, 40), (255, 68, 0, 45),
        (193, 0, 0, 50), (255, 170, 255, 55), (255, 119, 255, 60),
        (255, 255, 255, 65),
    ], dtype=np.float32)
    pixels = rgba.reshape(-1, 4)
    result = np.zeros(len(pixels), dtype=np.uint8)
    # Work in chunks to avoid allocating a full-world (pixels × stops × RGB)
    # temporary array for every radar frame.
    chunk_size = 16_384
    for start in range(0, len(pixels), chunk_size):
        end = min(start + chunk_size, len(pixels))
        chunk = pixels[start:end]
        visible = chunk[:, 3] > 0
        if not np.any(visible):
            continue
        colors = chunk[visible, :3].astype(np.float32)
        distances = ((colors[:, None, :] - stops[None, :, :3]) ** 2).sum(axis=-1)
        dbz = stops[np.argmin(distances, axis=-1), 3]
        result[start:end][visible] = np.clip(
            (dbz + 10) * (255.0 / 75.0), 1, 255
        ).astype(np.uint8)
    return result.reshape(rgba.shape[:2])

class RadarStore:
    """Keeps the catalog and one stitched raster per frame, refreshed on a
    background thread. Never blocks the UI: build()/tick() just read what is
    loaded so far, and frames appear in the animation as they arrive.
    """

    def __init__(self, mode: str, on_update=None) -> None:
        self._mode = mode
        self._lock = threading.Lock()
        self._on_update = on_update
        self._frames: list[dict] = []
        self._rasters: dict[int, np.ndarray] = {}
        self._checked_at = 0.0
        self._failed = False
        self._using_cache = False
        self._last_error = ""
        self._busy = False
        self._load_cache()

    def _cache_manifest(self):
        return CACHE_DIR / f"radar-{self._mode}-cache.json"

    def _cache_raster(self, timestamp: int):
        return CACHE_DIR / f"radar-{self._mode}-{timestamp}.npy"

    def _load_cache(self) -> None:
        """Restore the last usable frames before trying the network."""
        try:
            data = json.loads(self._cache_manifest().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict) or data.get("version") != 2:
            return
        entries = data.get("frames")
        if not isinstance(entries, list):
            return
        side = (2**WORLD_ZOOM) * TILE_SIZE
        frames = []
        rasters = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                timestamp = int(entry["time"])
                raster = np.load(self._cache_raster(timestamp), allow_pickle=False)
            except (KeyError, TypeError, ValueError, OSError, EOFError, OverflowError):
                continue
            if not isinstance(raster, np.ndarray):
                continue
            if raster.shape != (side, side) or raster.dtype != np.uint8:
                continue
            frames.append({
                "time": timestamp,
                "path": "",
                "nowcast": bool(entry.get("nowcast", False)),
            })
            rasters[timestamp] = raster
        frames.sort(key=lambda frame: frame["time"])
        with self._lock:
            self._frames = frames
            self._rasters = rasters
            self._using_cache = bool(rasters)

    def _save_raster(self, frame: dict, raster: np.ndarray) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._cache_raster(frame["time"])
            temporary = path.with_suffix(path.suffix + ".tmp")
            with temporary.open("wb") as stream:
                np.save(stream, raster, allow_pickle=False)
            temporary.replace(path)
        except OSError:
            return

    def _save_cache(self) -> None:
        """Persist the metadata for rasters represented by the current catalog."""
        with self._lock:
            frames = [
                dict(frame) for frame in self._frames
                if frame["time"] in self._rasters
            ]
        if not frames:
            try:
                self._cache_manifest().unlink(missing_ok=True)
            except OSError:
                pass
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            manifest = self._cache_manifest()
            temporary = manifest.with_suffix(manifest.suffix + ".tmp")
            payload = {
                "version": 2,
                "frames": [
                    {"time": frame["time"], "nowcast": bool(frame.get("nowcast"))}
                    for frame in frames
                ],
            }
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(manifest)
        except OSError:
            return

    def _prune_cache(self, keep: set[int]) -> None:
        try:
            for path in CACHE_DIR.glob(f"radar-{self._mode}-*.npy"):
                try:
                    timestamp = int(path.stem.rsplit("-", 1)[-1])
                except ValueError:
                    continue
                if timestamp not in keep:
                    path.unlink(missing_ok=True)
        except OSError:
            pass

    def ensure_fresh(self) -> None:
        with self._lock:
            if self._busy:
                return
            interval = CATALOG_RETRY_SECONDS if self._failed else CATALOG_REFRESH_SECONDS
            if time.time() - self._checked_at < interval:
                return
            self._busy = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def retry(self) -> None:
        """Clear the retry backoff and start a fresh background fetch."""
        with self._lock:
            if self._busy:
                return
            self._failed = False
            self._last_error = ""
            self._checked_at = 0.0
        set_live_progress("radar", state="downloading")
        self.ensure_fresh()

    def failed(self) -> bool:
        with self._lock:
            return self._failed

    def cached_fallback(self) -> bool:
        with self._lock:
            return self._using_cache and bool(self._rasters)

    def mark_failed(self, error: str) -> None:
        """Record a failed startup fetch so the normal retry path can recover."""
        with self._lock:
            self._failed = True
            self._using_cache = bool(self._rasters)
            self._last_error = str(error)
            self._checked_at = time.time()

    def loading(self) -> bool:
        with self._lock:
            return self._busy

    def catalog_frames(self) -> list[dict]:
        """Every frame the server offers (oldest first), loaded or not."""
        with self._lock:
            return list(self._frames)

    def loaded_frames(self) -> list[tuple[dict, np.ndarray]]:
        with self._lock:
            return [
                (frame, self._rasters[frame["time"]])
                for frame in self._frames
                if frame["time"] in self._rasters
            ]

    def install_catalog(self, frames: list[dict]) -> None:
        with self._lock:
            self._frames = list(frames)
            wanted = {frame["time"] for frame in frames}
            self._rasters = {stamp: raster for stamp, raster in self._rasters.items() if stamp in wanted}
            kept = set(self._rasters)
        self._save_cache()
        self._prune_cache(kept)

    def install_raster(self, frame: dict, raster: np.ndarray) -> None:
        with self._lock:
            self._rasters[frame["time"]] = raster
            self._failed = False
            self._using_cache = False
            self._last_error = ""
            self._checked_at = time.time()
        self._save_raster(frame, raster)
        self._save_cache()
        if self._on_update is not None:
            self._on_update()

    def _refresh(self) -> None:
        set_live_progress("radar", state="downloading")
        try:
            try:
                frames = fetch_catalog(self._mode)
            except RadarFetchError as error:
                set_live_progress("radar", state="failed", error=str(error))
                self.mark_failed(str(error))
                return
            with self._lock:
                self._frames = frames
                self._using_cache = False
                wanted = {f["time"] for f in frames}
                self._rasters = {t: r for t, r in self._rasters.items() if t in wanted}
                missing = sorted(
                    (f for f in frames if f["time"] not in self._rasters),
                    key=lambda f: (f["nowcast"], -f["time"]),
                )
                completed = len(frames) - len(missing)
                kept = set(self._rasters)
            self._save_cache()
            self._prune_cache(kept)
            set_live_progress(
                "radar", state="downloading", downloaded=completed,
                total=max(1, len(frames)),
            )
            # Observed frames first, newest first, so the live picture shows up quickly.
            # ThreadPoolExecutor registers an interpreter-shutdown hook that
            # joins its workers. A slow radar request could therefore make q
            # appear to hang even though these requests are only background
            # work. Daemon workers let process shutdown leave them behind.
            jobs = Queue()
            for frame in missing:
                jobs.put(frame)
            results = Queue()

            def fetch_worker() -> None:
                while True:
                    try:
                        frame = jobs.get_nowait()
                    except Empty:
                        return
                    try:
                        results.put((frame, fetch_frame_raster(frame, self._mode)))
                    except Exception:
                        results.put((frame, None))

            worker_count = min(MAX_CONCURRENT_TILE_REQUESTS, len(missing))
            for index in range(worker_count):
                threading.Thread(
                    target=fetch_worker, name=f"terrascope-radar-{index + 1}", daemon=True
                ).start()
            failed_frames = 0
            for _ in missing:
                frame, raster = results.get()
                completed += 1
                set_live_progress(
                    "radar", state="downloading", downloaded=completed,
                    total=max(1, len(frames)),
                )
                if raster is None:
                    failed_frames += 1
                    continue
                with self._lock:
                    self._rasters[frame["time"]] = raster
                self._save_raster(frame, raster)
                self._save_cache()
                if self._on_update is not None:
                    self._on_update()
            with self._lock:
                self._failed = not self._rasters or failed_frames > 0
                self._using_cache = self._failed
                self._checked_at = time.time()
            error = (
                "Some radar frames could not be downloaded" if failed_frames
                else "No radar frames could be downloaded" if not self._rasters
                else ""
            )
            set_live_progress(
                "radar", state="failed" if self._failed else "ready",
                downloaded=completed, total=max(1, len(frames)), error=error,
            )
        except Exception as error:
            set_live_progress("radar", state="failed", error=str(error))
            self.mark_failed(str(error))
        finally:
            with self._lock:
                self._busy = False
            if self._on_update is not None:
                self._on_update()

# ---------------------------------------------------------------------------
# Geometry: map a lon/lat sampling grid onto raster pixels (Web Mercator)
# ---------------------------------------------------------------------------

_MERCATOR_MAX_LAT = 85.0511

def sample_raster(raster: np.ndarray, view: View) -> np.ndarray:
    """Radar intensity (float32, 0 = nothing) for every HALF terminal cell of the
    view, as an array of shape (2 * height, width): row 2*y is the top half of
    terminal row y, row 2*y + 1 its bottom half.

    The sampling points are laid out on the view's own cell grid (not on a fixed
    lon/lat grid), so cells and samples can never beat against each other. Each
    half-cell is the mean of SUPERSAMPLE x SUPERSAMPLE bilinear samples of the
    Web-Mercator raster."""
    size = raster.shape[0]
    columns = view.width * SUPERSAMPLE
    rows = view.height * 2 * SUPERSAMPLE
    lons = view.origin_lon + (np.arange(columns) + 0.5) / columns * view.lon_span
    lats = view.origin_lat - (np.arange(rows) + 0.5) / rows * view.lat_span
    inside = np.abs(lats) < _MERCATOR_MAX_LAT
    radians = np.radians(np.clip(lats, -_MERCATOR_MAX_LAT, _MERCATOR_MAX_LAT))
    mercator_y = np.log(np.tan(radians) + 1.0 / np.cos(radians))
    u = ((lons + 180.0) % 360.0) / 360.0 * size - 0.5  # raster column (pixel centres at .0)
    v = (1.0 - mercator_y / np.pi) / 2.0 * size - 0.5  # raster row
    x0 = np.floor(u).astype(np.int64)
    y0 = np.floor(v).astype(np.int64)
    fx = (u - x0).astype(np.float32)[None, :]
    fy = (v - y0).astype(np.float32)[:, None]
    x0w, x1w = x0 % size, (x0 + 1) % size  # longitude wraps terrascope
    y0c, y1c = np.clip(y0, 0, size - 1), np.clip(y0 + 1, 0, size - 1)
    top = raster[y0c[:, None], x0w[None, :]] * (1 - fx) + raster[y0c[:, None], x1w[None, :]] * fx
    bottom = raster[y1c[:, None], x0w[None, :]] * (1 - fx) + raster[y1c[:, None], x1w[None, :]] * fx
    values = top * (1 - fy) + bottom * fy
    values[~inside, :] = 0.0
    return values.reshape(view.height * 2, SUPERSAMPLE, view.width, SUPERSAMPLE).mean(axis=(1, 3))

# ---------------------------------------------------------------------------
# Earthquakes (USGS)
# ---------------------------------------------------------------------------
