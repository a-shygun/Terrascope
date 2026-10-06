"""Terminal layout, controls, and dropdown drawing helpers."""

from __future__ import annotations

from .constants import (
    BOX_GAP,
    CONTROLS_COLLAPSED_BUTTON,
    CONTROLS_EXPANDED_BUTTON,
    CONTROLS_GAP,
    DEFAULT_PANEL_LAYOUT,
    DROPDOWN_ACTIVE_MARK,
    DROPDOWN_INACTIVE_MARK,
    DROPDOWN_MAX_HEIGHT,
    DROPDOWN_MARGIN_X,
    DROPDOWN_MARGIN_Y,
    DROPDOWN_MIN_HEIGHT,
    DROPDOWN_NO_MATCH,
    DROPDOWN_PADDING_X,
    DROPDOWN_PADDING_Y,
    DROPDOWN_PLACEHOLDER,
    DROPDOWN_TITLE,
    DROPDOWN_WIDTH,
    HELP_ITEMS,
    HELP_MIN_GAP,
    HELP_SEPARATOR,
    HELP_SHORT_KEYS,
    LAYER_BAR_HEIGHT,
    LAYER_TAB_GAP,
    Layer,
    MODAL_BG_COLOR,
    MODAL_BORDER_COLOR,
    MODAL_DIM_COLOR,
    MODAL_MARGIN_X,
    MODAL_MARGIN_Y,
    MODAL_PADDING_X,
    MODAL_PADDING_Y,
    MODAL_TEXT_COLOR,
    OUTER_MARGIN,
    PANEL_HEIGHT,
    PANEL_MIN_HEIGHT,
    PANEL_MIN_MAP_HEIGHT,
    PANEL_WIDTH,
    PanelBox,
    Rect,
    TIMEZONE_OPTIONS,
    ZoneInfo,
    ZoneInfoNotFoundError,
    _BOX,
    _IGNORED_ZONE_PREFIXES,
    available_timezones,
    curses,
    dataclass,
    datetime,
    lru_cache,
    replace,
    timezone
)

def safe_addstr(window, y: int, x: int, text: str, attributes: int = 0) -> None:
    try:
        window.addnstr(y, x, text, max(0, window.getmaxyx()[1] - x - 1), attributes)
    except curses.error:
        pass

def concise_error_message(error: str, limit: int = 42) -> str:
    """Turn common transport errors into short status text for the TUI."""
    text = " ".join(str(error).split())
    lowered = text.lower()
    if any(token in lowered for token in (
        "nodename nor servname", "name or service not known",
        "temporary failure in name resolution", "getaddrinfo failed",
    )):
        text = "network/DNS unavailable"
    elif "timed out" in lowered or "timeout" in lowered:
        text = "request timed out"
    elif "http error" in lowered:
        detail = text.lower().split("http error", 1)[1].strip()
        code = detail.split(":", 1)[0].strip()
        text = f"HTTP {code}"
    elif text.lower().startswith("could not download "):
        text = "download failed"
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text

def draw_box(window, top: int, left: int, height: int, width: int, title: str) -> None:
    if height < 2 or width < 2:
        return
    horizontal = _BOX["horizontal"] * (width - 2)
    safe_addstr(window, top, left, _BOX["top_left"] + horizontal + _BOX["top_right"])
    for row in range(top + 1, top + height - 1):
        safe_addstr(window, row, left, _BOX["vertical"])
        safe_addstr(window, row, left + width - 1, _BOX["vertical"])
    safe_addstr(
        window,
        top + height - 1,
        left,
        _BOX["bottom_left"] + horizontal + _BOX["bottom_right"],
    )
    if title:
        title_text = f" {title} "
        if len(title_text) < width - 2:
            safe_addstr(window, top, left + 2, title_text)

