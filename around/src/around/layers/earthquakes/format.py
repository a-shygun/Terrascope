from __future__ import annotations

import time

from around.layers.earthquakes.settings import (
    ALERT_COLORS,
    MAGNITUDE_COLOR_BANDS,
    MAGNITUDE_COLOR_MAJOR,
    MAGNITUDE_COLOR_UNKNOWN,
)


def magnitude_to_color(magnitude) -> str:
    if magnitude is None:
        return MAGNITUDE_COLOR_UNKNOWN
    for threshold, color in MAGNITUDE_COLOR_BANDS:
        if magnitude < threshold:
            return color
    return MAGNITUDE_COLOR_MAJOR


def magnitude_to_glyph(magnitude) -> str:
    if magnitude is None:
        return "•"
    if magnitude < 4.5:
        return "•"
    if magnitude < 6.0:
        return "◆"
    return "★"


def format_magnitude(magnitude) -> str:
    if magnitude is None:
        return "N/A"
    return f"M {magnitude:.1f}"


def format_depth(depth_km) -> str:
    if depth_km is None:
        return "N/A"
    return f"{depth_km:.1f} km"


def format_time_ago(epoch_ms) -> str:
    if epoch_ms is None:
        return "N/A"
    try:
        seconds_ago = max(0.0, time.time() - float(epoch_ms) / 1000.0)
    except (TypeError, ValueError):
        return "N/A"
    if seconds_ago < 3600:
        return f"{seconds_ago / 60:.0f}m ago"
    if seconds_ago < 86400:
        return f"{seconds_ago / 3600:.1f}h ago"
    return f"{seconds_ago / 86400:.1f}d ago"


def format_tsunami(flag: bool) -> str:
    return "WARNING" if flag else "NO"


def alert_to_color(alert) -> str:
    if not alert:
        return "#888888"
    return ALERT_COLORS.get(str(alert).lower(), "#888888")
