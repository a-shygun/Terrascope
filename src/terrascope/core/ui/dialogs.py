"""Welcome, selection, and information dialogs."""

from __future__ import annotations

from .colors import (
    ColorManager
)
from .constants import (
    BANNER_COLOR,
    BANNER_FILL,
    BANNER_ROWS,
    BANNER_TEXT,
    DEFAULT_INFO_TITLE,
    GITHUB_URL,
    INFO_BOX_LABEL_WIDTH,
    INFO_BOX_MIN_WIDTH,
    INFO_IMAGE_GAP,
    INFO_IMAGE_MIN_VALUE_WIDTH,
    INFO_PLACEHOLDER,
    InfoImage,
    LINK_COLOR,
    LIVE_BOX_MAX_LABEL_WIDTH,
    Layer,
    MODAL_BG_COLOR,
    MODAL_BORDER_COLOR,
    MODAL_CONTENT,
    MODAL_DIM_COLOR,
    MODAL_MARGIN_X,
    MODAL_MARGIN_Y,
    MODAL_PADDING_X,
    MODAL_PADDING_Y,
    MODAL_TEXT_COLOR,
    Rect,
    SCOPE_COLOR,
    TABS,
    TERRA_COLOR,
    UI,
    WELCOME_DISMISS_HINT,
    WELCOME_REOPEN_HINT,
    WELCOME_SKIP_BUTTON,
    WELCOME_TAGLINE,
    _BANNER_FONT,
    _BOX,
    curses,
    dataclass,
    textwrap
)
from .layout import (
    concise_error_message,
    draw_box,
    safe_addstr
)
from .map import (
    _put_clipped
)

class LinkLayout:
    row: int
    left: int
    width: int

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
    safe_addstr(window, top + height - 1, left, _BOX["bottom_left"] + horizontal + _BOX["bottom_right"], pair)
    if title:
        title_text = f" {title} "
        if len(title_text) < width - 2:
            safe_addstr(window, top, left + 2, title_text, pair | curses.A_BOLD)

def _draw_modal_frame(
    window, top: int, left: int, height: int, width: int, title: str, colors
) -> None:
    """Draw a white modal outline over the terminal's default background."""
    screen_height, screen_width = window.getmaxyx()
    margin_pair = colors.get_pair(MODAL_TEXT_COLOR, MODAL_BG_COLOR)
    first_col = max(0, left - MODAL_MARGIN_X)
    last_col = min(screen_width, left + width + MODAL_MARGIN_X)
    blank = " " * max(0, last_col - first_col)
    for row in range(
        max(0, top - MODAL_MARGIN_Y), min(screen_height, top + height + MODAL_MARGIN_Y)
    ):
        safe_addstr(window, row, first_col, blank, margin_pair)
    card_pair = colors.get_pair(MODAL_BORDER_COLOR, MODAL_BG_COLOR)
    _draw_filled_box(window, top, left, height, width, title, card_pair)

def _banner_lines(scale: int, text: str = BANNER_TEXT) -> list[str]:
    rows = ["" for _ in range(BANNER_ROWS)]
    gap = " " * scale
    for index, letter in enumerate(text):
        glyph = _BANNER_FONT[letter.upper()]
        for row in range(BANNER_ROWS):
            rows[row] += "".join(
                (BANNER_FILL if char == "X" else " ") * scale for char in glyph[row]
            )
            if index < len(text) - 1:
                rows[row] += gap
    return rows

def _flatten_modal_body() -> list[tuple[str, bool]]:
    """(text, bold) rows for the modal body, with "@tabs" expanded into one
    row per tab."""
    rows: list[tuple[str, bool]] = []
    for text, kind in MODAL_CONTENT:
        if text == "@tabs":
            for index, tab in enumerate(TABS):
                label = f" {index + 1} {tab.label}".ljust(12)
                rows.append((f"{label}{tab.blurb}", False))
            continue
        rows.append((text, kind is None and bool(text)))
    return rows

