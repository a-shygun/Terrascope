"""Solar and lunar position calculations used by the day/night layer."""

from __future__ import annotations

import math
from datetime import datetime, timezone

SYNODIC_MONTH_DAYS = 29.530588853

MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)

MOON_PHASE_NAMES = (
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
)

SUN_PHASES = (
    (0.0, "Day"),
    (-6.0, "Civil twilight"),
    (-12.0, "Nautical twilight"),
    (-18.0, "Astronomical twilight"),
)

SUN_NIGHT = "Night"

SUNRISE_ELEVATION = -0.833

def julian_day(now: datetime) -> float:
    """Julian Day Number for a UTC datetime (Meeus, ch. 7)."""
    year, month = now.year, now.month
    day = now.day + (now.hour + now.minute / 60 + now.second / 3600) / 24
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return int(365.25 * (year + 4716)) + int(30.6001 * (month + 1)) + day + b - 1524.5

def solar_position(now: datetime) -> tuple[float, float]:
    """(declination in radians, equation of time in minutes).

    Accurate to roughly 0.01°. Depends only on time, so it is computed once
    and shared by the map shading and the info box."""
    T = (julian_day(now) - 2451545.0) / 36525.0  # Julian centuries since J2000.0
    L0 = math.radians((280.46646 + T * (36000.76983 + T * 0.0003032)) % 360)
    M = math.radians(357.52911 + T * (35999.05029 - 0.0001537 * T))
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    center = (
        math.sin(M) * (1.914602 - T * (0.004817 + 0.000014 * T))
        + math.sin(2 * M) * (0.019993 - 0.000101 * T)
        + math.sin(3 * M) * 0.000289
    )
    omega = math.radians(125.04 - 1934.136 * T)
    apparent = math.radians(
        math.degrees(L0) + center - 0.00569 - 0.00478 * math.sin(omega)
    )
    obliquity = math.radians(
        23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
        + 0.00256 * math.cos(omega)
    )
    declination = math.asin(math.sin(obliquity) * math.sin(apparent))
    y = math.tan(obliquity / 2) ** 2
    eq_time = 4 * math.degrees(
        y * math.sin(2 * L0)
        - 2 * e * math.sin(M)
        + 4 * e * y * math.sin(M) * math.cos(2 * L0)
        - 0.5 * y * y * math.sin(4 * L0)
        - 1.25 * e * e * math.sin(2 * M)
    )
    return declination, eq_time

def sun_elevation(lat: float, lon: float, now: datetime, declination: float, eq_time: float) -> float:
    minutes = now.hour * 60 + now.minute + now.second / 60
    solar_minutes = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = math.radians(solar_minutes / 4 - 180)
    phi = math.radians(lat)
    cosine = math.sin(phi) * math.sin(declination) + math.cos(phi) * math.cos(
        declination
    ) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, cosine))))

def sunrise_sunset(lat: float, lon: float, declination: float, eq_time: float):
    """(sunrise, sunset) as minutes after 00:00 UTC, or the string "polar day" /
    "polar night" where the sun never sets / rises."""
    phi = math.radians(lat)
    cos_h = (
        math.sin(math.radians(SUNRISE_ELEVATION)) - math.sin(phi) * math.sin(declination)
    ) / (math.cos(phi) * math.cos(declination) or 1e-9)
    if cos_h <= -1:
        return "polar day"
    if cos_h >= 1:
        return "polar night"
    half_day = math.degrees(math.acos(cos_h))  # degrees of hour angle
    noon = 720 - 4 * lon - eq_time
    return (noon - 4 * half_day) % 1440, (noon + 4 * half_day) % 1440

def sun_phase_name(elevation: float) -> str:
    for threshold, name in SUN_PHASES:
        if elevation >= threshold:
            return name
    return SUN_NIGHT

def moon_info(now: datetime) -> dict:
    age = ((now - MOON_EPOCH).total_seconds() / 86400) % SYNODIC_MONTH_DAYS
    fraction = age / SYNODIC_MONTH_DAYS
    return {
        "name": MOON_PHASE_NAMES[int(fraction * 8 + 0.5) % 8],
        "illumination": (1 - math.cos(2 * math.pi * fraction)) / 2,
        "age": age,
        "to_new": SYNODIC_MONTH_DAYS - age,
        "to_full": (SYNODIC_MONTH_DAYS / 2 - age) % SYNODIC_MONTH_DAYS,
    }

def hhmm(minutes: float) -> str:
    minutes = round(minutes) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"

def format_hemisphere(value: float, positive: str, negative: str) -> str:
    return f"{abs(value):.1f}\u00b0{positive if value >= 0 else negative}"
