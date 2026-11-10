# i18n.py — LANGUAGE, TRANSLATION AND REGIONAL FORMATS
# Responsible for: choosing the interface language, looking up translated
# strings (gettext, domain "terrascope"), and the regional formats that depend
# on it (24/12 h clock, date order, decimal separator, °C/°F, km/h/mph).
#
# Language is chosen in this order, the first usable value wins:
#   1. --lang (cli.py calls activate() with it before anything else),
#   2. app.language in the config ("auto" means: keep looking),
#   3. the environment: LANGUAGE, LC_ALL, LC_MESSAGES, LANG,
#   4. the Windows interface language (GetUserDefaultUILanguage),
#   5. English.
# A language is only used when its catalogue is installed (locale/<lang>/
# LC_MESSAGES/terrascope.mo); otherwise the next candidate applies, and the
# base language is tried too (pt_PT uses pt_BR). English needs no catalogue.
#
# Regional formats follow the language (_REGIONAL_DEFAULTS). app.time_format
# and app.units override them: "auto" keeps the language's choice.
#
# Edit this file to: add a language's default formats, or change the
# resolution order. Strings are marked with _() where they are used; the
# texts that live in default.yaml are listed in YAML_TEXTS below.

from __future__ import annotations

import gettext
import locale
import os
import sys
from datetime import date, datetime
from pathlib import Path

from terrascope.core import config

DOMAIN = "terrascope"
# terrascope_LOCALE_DIR (like terrascope_CONFIG) points at another catalogue
# folder; tools/pseudo_locale.py uses it to test layouts without touching the repo.
LOCALE_DIR = Path(os.environ.get("terrascope_LOCALE_DIR") or Path(__file__).resolve().parents[1] / "locale")
DEFAULT_LANGUAGE = "en"

# Per base language (the part before "_"). "en" is also the fallback.
_REGIONAL_DEFAULTS = {
    "en": {"time_format": "24h", "units": "metric", "decimal": ".", "thousands": ",",
           "date": "%Y-%m-%d", "month_day": "%m-%d"},
    "pt": {"time_format": "24h", "units": "metric", "decimal": ",", "thousands": ".",
           "date": "%d/%m/%Y", "month_day": "%d/%m"},
}
_CHOICES = {"time_format": ("24h", "12h"), "units": ("metric", "imperial")}

_state: dict = {"language": DEFAULT_LANGUAGE, "catalog": gettext.NullTranslations(), "activated": False}


def N_(message: str) -> str:
    """Marks a string that is kept as data (default.yaml) so pybabel extract
    finds it. Returns the text unchanged."""
    return message


# Texts that come from default.yaml: tab labels and blurbs, and timezone labels.
# The runtime translates them on load with _(), using the English text as the
# key. tests/test_i18n.py checks that this list covers every such text.
YAML_TEXTS = (
    # Keys the app compares in English but shows translated (see dialogs.py).
    N_("SETUP COMPLETE"),
    N_("MAP"), N_("TIME"), N_("WEATHER"), N_("PLANES"),
    N_("the plain world map (zoom in for state / province borders and detailed cities)"),
    N_("clock, sun phases, moon phase and the day/night line"),
    N_("city temperatures, earthquakes, clouds and storms"),
    N_("live aircraft"),
    N_("UTC"), N_("Local"), N_("Paris / Berlin"), N_("Helsinki / Athens"), N_("Moscow"), N_("Dubai"),
    N_("Mumbai"), N_("Shanghai / Singapore"), N_("Tokyo / Seoul"), N_("Sydney"),
    N_("New York"), N_("Chicago"), N_("Denver"), N_("Los Angeles"), N_("London"),
)


def _normalize(name) -> str | None:
    """'pt-BR', 'pt_BR.UTF-8' and 'pt_BR:en' all give 'pt_BR'; 'C', 'POSIX' and
    empty values give None."""
    if not name:
        return None
    text = str(name).strip().split(":")[0].split(".")[0].split("@")[0].replace("-", "_")
    if not text or text.upper() in {"C", "POSIX"} or text.lower() == "auto":
        return None
    parts = text.split("_")
    base = parts[0].lower()
    if len(parts) > 1 and parts[1]:
        return f"{base}_{parts[1].upper()}"
    return base


def available_languages() -> tuple[str, ...]:
    """English plus every language with an installed catalogue."""
    found = {DEFAULT_LANGUAGE}
    if LOCALE_DIR.is_dir():
        for path in LOCALE_DIR.glob(f"*/LC_MESSAGES/{DOMAIN}.mo"):
            found.add(path.parent.parent.name)
    return tuple(sorted(found))


def _match(requested: str | None) -> str | None:
    """The installed language for a requested one: the same name, then the same
    base language, else None."""
    if not requested:
        return None
    available = available_languages()
    if requested in available:
        return requested
    base = requested.split("_")[0]
    return next((name for name in available if name.split("_")[0] == base), None)


def is_supported(requested: str) -> bool:
    """True when `requested` (e.g. "pt_BR" or "pt-BR") has an installed catalogue."""
    name = _normalize(requested)
    return name is not None and _match(name) is not None


def _windows_ui_language() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        lcid = kernel32.GetUserDefaultUILanguage()
        buffer = ctypes.create_unicode_buffer(85)
        if kernel32.LCIDToLocaleName(lcid, buffer, len(buffer), 0):
            return buffer.value  # e.g. "pt-BR"
    except Exception:
        return None
    return None


