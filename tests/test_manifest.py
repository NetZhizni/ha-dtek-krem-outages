"""Consistency checks for release metadata."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.dtek_krem_outages.const import DOMAIN

ROOT = Path(__file__).parents[1]
INTEGRATION_DIR = ROOT / "custom_components" / DOMAIN


def test_changelog_has_manifest_version() -> None:
    """The release workflow takes its notes from this version's CHANGELOG section."""
    manifest = json.loads((INTEGRATION_DIR / "manifest.json").read_text("utf-8"))
    heading = f"## [{manifest['version']}] - "
    lines = (ROOT / "CHANGELOG.md").read_text("utf-8").splitlines()
    assert any(line.startswith(heading) for line in lines)


def test_brand_icons_present() -> None:
    """Home Assistant serves these from the integration's brand folder."""
    for name in ("icon.png", "icon@2x.png"):
        assert (INTEGRATION_DIR / "brand" / name).is_file()


def test_translations_match() -> None:
    """strings.json and en.json are identical; uk.json, ru.json have its keys."""

    def keys(data: dict, prefix: str = "") -> set[str]:
        result = set()
        for key, value in data.items():
            result.add(prefix + key)
            if isinstance(value, dict):
                result |= keys(value, f"{prefix}{key}.")
        return result

    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text("utf-8"))
    english = json.loads(
        (INTEGRATION_DIR / "translations" / "en.json").read_text("utf-8")
    )
    assert strings == english
    for language in ("uk", "ru"):
        translation = json.loads(
            (INTEGRATION_DIR / "translations" / f"{language}.json").read_text("utf-8")
        )
        assert keys(strings) == keys(translation), language