def _draw_filled_box(
    window, top: int, left: int, height: int, width: int, title: str, pair: int
) -> None:
    """Draw a modal outline over spaces using the terminal's default background."""
    blank = " " * width
    for row in range(top, top + height):
        safe_addstr(window, row, left, blank, pair)
    if height < 2 or width < 2:
        return
    horizontal = _BOX["horizontal"] * (width - 2)
    safe_addstr(window, top, left, _BOX["top_left"] + horizontal + _BOX["top_right"], pair)
    for row in range(top + 1, top + height - 1):
        safe_addstr(window, row, left, _BOX["vertical"], pair)
        safe_addstr(window, row, left + width - 1, _BOX["vertical"], pair)
    safe_addstr(
        window,
        top + height - 1,
        left,
        _BOX["bottom_left"] + horizontal + _BOX["bottom_right"],
        pair,
    )
    if title:
        title_text = f" {title} "
        if len(title_text) < width - 2:
            safe_addstr(window, top, left + 2, title_text, pair | curses.A_BOLD)

def _draw_modal_frame(
    window, top: int, left: int, height: int, width: int, title: str, colors,
    margin_x: int = MODAL_MARGIN_X, margin_y: int = MODAL_MARGIN_Y,
) -> None:
    """Draw a white modal outline over the terminal's default background."""
    screen_height, screen_width = window.getmaxyx()
    margin_pair = colors.get_pair(MODAL_TEXT_COLOR, MODAL_BG_COLOR)
    first_col = max(0, left - margin_x)
    last_col = min(screen_width, left + width + margin_x)
    blank = " " * max(0, last_col - first_col)
    for row in range(
        max(0, top - margin_y), min(screen_height, top + height + margin_y)
    ):
        safe_addstr(window, row, first_col, blank, margin_pair)
    card_pair = colors.get_pair(MODAL_BORDER_COLOR, MODAL_BG_COLOR)
    _draw_filled_box(window, top, left, height, width, title, card_pair)

@dataclass
class Layout:
    map: Rect
    # (box, rect) for every box of the bottom row; empty = panel hidden.
    boxes: tuple[tuple[PanelBox, Rect], ...] = ()
    tabs: Rect | None = None  # top row with the clickable layer tabs

    def rect_of(self, kind: str) -> Rect | None:
        return next((rect for box, rect in self.boxes if box.kind == kind), None)

    @property

    def info(self) -> Rect | None:
        return self.rect_of("info")

def compute_layout(
    height: int, width: int, panel_visible: bool, owner: Layer | None = None,
    panel_layout: tuple[PanelBox, ...] | None = None,
    panel_orientation: str = "horizontal",
) -> Layout:
    """Split the terminal into a map and optional bottom or left-side panel.
    `owner` supplies the active layer's panel layout. Shared by drawing and
    mouse handling so the two can never disagree."""
    margin_x, margin_y = OUTER_MARGIN
    box_width = width - margin_x * 2
    tab_height = LAYER_BAR_HEIGHT
    total_height = height - margin_y * 2 - tab_height
    tabs_rect = (margin_y, margin_x, tab_height, box_width)
    map_top = margin_y + tab_height
    spec = panel_layout or (owner.panel_layout if owner is not None else None) or DEFAULT_PANEL_LAYOUT
    if panel_visible and panel_orientation == "vertical":
        panel_width = min(PANEL_WIDTH, box_width - 28)
        if panel_width >= 16 and total_height >= PANEL_MIN_MAP_HEIGHT:
            map_left = margin_x + panel_width + BOX_GAP
            map_width = box_width - panel_width - BOX_GAP
            map_rect = (map_top, map_left, total_height, map_width)
            panel_left = margin_x
            panel_inner_height = total_height
            boxes = []
            top = map_top
            for index, box in enumerate(spec):
                box_height = (
                    panel_inner_height - sum(rect[2] for _, rect in boxes)
                    if index == len(spec) - 1
                    else max(1, int(panel_inner_height * box.ratio))
                )
                boxes.append((box, (top, panel_left, box_height, panel_width)))
                top += box_height
            return Layout(map_rect, tuple(boxes), tabs_rect)
    panel_height = 0
    if panel_visible:
        panel_height = min(PANEL_HEIGHT, total_height - PANEL_MIN_MAP_HEIGHT)
        if panel_height < PANEL_MIN_HEIGHT:
            panel_height = 0  # terminal too short: the map keeps all the room
    map_height = total_height - panel_height
    map_rect = (map_top, margin_x, map_height, box_width)
    if panel_height == 0:
        return Layout(map_rect, (), tabs_rect)
    top = map_top + map_height
    boxes = []
    left = margin_x
    right_edge = margin_x + box_width
    for index, box in enumerate(spec):
        if index == len(spec) - 1:
            box_w = right_edge - left  # last box takes the remainder
            drawn_w = box_w
        else:
            box_w = max(1, int(box_width * box.ratio))
            drawn_w = max(1, box_w - BOX_GAP)
        if box_w < 1:
            break
        boxes.append((box, (top, left, panel_height, drawn_w)))
        left += box_w
    return Layout(map_rect, tuple(boxes), tabs_rect)