def _system_language() -> str | None:
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = _normalize(os.environ.get(name))
        if value:
            return value
    windows = _normalize(_windows_ui_language())
    if windows:
        return windows
    try:
        return _normalize(locale.getlocale()[0])
    except Exception:
        return None


def _config_language() -> str | None:
    return _normalize(config.get_path("app.language", "auto"))


def _load(language: str) -> None:
    catalog = gettext.NullTranslations()
    if language != DEFAULT_LANGUAGE:
        catalog = gettext.translation(DOMAIN, localedir=str(LOCALE_DIR), languages=[language], fallback=True)
    _state.update(language=language, catalog=catalog, activated=True)


def activate(requested: str | None = None) -> str:
    """Choose the interface language (see the order at the top of this file),
    load its catalogue and return its name. Safe to call again: the last call
    wins, so cli.py calls it once before the parser and once after the
    config files are merged."""
    chosen = _match(_normalize(requested)) or _match(_config_language()) \
        or _match(_system_language()) or DEFAULT_LANGUAGE
    _load(chosen)
    return chosen


def language() -> str:
    """The active language, such as "en" or "pt_BR"."""
    if not _state["activated"]:
        activate()
    return _state["language"]


def _(message: str) -> str:
    """The translation of `message` in the active language (English if none)."""
    if not message:  # gettext("") would return the catalogue header
        return message
    if not _state["activated"]:
        activate()
    return _state["catalog"].gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Singular or plural form for `n`, in the active language."""
    if not _state["activated"]:
        activate()
    return _state["catalog"].ngettext(singular, plural, n)


def translation(domain: str, localedir: str | os.PathLike) -> gettext.NullTranslations:
    """Catalogue of another domain (e.g. "terrascope_br") in the active
    language, with English (no translation) as fallback."""
    if not _state["activated"]:
        activate()
    return gettext.translation(
        domain, localedir=str(localedir), languages=[_state["language"]], fallback=True
    )


# --- regional formats -----------------------------------------------------------

def _regional(key: str) -> str:
    base = language().split("_")[0]
    return _REGIONAL_DEFAULTS.get(base, _REGIONAL_DEFAULTS[DEFAULT_LANGUAGE])[key]


def _setting(key: str) -> str | None:
    value = str(config.get_path(f"app.{key}", "auto")).strip().lower()
    return value if value in _CHOICES[key] else None


def time_format() -> str:
    """"24h" or "12h": app.time_format if set, else the language's default."""
    return _setting("time_format") or _regional("time_format")


def units() -> str:
    """"metric" or "imperial": app.units if set, else the language's default."""
    return _setting("units") or _regional("units")


def decimal_separator() -> str:
    return _regional("decimal")


def format_number(value: float, decimals: int = 0) -> str:
    """12.5 -> "12,5" in pt, "12.5" in en."""
    text = f"{value:.{decimals}f}"
    separator = decimal_separator()
    return text if separator == "." else text.replace(".", separator)


def format_integer(value: float) -> str:
    """Whole number with thousands separators: "1,000" in en, "1.000" in pt."""
    text = f"{round(value):,}"
    separator = _regional("thousands")
    return text if separator == "," else text.replace(",", separator)


def format_temperature(celsius: float, decimals: int = 0, unit: bool = True) -> str:
    """"12°C" (or "54°F" under imperial). unit=False gives "12°" for compact labels."""
    if units() == "imperial":
        value, symbol = celsius * 9 / 5 + 32, "°F"
    else:
        value, symbol = celsius, "°C"
    return format_number(value, decimals) + (symbol if unit else "°")


def speed_unit() -> str:
    return "mph" if units() == "imperial" else "km/h"


def speed_value(kmh: float, decimals: int = 0) -> str:
    """The number only, in the configured units ("7" for 12 km/h under imperial).
    For places where the unit is shown once, next to another speed."""
    value = kmh * 0.621371 if units() == "imperial" else kmh
    return format_number(value, decimals)


def format_speed(kmh: float, decimals: int = 0) -> str:
    """"12 km/h", or "7 mph" under imperial."""
    return f"{speed_value(kmh, decimals)} {speed_unit()}"


def format_distance(km: float) -> str:
    """Scale-bar length: "1,000 km", "12 km", "300 m"; under imperial "8 mi",
    "980 ft", "1,200 mi"."""
    if units() == "imperial":
        miles = km * 0.621371
        if miles >= 1000:
            return f"{format_integer(miles)} mi"
        if miles >= 1:
            return f"{miles:.0f} mi"
        return f"{miles * 5280:.0f} ft"
    if km >= 1000:
        return f"{format_integer(km)} km"
    if km >= 1:
        return f"{km:.0f} km"
    return f"{km * 1000:.0f} m"


def format_clock(moment: datetime, seconds: bool = True) -> str:
    """"14:05:09", or "02:05:09 PM" when the clock is set to 12 h."""
    if time_format() == "12h":
        return moment.strftime("%I:%M:%S %p" if seconds else "%I:%M %p")
    return moment.strftime("%H:%M:%S" if seconds else "%H:%M")


def format_date(value: date | datetime) -> str:
    """"2026-11-10" in en, "10/11/2026" in pt."""
    return value.strftime(_regional("date"))


def format_month_day(value: date | datetime) -> str:
    """"11-10" in en, "10/11" in pt."""
    return value.strftime(_regional("month_day"))
