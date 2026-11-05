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

"""The score-gated tags must reach the ranking under every default config."""

import re
from pathlib import Path
from typing import List

import pytest
import yaml

from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    SCORE_GATED_POLYMARKET_TAGS,
)

PACKAGES_ROOT = Path(__file__).resolve().parents[4]
CONFIGS = (
    "valory/skills/market_manager_abci/skill.yaml",
    "valory/skills/decision_maker_abci/skill.yaml",
    "valory/skills/trader_abci/skill.yaml",
    "valory/agents/trader/aea-config.yaml",
    "valory/services/polymarket_trader/service.yaml",
    "valory/services/trader_pearl/service.yaml",
)
# a block list in a skill.yaml, or the inline default of an env-var template
DEFAULT = re.compile(
    r"disabled_polymarket_tags:(?:\s*\$\{\w+:list:(\[.*?\])\}|((?:\s*- .*)+))"
)


def _default_disabled_tags(config: str) -> List[str]:
    """Load the default disabled_polymarket_tags of a config file."""
    found = DEFAULT.search((PACKAGES_ROOT / config).read_text())
    assert found is not None, f"no disabled_polymarket_tags default in {config}"
    inline, block = found.groups()
    return yaml.safe_load(inline or block)


@pytest.mark.parametrize("config", CONFIGS)
def test_no_default_disables_a_score_gated_tag(config: str) -> None:
    """A disabled tag is dropped before the ranking, so the gate could never pass it."""
    tags = _default_disabled_tags(config)
    assert tags and not SCORE_GATED_POLYMARKET_TAGS & {t.strip().lower() for t in tags}