def tab_slots(tabs, left: int, width: int) -> list[tuple[int, int, str]]:
    """(tab index, screen x, text) for every tab that fits in the bar.

    Shared by drawing and mouse handling so the two can never disagree."""
    slots = []
    x = left
    for index, tab in enumerate(tabs):
        text = f" {index + 1} {tab.label} "
        if x + len(text) > left + width:
            break
        slots.append((index, x, text))
        x += len(text) + LAYER_TAB_GAP
    return slots

def draw_tab_bar(
    window, rect: Rect, tabs, active: int, colors, controls_expanded: bool,
    time_text: str, panel_orientation: str = "horizontal",
) -> ControlsLayout | None:
    """Top row: one numbered tab per entry in tabs.py; the active one is lit.
    Returns the controls bar's layout (for click handling), or None if there
    was no room to draw it."""
    top, left, height, width = rect
    if height < 1:
        return None
    for index, x, text in tab_slots(tabs, left, width):
        attrs = colors.get_pair(tabs[index].color)
        if index == active:
            attrs |= curses.A_REVERSE | curses.A_BOLD
        else:
            attrs |= curses.A_DIM
        safe_addstr(window, top, x, text, attrs)
    slots = tab_slots(tabs, left, width)
    tabs_end = (slots[-1][1] + len(slots[-1][2])) if slots else left
    return draw_controls_bar(
        window, rect, tabs_end, controls_expanded, time_text, panel_orientation
    )

def _help_segments(level: int) -> list[tuple[str, bool, str | None]]:
    """(text, bold, click action) pieces of the key hints. level 0 = full
    wording, 1 = short key names, 2 = keys only. The action is set on the
    pieces of a clickable hint ("about", "quit"), else None."""
    segments: list[tuple[str, bool, str | None]] = []
    for index, (key, meaning, action) in enumerate(HELP_ITEMS):
        if index:
            segments.append((HELP_SEPARATOR if level < 2 else " ", False, None))
        if level >= 1:
            key = HELP_SHORT_KEYS.get(key, key)
        segments.append((key, True, action))
        if level < 2:
            segments.append((" " + meaning, False, action))
    return segments

def draw_help_bar(
    window, top: int, tabs_end: int, right: int
) -> tuple[tuple[str, int, int], ...]:
    """Key hints, right-aligned at `right`; the fullest version that fits in
    the room left of the tabs is used (nothing if none fits). Returns the
    clickable hints as (action, screen x, width)."""
    room = right - tabs_end - HELP_MIN_GAP
    for level in range(3):
        segments = _help_segments(level)
        total = sum(len(text) for text, _, _ in segments)
        if total <= room:
            x = right - total
            spans: dict[str, tuple[int, int]] = {}
            for text, bold, action in segments:
                safe_addstr(window, top, x, text, curses.A_BOLD if bold else curses.A_DIM)
                if action:
                    start = spans.get(action, (x, x))[0]
                    spans[action] = (start, x + len(text))
                x += len(text)
            return tuple((action, start, end - start) for action, (start, end) in spans.items())
    return ()

