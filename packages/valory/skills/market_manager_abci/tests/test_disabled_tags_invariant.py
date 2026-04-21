# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""Invariant test guarding against disabled_polymarket_tags drift.

Open Autonomy composition forces each composing skill to re-declare the
nested skill's ``args:``. So ``disabled_polymarket_tags`` is declared in
three places: ``market_manager_abci``, ``decision_maker_abci``, and
``trader_abci``. Divergence between them silently ships the wrong list in
production depending on which skill the deployed service loads through.
This test catches that drift early.
"""

from pathlib import Path
from typing import List

import yaml

PACKAGES_ROOT = Path(__file__).resolve().parents[4]


def _load_disabled_tags(skill_relpath: str) -> List[str]:
    """Load the disabled_polymarket_tags list from a skill's skill.yaml."""
    skill_yaml = PACKAGES_ROOT / skill_relpath / "skill.yaml"
    with skill_yaml.open() as f:
        data = yaml.safe_load(f)
    return data["models"]["params"]["args"]["disabled_polymarket_tags"]


def test_disabled_polymarket_tags_consistent_across_skills() -> None:
    """The three composed skills must declare identical disabled_polymarket_tags."""
    mm = _load_disabled_tags("valory/skills/market_manager_abci")
    dm = _load_disabled_tags("valory/skills/decision_maker_abci")
    trader = _load_disabled_tags("valory/skills/trader_abci")
    assert mm == dm == trader, (
        "disabled_polymarket_tags drift detected:\n"
        f"  market_manager_abci ({len(mm)} slugs): {mm}\n"
        f"  decision_maker_abci ({len(dm)} slugs): {dm}\n"
        f"  trader_abci ({len(trader)} slugs): {trader}"
    )
