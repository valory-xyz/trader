# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""The runtime strategy pointer must match the packaged strategy code.

The agent downloads its betting strategy at runtime from the CID in the
``file_hash_to_strategies`` param, NOT from the packaged ``customs`` code.
``autonomy packages lock`` bumps the package CID but never that pointer, so a
strategy change that forgets to repoint it silently ships the OLD strategy —
this actually happened: the kelly pointer sat frozen for ~2 months across
several releases while the packaged code moved on twice. This test fails when
any ``file_hash_to_strategies`` entry disagrees with the ``packages.json`` CID
for that strategy.
"""

import functools
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


def _repo_root() -> Path:
    """Return the repo root, i.e. the directory holding ``packages/packages.json``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "packages.json").is_file():
            return parent
    raise RuntimeError("Could not locate packages/packages.json above this test.")


ROOT = _repo_root()

# Every config that pins the runtime strategy pointer.
POINTER_FILES = (
    ROOT / "packages/valory/services/polymarket_trader/service.yaml",
    ROOT / "packages/valory/services/trader_pearl/service.yaml",
    ROOT / "packages/valory/agents/trader/aea-config.yaml",
)

_POINTER_RE = re.compile(r"file_hash_to_strategies:\s*\$\{[^{]*(\{.*\})\}")
_ENTRY_RE = re.compile(r'"(bafybei[a-z0-9]+)":\s*\[\s*"([a-z_]+)"\s*\]')


def _config_id(path: Path) -> str:
    """Return a disambiguating label, e.g. ``polymarket_trader/service.yaml``."""
    return f"{path.parent.name}/{path.name}"


@functools.lru_cache()
def _package_cids() -> Dict[str, str]:
    """Return ``{strategy_name: package_cid}`` for every ``custom`` in packages.json."""
    data = json.loads((ROOT / "packages" / "packages.json").read_text())
    out: Dict[str, str] = {}
    for section in data.values():
        if not isinstance(section, dict):
            continue
        for key, cid in section.items():
            match = re.match(r"custom/valory/([a-z_]+)/", key)
            if match:
                out[match.group(1)] = cid
    return out


def _pointer_entries(path: Path) -> List[Tuple[str, str]]:
    """Return ``(strategy_name, runtime_cid)`` pairs from a config's pointer."""
    if not path.is_file():
        return []
    match = _POINTER_RE.search(path.read_text())
    if match is None:
        return []
    return [(name, cid) for cid, name in _ENTRY_RE.findall(match.group(1))]


_CASES = [
    (_config_id(path), name, cid)
    for path in POINTER_FILES
    for name, cid in _pointer_entries(path)
]


def test_all_pointer_files_present() -> None:
    """Every expected pointer config must exist (a rename must not silently drop coverage)."""
    missing = [_config_id(p) for p in POINTER_FILES if not p.is_file()]
    assert not missing, f"Expected strategy-pointer config(s) missing: {missing}"


@pytest.mark.parametrize("path", POINTER_FILES, ids=_config_id)
def test_each_pointer_file_has_entries(path: Path) -> None:
    """Each pointer config must parse to at least one strategy entry."""
    assert _pointer_entries(path), (
        f"{_config_id(path)}: no file_hash_to_strategies entries parsed. A missing "
        f"file or a format change would otherwise silently drop this config from the "
        f"consistency check while the others keep the suite green."
    )


@pytest.mark.parametrize("config, strategy, runtime_cid", _CASES)
def test_runtime_pointer_matches_packaged_strategy(
    config: str, strategy: str, runtime_cid: str
) -> None:
    """Each file_hash_to_strategies CID must equal the packages.json CID."""
    packaged = _package_cids().get(strategy)
    assert packaged is not None, (
        f"{config}: file_hash_to_strategies references '{strategy}', which is "
        f"not a custom/valory/* package in packages.json."
    )
    assert runtime_cid == packaged, (
        f"{config}: runtime strategy '{strategy}' is STALE — "
        f"file_hash_to_strategies -> {runtime_cid} but packages.json -> "
        f"{packaged}. Repoint file_hash_to_strategies to the packaged CID and "
        f"re-lock, or the deployed agent will keep running an old strategy."
    )