@dataclass
class ControlsLayout:
    """Clickable columns of the controls bar. Shared by drawing and mouse
    handling so the two can never disagree."""

    datetime_x: int
    datetime_width: int
    button_x: int
    button_width: int
    orientation_x: int = 0
    orientation_width: int = 0
    help_hits: tuple[tuple[str, int, int], ...] = ()

def controls_bar_slots(
    tabs_end: int, right: int, time_text: str,
    expanded: bool = False, panel_orientation: str = "horizontal",
) -> ControlsLayout | None:
    button_width = len(CONTROLS_COLLAPSED_BUTTON)
    datetime_width = len(time_text)
    datetime_x = right - datetime_width
    orientation_text = "PANEL: LEFT" if panel_orientation == "vertical" else "PANEL: BOTTOM"
    orientation_width = len(orientation_text) if expanded else 0
    orientation_x = datetime_x - CONTROLS_GAP - orientation_width
    button_x = orientation_x - (CONTROLS_GAP if expanded else 0) - button_width
    if button_x < tabs_end:
        return None  # no room: draw nothing rather than overlap the tabs
    return ControlsLayout(
        datetime_x, datetime_width, button_x, button_width,
        orientation_x, orientation_width,
    )

def draw_controls_bar(
    window, rect: Rect, tabs_end: int, expanded: bool, time_text: str,
    panel_orientation: str = "horizontal",
) -> ControlsLayout | None:
    top, left, _height, width = rect
    right = left + width
    layout = controls_bar_slots(tabs_end, right, time_text, expanded, panel_orientation)
    if layout is None:
        return None
    help_hits: tuple[tuple[str, int, int], ...] = ()
    if expanded:
        help_hits = draw_help_bar(window, top, tabs_end, layout.button_x - CONTROLS_GAP)
    button_text = CONTROLS_EXPANDED_BUTTON if expanded else CONTROLS_COLLAPSED_BUTTON
    safe_addstr(window, top, layout.button_x, button_text, curses.A_DIM)
    if expanded:
        orientation_text = "PANEL: LEFT" if panel_orientation == "vertical" else "PANEL: BOTTOM"
        safe_addstr(window, top, layout.orientation_x, orientation_text, curses.A_BOLD | curses.A_DIM)
    safe_addstr(window, top, layout.datetime_x, time_text, curses.A_BOLD)
    return replace(layout, help_hits=help_hits)

def _all_timezone_choices() -> tuple[tuple[str, str | None], ...]:
    """The short curated list first, then every other IANA zone the system
    knows (label = zone name with underscores shown as spaces)."""
    known = {name for _, name in TIMEZONE_OPTIONS if name}
    try:
        zones = sorted(available_timezones())
    except Exception:  # no tz database on this system: curated list only
        zones = []
    extra = tuple(
        (name.replace("_", " "), name)
        for name in zones
        if "/" in name
        and name not in known
        and not name.startswith(_IGNORED_ZONE_PREFIXES)
    )
    return TIMEZONE_OPTIONS + extra

def timezone_choices(query: str) -> list[tuple[str, str | None]]:
    """(label, IANA zone or None for local) entries to list. Nothing typed =
    every zone (the common ones from TIMEZONE_OPTIONS first, then the rest
    A-Z); otherwise the zones matching the query, word-prefix matches
    ("hel" -> Helsinki) before plain substring matches."""
    needle = query.strip().lower()
    if not needle:
        return list(_all_timezone_choices())
    starts = []
    rest = []
    for label, name in _all_timezone_choices():
        text = f"{label} {name or ''}".lower()
        words = text.replace("/", " ").replace("_", " ").split()
        if text.startswith(needle) or any(word.startswith(needle) for word in words):
            starts.append((label, name))
        elif needle in text:
            rest.append((label, name))
    return starts + rest

def current_time_text(timezone_name: str | None) -> str:
    """YYYY-MM-DD HH:MM:SS plus a short zone label, for the chosen timezone
    (None = local system time)."""
    try:
        now = datetime.now(ZoneInfo(timezone_name)) if timezone_name else datetime.now().astimezone()
        label = now.tzname() or timezone_name or ""
    except (ZoneInfoNotFoundError, ValueError, OSError):
        now = datetime.now(timezone.utc)
        label = "UTC"
    return f"{now:%Y-%m-%d} {now:%H:%M:%S} {label}".rstrip()

