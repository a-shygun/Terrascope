"""The --lang flag and the translated help, run as the real command."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def _run(args, tmp_path, env_extra=None):
    env = dict(os.environ)
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG", "terrascope_CONFIG", "terrascope_LOCALE_DIR"):
        env.pop(name, None)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "terrascope", *args],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )


def test_help_in_portuguese(tmp_path):
    result = _run(["--lang", "pt_BR", "--help"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Idioma e formatos regionais" in result.stdout
    assert "Mostra esta ajuda e encerra." in result.stdout
    assert "Language and regional formats" not in result.stdout


def test_help_in_english_is_unchanged(tmp_path):
    result = _run(["--lang", "en", "--help"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Language and regional formats" in result.stdout
    assert "Show this help and exit." in result.stdout


def test_lang_hyphen_form_is_accepted(tmp_path):
    result = _run(["--lang", "pt-BR", "--list-tabs"], tmp_path)
    assert result.returncode == 0, result.stderr


def test_auto_is_accepted_as_a_language(tmp_path):
    """The help and the config both document 'auto'; it means 'choose from the system'."""
    result = _run(["--lang", "auto", "--list-tabs"], tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("value", ["AUTO", "Auto"])
def test_auto_is_accepted_in_any_case(tmp_path, value):
    result = _run(["--lang", value, "--list-tabs"], tmp_path)
    assert result.returncode == 0, result.stderr


def test_unsupported_language_is_an_error(tmp_path):
    result = _run(["--lang", "fr", "--list-tabs"], tmp_path)
    assert result.returncode == 2
    assert "unsupported language 'fr'" in result.stderr


def test_environment_selects_the_language_when_no_flag(tmp_path):
    result = _run(["--help"], tmp_path, {"LANG": "pt_BR.UTF-8"})
    assert result.returncode == 0, result.stderr
    assert "Idioma e formatos regionais" in result.stdout


@pytest.mark.parametrize("flag, value", [("--time-format", "12h"), ("--units", "imperial")])
def test_regional_flags_are_accepted(tmp_path, flag, value):
    result = _run(["--lang", "en", flag, value, "--dump-config"], tmp_path)
    assert result.returncode == 0, result.stderr
    assert f"{flag[2:].replace('-', '_')}" in result.stdout or value in result.stdout
