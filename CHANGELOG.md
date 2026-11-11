# Changelog

## Unreleased

- Support Windows 10/11: `windows-curses` and `tzdata` are installed automatically on Windows, so the curses UI starts and the time zone selector lists every IANA zone.
- Fix mouse wheel zoom and drag-to-pan under PDCurses (`windows-curses`), which reports wheel and button-held motion events with an empty button state.
- Fix colours under PDCurses: the colour-pair budget was computed as 1 (every colour reused the first pair, losing the water/land fill), bold coloured text switched palette slots, and dim text was drawn at full brightness.
- Show the UTC offset instead of Windows' long localised zone name in the clock and the CLOCK panel.
- Build a standalone `windows_x86_64` zip with each release, with generated Scoop and winget manifests; add Windows to the CI matrix.

## 1.0.0

- First stable release of Terrascope.

## 0.2.3

- Handle malformed flight `last_contact` values and skip invalid cached history timestamps. (PR #8)
- Reject non-integer radar frame timestamps instead of failing later during rendering. (PR #9)
- Restrict search and country-filter shortcuts to the Planes tab, fixing the hidden modal freeze reported in issue #3.
- Update package-manager configuration: Homebrew reads the release version from `pyproject.toml` and supports `--HEAD`; the Arch recipe tracks `main` as `terrascope-git`.

## 0.2.1

- Switch the radar overlay to RainViewer's Weather Maps API.
- Improve weather forecast readability, chart sizing, and dynamic city details.
- Refine map footer spacing, panel controls, and weather error messages.