@dataclass
class DropdownLayout:
    rect: Rect
    option_rows: tuple[int, ...]  # screen row of each listed entry, top to bottom
    first_index: int

def dropdown_rect(anchor_top: int, anchor_right: int, screen_height: int, screen_width: int) -> Rect:
    """Box just under the clock, right-aligned under it, leaving the modal margin
    free terrascope it. Shared by drawing and mouse handling so the two can never
    disagree."""
    width = max(10, min(DROPDOWN_WIDTH, screen_width - 2 * DROPDOWN_MARGIN_X))
    top = anchor_top + DROPDOWN_MARGIN_Y
    room = screen_height - top - DROPDOWN_MARGIN_Y - 1
    height = max(DROPDOWN_MIN_HEIGHT, min(DROPDOWN_MAX_HEIGHT, room))
    left = max(DROPDOWN_MARGIN_X, min(screen_width - width - DROPDOWN_MARGIN_X, anchor_right - width))
    return top, left, height, width

def _dropdown_list_rows(height: int) -> int:
    # border (2) + padding (top and bottom) + search row + rule row
    return max(0, height - 2 - 2 * DROPDOWN_PADDING_Y - 2)

def dropdown_first_index(cursor: int, visible: int, total: int) -> int:
    """First listed entry so the highlighted one is always on screen."""
    if visible <= 0 or total <= visible:
        return 0
    return max(0, min(cursor - visible + 1, total - visible))

def draw_dropdown(
    window,
    rect: Rect,
    selected_timezone: str | None,
    colors,
    query: str = "",
    cursor: int = 0,
) -> DropdownLayout:
    top, left, height, width = rect
    _draw_modal_frame(
        window, top, left, height, width, DROPDOWN_TITLE, colors,
        DROPDOWN_MARGIN_X, DROPDOWN_MARGIN_Y,
    )
    text_pair = colors.get_pair(MODAL_TEXT_COLOR, MODAL_BG_COLOR)
    dim_pair = colors.get_pair(MODAL_DIM_COLOR, MODAL_BG_COLOR)
    x = left + 1 + DROPDOWN_PADDING_X
    inner = max(1, width - 2 - 2 * DROPDOWN_PADDING_X)
    y = top + 1 + DROPDOWN_PADDING_Y

    # Search row.
    if query:
        shown = ("> " + query + "\u2588")[-inner:]
        safe_addstr(window, y, x, shown.ljust(inner), text_pair | curses.A_BOLD)
    else:
        safe_addstr(window, y, x, DROPDOWN_PLACEHOLDER[:inner].ljust(inner), dim_pair)
    y += 1

    choices = timezone_choices(query)
    total = len(choices)
    cursor = max(0, min(cursor, total - 1)) if total else 0

    # Rule row, with the position in the list on its right.
    counter = f" {cursor + 1}/{total} " if total else " 0 "
    if len(counter) < inner:
        rule = _BOX["horizontal"] * (inner - len(counter)) + counter
    else:
        rule = counter[:inner]
    safe_addstr(window, y, x, rule, dim_pair)
    y += 1

    # The list.
    rows = _dropdown_list_rows(height)
    first = dropdown_first_index(cursor, rows, total)
    option_rows = []
    if not total:
        safe_addstr(window, y, x, DROPDOWN_NO_MATCH.ljust(inner), dim_pair)
    for offset in range(min(rows, max(0, total - first))):
        index = first + offset
        label, tz_name = choices[index]
        mark = DROPDOWN_ACTIVE_MARK if tz_name == selected_timezone else DROPDOWN_INACTIVE_MARK
        text = (mark + label)[:inner].ljust(inner)
        attrs = text_pair | (curses.A_REVERSE if index == cursor else 0)
        safe_addstr(window, y + offset, x, text, attrs)
        option_rows.append(y + offset)
    return DropdownLayout((top, left, height, width), tuple(option_rows), first)