def draw_welcome_modal(
    window, screen_height: int, screen_width: int, colors, download_progress=(),
    startup_status=("SETUP COMPLETE", 100, "ready", ""),
    province_prompt: bool = False,
) -> tuple[Rect | None, LinkLayout | None, LinkLayout | None, LinkLayout | None, LinkLayout | None]:
    """Draw a compact welcome and first-run data status card."""
    if screen_height < 14 or screen_width < 30:
        return None, None, None, None, None

    compact = screen_height < 42 or screen_width < 100
    body = (
        [
            ("MAP  ·  TIME  ·  WEATHER  ·  PLANES", False),
            ("WASD / arrows pan  ·  +/- zoom  ·  click markers", False),
            ("? guide  ·  Esc close  ·  H panel  ·  Q quit", False),
        ]
        if compact
        else _flatten_modal_body()
    )
    link_text = f"GITHUB   {GITHUB_URL}"
    scale = 2 if screen_width >= max(140, int(UI["banner_wide_min_width"])) else 1
    compact_banner = screen_height < 28 or screen_width < 100
    terra_banner = ["TERRA"] if compact_banner else _banner_lines(scale, "terra")
    scope_banner = ["SCOPE"] if compact_banner else _banner_lines(scale, "scope")
    banner = [
        terra + (" " * scale) + scope
        for terra, scope in zip(terra_banner, scope_banner)
    ]
    banner_width = max(map(len, banner))
    preferred_width = max(96, banner_width + 2 + 2 * MODAL_PADDING_X + 8)
    width = max(40, min(screen_width - MODAL_MARGIN_X * 2, preferred_width))
    inner_width = max(1, width - 2 - 2 * MODAL_PADDING_X)
    wrapped_body: list[tuple[str, bool]] = []
    for text, bold in body:
        if text:
            wrapped_body.extend((line, bold) for line in textwrap.wrap(text, width=inner_width) or [""])
        else:
            wrapped_body.append(("", bold))
    body = wrapped_body
    content_rows = len(banner) + 1 + 2 + 2 + len(body) + (13 if province_prompt else 11)
    height = max(12, min(screen_height - MODAL_MARGIN_Y * 2, content_rows + 2 + MODAL_PADDING_Y * 2))
    top = max(0, (screen_height - height) // 2)
    left = max(0, (screen_width - width) // 2)

    _draw_modal_frame(window, top, left, height, width, "", colors)
    inner_left = left + 1 + MODAL_PADDING_X
    limit_x = left + width - 1 - MODAL_PADDING_X
    bottom = top + height - 1 - MODAL_PADDING_Y  # first row content may not use
    y = top + 1 + MODAL_PADDING_Y

    text_pair = colors.get_pair(MODAL_TEXT_COLOR, MODAL_BG_COLOR)
    dim_pair = colors.get_pair(MODAL_DIM_COLOR, MODAL_BG_COLOR)
    accent_pair = colors.get_pair(BANNER_COLOR, MODAL_BG_COLOR)
    terra_pair = colors.get_pair(TERRA_COLOR, MODAL_BG_COLOR)
    scope_pair = colors.get_pair(SCOPE_COLOR, MODAL_BG_COLOR)
    link_pair = colors.get_pair(LINK_COLOR, MODAL_BG_COLOR)

    def centered(text: str, attrs: int = 0) -> int:
        x = left + max(1 + MODAL_PADDING_X, (width - len(text)) // 2)
        return _put_clipped(window, y, x, text, limit_x, attrs)

    tagline = "A live world map, drawn in braille." if compact else WELCOME_TAGLINE
    banner_left = left + max(1 + MODAL_PADDING_X, (width - banner_width) // 2)
    terra_width = max(map(len, terra_banner))
    for terra_line, scope_line in zip(terra_banner, scope_banner):
        if y >= bottom:
            break
        _put_clipped(window, y, banner_left, terra_line, limit_x, curses.A_BOLD | terra_pair)
        _put_clipped(
            window, y, banner_left + terra_width + scale,
            scope_line, limit_x, curses.A_BOLD | scope_pair,
        )
        y += 1
    if y < bottom:
        centered(tagline, dim_pair)
        y += 1
    if not compact:
        y += 1
    if y < bottom:
        centered("FIRST RUN  /  DATA DOWNLOADS", curses.A_BOLD | text_pair)
        y += 1
    step_name, overall_percent, step_state, step_error = startup_status
    if step_name == "SETUP COMPLETE":
        step_label = step_name
    elif step_name == "LIVE AIRCRAFT":
        step_label = "AIRCRAFT FEED"
    elif step_name == "WEATHER RADAR":
        step_label = "PRESENT RADAR"
    elif step_name == "CITY WEATHER":
        step_label = "CITY WEATHER"
    elif step_name == "RADAR HISTORY":
        step_label = "OTHER RADAR TIMES"
    elif "admin_0_countries" in step_name:
        step_label = "WORLD MAP"
    elif "admin_1_states_provinces" in step_name:
        step_label = "DETAILED BORDERS"
    elif "populated_places" in step_name:
        step_label = "DETAILED CITIES"
    elif "airports" in step_name:
        step_label = "AIRPORTS"
    else:
        step_label = step_name.removeprefix("ne_").replace(".geojson", "").replace("_", " ").upper()
    state_label = {
        "waiting": "QUEUED",
        "downloading": "DOWNLOADING",
        "failed": "FAILED",
        "ready": "READY",
    }.get(step_state, step_state.upper())
    radar_unavailable = step_name == "WEATHER RADAR" and step_state == "failed"
    headline = "RADAR UNAVAILABLE" if radar_unavailable else f"{state_label}  /  {step_label}"
    if step_error and not radar_unavailable:
        headline += f"  ·  {concise_error_message(step_error, 34)}"
    if y < bottom:
        headline_x = left + max(1 + MODAL_PADDING_X, (width - len(headline)) // 2)
        _put_clipped(
            window, y, headline_x, headline, limit_x,
            (curses.A_BOLD if step_state == "failed" else 0) | text_pair,
        )
        y += 1
    if y < bottom:
        percent_text = f"{overall_percent:3d}%"
        track_width = max(1, limit_x - inner_left - len(percent_text) - 5)
        filled = round(track_width * max(0, min(100, overall_percent)) / 100)
        bar = "[" + "=" * filled + "-" * (track_width - filled) + "]"
        line_width = len(bar) + 1 + len(percent_text)
        line_x = left + max(1 + MODAL_PADDING_X, (width - line_width) // 2)
        _put_clipped(window, y, line_x, bar, limit_x, dim_pair)
        _put_clipped(window, y, line_x + 1, "=" * filled, limit_x, accent_pair)
        _put_clipped(
            window, y, line_x + len(bar) + 1,
            percent_text, limit_x, text_pair,
        )
        y += 1
    if not compact:
        y += 1

    for text, bold in body:
        if y >= bottom:
            break
        if text:
            x = left + max(1 + MODAL_PADDING_X, (width - len(text)) // 2)
            _put_clipped(window, y, x, text, limit_x, text_pair | (curses.A_BOLD if bold else 0))
        y += 1
    if not compact:
        y += 1

    link_layout = None
    if y < bottom:
        x = left + max(1 + MODAL_PADDING_X, (width - len(link_text)) // 2)
        attrs = curses.A_UNDERLINE | link_pair
        end_x = _put_clipped(window, y, x, link_text, limit_x, attrs)
        link_layout = LinkLayout(y, x, max(0, end_x - x))
        y += 1
    if y < bottom:
        centered(WELCOME_DISMISS_HINT, dim_pair)
        y += 1
    if y < bottom:
        centered(WELCOME_REOPEN_HINT, dim_pair)
        y += 1
    y += 1

    button_layout = None
    province_yes_layout = None
    province_no_layout = None
    if province_prompt and y < bottom:
        centered("Optional: download state / province borders (~25MB)?", dim_pair)
        y += 1
        yes_text = "[Y DOWNLOAD]"
        no_text = "[N KEEP OFF]"
        gap = "   "
        total_width = len(yes_text) + len(gap) + len(no_text)
        yes_x = left + max(1 + MODAL_PADDING_X, (width - total_width) // 2)
        no_x = yes_x + len(yes_text) + len(gap)
        attrs = curses.A_BOLD | curses.A_REVERSE | accent_pair
        yes_end = _put_clipped(window, y, yes_x, yes_text, limit_x, attrs)
        no_end = _put_clipped(window, y, no_x, no_text, limit_x, curses.A_BOLD | curses.A_REVERSE | text_pair)
        province_yes_layout = LinkLayout(y, yes_x, max(0, yes_end - yes_x))
        province_no_layout = LinkLayout(y, no_x, max(0, no_end - no_x))
        y += 1
    if y < bottom:
        x = left + max(1 + MODAL_PADDING_X, (width - len(WELCOME_SKIP_BUTTON)) // 2)
        attrs = curses.A_BOLD | curses.A_REVERSE | text_pair
        end_x = _put_clipped(window, y, x, WELCOME_SKIP_BUTTON, limit_x, attrs)
        button_layout = LinkLayout(y, x, max(0, end_x - x))

    return (top, left, height, width), link_layout, button_layout, province_yes_layout, province_no_layout

def info_title_text(layer: Layer | None, selection_position: tuple[int, int]) -> str:
    title = layer.info_title if layer else DEFAULT_INFO_TITLE
    position, total = selection_position
    if total > 1:
        title = f"{title}  < {position} of {total} >"
    return title

def info_arrow_positions(
    info_left: int, layer: Layer | None, selection_position: tuple[int, int]
) -> tuple[int, int] | None:
    """Screen x of the "<" and ">" in the info box title (None if not shown).

    Shared by drawing and mouse handling so the two can never disagree."""
    if layer is None or selection_position[1] < 2:
        return None
    title_left = info_left + 3
    title = info_title_text(layer, selection_position)
    return title_left + len(layer.info_title) + 2, title_left + title.rfind(">")

def draw_info_box(
    window,
    top: int,
    left: int,
    height: int,
    width: int,
    layer: Layer | None,
    selection_position: tuple[int, int] = (0, 0),
    colors: ColorManager | None = None,
) -> None:
    if height < 3 or width < INFO_BOX_MIN_WIDTH:
        return

    draw_box(window, top, left, height, width, info_title_text(layer, selection_position))

    if layer is None:
        for offset, line in enumerate(INFO_PLACEHOLDER):
            if line:  # empty strings are blank rows
                safe_addstr(window, top + 1 + offset, left + 2, line)
        return

    image = None
    if colors is not None:
        # Room left for a picture: box minus borders/padding, the label column,
        # the minimum value width and the gap.
        room = width - (INFO_BOX_LABEL_WIDTH + 3) - INFO_IMAGE_MIN_VALUE_WIDTH - INFO_IMAGE_GAP - 2
        if room >= 4:
            image = layer.info_image(height - 2, room)

    value_width = width if image is None else width - image.width - INFO_IMAGE_GAP
    _draw_label_value_rows(
        window, top, left, height, value_width, layer.info_rows(), INFO_BOX_LABEL_WIDTH
    )
    if image is not None and colors is not None:
        _draw_info_image(window, top, left + width - 2 - image.width, height, image, colors)

def _draw_info_image(window, top: int, left: int, height: int, image: InfoImage, colors) -> None:
    """Paint an InfoImage's lines inside an info box, from its first inner row."""
    limit_x = left + image.width
    for offset, segments in enumerate(image.lines[: height - 2]):
        x = left
        for text, fg, bg in segments:
            attributes = colors.get_pair(fg, bg) if fg else 0
            x = _put_clipped(window, top + 1 + offset, x, text, limit_x, attributes)

def draw_text_box(window, rect: Rect, title: str, lines: list[tuple[str, int]]) -> None:
    """A box of (text, curses attributes) lines, clipped to the box."""
    top, left, height, width = rect
    if height < 3 or width < INFO_BOX_MIN_WIDTH:
        return
    draw_box(window, top, left, height, width, title)
    limit_x = left + width - 2
    for offset, (text, attributes) in enumerate(lines[: height - 2]):
        _put_clipped(window, top + 1 + offset, left + 2, text, limit_x, attributes)

def draw_live_box(
    window, rect: Rect, title: str, rows: list[tuple[str, str]]
) -> None:
    """A box of (label, value) rows a layer computes fresh every frame (clock,
    sun, moon...). The label column is as wide as the longest label."""
    top, left, height, width = rect
    if height < 3 or width < INFO_BOX_MIN_WIDTH:
        return
    draw_box(window, top, left, height, width, title)
    label_width = min(
        LIVE_BOX_MAX_LABEL_WIDTH, max((len(str(label)) for label, _ in rows), default=0)
    )
    _draw_label_value_rows(
        window, top, left, height, width, rows, label_width, bold_label=True
    )

def draw_rich_box(window, rect: Rect, title: str, lines, colors) -> None:
    """A box of coloured text. `lines` is a list of lines, each a list of
    (text, "#rrggbb" or None, style) pieces (style "", "bold" or "dim"),
    clipped to the box."""
    top, left, height, width = rect
    if height < 3 or width < INFO_BOX_MIN_WIDTH:
        return
    draw_box(window, top, left, height, width, title)
    limit_x = left + width - 2
    for offset, pieces in enumerate(lines[: height - 2]):
        x = left + 2
        for text, color, style in pieces:
            attributes = colors.get_pair(color) if color else 0
            if style == "bold":
                attributes |= curses.A_BOLD
            elif style == "dim":
                attributes |= curses.A_DIM
            x = _put_clipped(window, top + 1 + offset, x, text, limit_x, attributes)

def _draw_label_value_rows(
    window,
    top: int,
    left: int,
    height: int,
    width: int,
    rows: list[tuple[str, str]],
    label_width: int,
    bold_label: bool = False,
) -> None:
    """(label, value) rows inside a box already drawn by draw_box: the label
    column is `label_width` wide, the value wraps in whatever room is left.
    Shared by draw_info_box and draw_live_box, which only differ in where
    label_width comes from and whether the label is bold."""
    x = left + 2
    value_x = x + label_width + 1
    value_width = max(1, width - (value_x - left) - 2)
    attrs = curses.A_BOLD if bold_label else 0
    y = top + 1
    for label, value in rows:
        if y >= top + height - 1:
            break
        safe_addstr(window, y, x, str(label)[:label_width].ljust(label_width), attrs)
        wrapped = textwrap.wrap(
            str(value), width=value_width, break_long_words=True, break_on_hyphens=False
        ) or [""]
        for line in wrapped:
            if y >= top + height - 1:
                break
            safe_addstr(window, y, value_x, line)
            y += 1
