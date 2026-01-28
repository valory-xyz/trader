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

"""Base class for all achievements checkers."""


from uuid import uuid5, NAMESPACE_DNS
from typing import Dict, Any


OLAS_NETWORK_NS = uuid5(NAMESPACE_DNS, "olas.network")
ACHIEVEMENTS_CHECKER_NS = uuid5(OLAS_NETWORK_NS, "skill/valory/agent_performance_summary_abci/achievements_checker")


class AchievementsChecker:
    """Base class for all achievements checkers"""

    def generate_achievement_id(self, seed: str) -> str:
        """Generate a deterministic achievement type ID"""
        return str(uuid5(ACHIEVEMENTS_CHECKER_NS, f"{self.achievement_type}/{seed}"))

    def update_achievements(self, achievements: Dict[str, Dict], **kwargs) -> bool:
        """Check if an achievement has been reached and populate `achievements`. Returns `True` if the achievements dictionary has been updated."""
        raise NotImplementedError()

    @property
    def achievement_type(self) -> str:
        """Returns a string representing the achievement type"""
        raise NotImplementedError()
