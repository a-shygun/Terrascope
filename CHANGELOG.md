# Changelog

## 0.2.3

- Handle malformed flight `last_contact` values and skip invalid cached history timestamps. (PR #8)
- Reject non-integer radar frame timestamps instead of failing later during rendering. (PR #9)
- Restrict search and country-filter shortcuts to the Planes tab, fixing the hidden modal freeze reported in issue #3.
- Update package-manager configuration: Homebrew reads the release version from `pyproject.toml` and supports `--HEAD`; the Arch recipe tracks `main` as `terrascope-git`.

## 0.2.1

- Switch the radar overlay to RainViewer's Weather Maps API.
- Improve weather forecast readability, chart sizing, and dynamic city details.
- Refine map footer spacing, panel controls, and weather error messages.
