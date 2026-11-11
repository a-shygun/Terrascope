"""Build hook: compile the translation catalogues to .mo files.

Each src/terrascope/locale/<lang>/LC_MESSAGES/terrascope.po is compiled with
Babel (a build dependency only; the app itself reads the .mo with gettext). The
.mo sits next to its .po, so editable installs and tests find it. Wheels get it
through force_include, because .mo files are ignored by git.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        from babel.messages.mofile import write_mo
        from babel.messages.pofile import read_po

        root = Path(self.root)
        source_dir = root / "src"
        for po in sorted((source_dir / "terrascope" / "locale").glob("*/LC_MESSAGES/terrascope.po")):
            mo = po.with_suffix(".mo")
            with po.open("rb") as source:
                catalog = read_po(source)
            with mo.open("wb") as target:
                write_mo(target, catalog)
            if self.target_name == "wheel":
                build_data["force_include"][str(mo)] = mo.relative_to(source_dir).as_posix()
