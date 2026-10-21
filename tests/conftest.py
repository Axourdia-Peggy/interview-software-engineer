"""Shared fixtures.

Tests never write inside the repository: catalog copies live in pytest's tmp_path
and CLI runs use --dry-run.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from shiftforge.config import CatalogBundle, load_catalogs

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "configs"
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.fixture
def catalogs() -> CatalogBundle:
    return load_catalogs(CONFIG_DIR)


@pytest.fixture
def edited_configs(tmp_path: Path) -> Callable[[Callable[[dict], None]], Path]:
    """Copy configs/ into tmp_path, apply `mutate` to rule_catalog.json, return the copy."""

    def _edit(mutate: Callable[[dict], None]) -> Path:
        config_dir = tmp_path / "configs"
        shutil.copytree(CONFIG_DIR, config_dir)
        path = config_dir / "rule_catalog.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return config_dir

    return _edit


def rule_params(payload: dict, name: str) -> dict:
    """The params dict of the named rule inside a raw rule_catalog.json payload."""
    return next(rule for rule in payload["rules"] if rule["name"] == name)["params"]
