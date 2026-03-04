# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""This module contains tests for the AchievementsChecker base class."""

from uuid import NAMESPACE_DNS, uuid5

import pytest

from packages.valory.skills.agent_performance_summary_abci.achievements_checker.base import (
    ACHIEVEMENTS_CHECKER_NS,
    OLAS_NETWORK_NS,
    AchievementsChecker,
)
from packages.valory.skills.agent_performance_summary_abci.models import Achievements


class TestUUIDConstants:
    """Tests for UUID namespace constants."""

    def test_olas_network_ns_is_deterministic(self) -> None:
        """Test that OLAS_NETWORK_NS is deterministic."""
        expected = uuid5(NAMESPACE_DNS, "olas.network")
        assert OLAS_NETWORK_NS == expected

    def test_achievements_checker_ns_is_deterministic(self) -> None:
        """Test that ACHIEVEMENTS_CHECKER_NS is deterministic."""
        expected = uuid5(
            OLAS_NETWORK_NS,
            "skill/valory/agent_performance_summary_abci/achievements_checker",
        )
        assert ACHIEVEMENTS_CHECKER_NS == expected

    def test_olas_network_ns_stable_across_calls(self) -> None:
        """Test that OLAS_NETWORK_NS is the same across repeated accesses."""
        assert OLAS_NETWORK_NS == OLAS_NETWORK_NS

    def test_achievements_checker_ns_stable_across_calls(self) -> None:
        """Test that ACHIEVEMENTS_CHECKER_NS is the same across repeated accesses."""
        assert ACHIEVEMENTS_CHECKER_NS == ACHIEVEMENTS_CHECKER_NS


class TestAchievementsChecker:
    """Tests for AchievementsChecker base class."""

    def test_generate_achievement_id_is_deterministic(self) -> None:
        """Test that generate_achievement_id produces the same ID for the same seed."""

        class TestChecker(AchievementsChecker):
            """Test checker."""

            @property
            def achievement_type(self) -> str:  # type: ignore
                """Returns a string representing the achievement type."""
                return "test_type"

        test_checker = TestChecker()
        id1 = test_checker.generate_achievement_id("seed_value")
        id2 = test_checker.generate_achievement_id("seed_value")
        assert id1 == id2

    def test_generate_achievement_id_different_seeds(self) -> None:
        """Test that different seeds produce different IDs."""

        class TestChecker(AchievementsChecker):
            """Test checker."""

            @property
            def achievement_type(self) -> str:  # type: ignore
                """Returns a string representing the achievement type."""
                return "test_type"

        test_checker = TestChecker()
        id1 = test_checker.generate_achievement_id("seed_a")
        id2 = test_checker.generate_achievement_id("seed_b")
        assert id1 != id2

    def test_generate_achievement_id_uses_achievement_type(self) -> None:
        """Test that the achievement type is incorporated into the generated ID."""

        class TypeAChecker(AchievementsChecker):
            """Type A checker."""

            @property
            def achievement_type(self) -> str:  # type: ignore
                """Returns a string representing the achievement type."""
                return "type_a"

        class TypeBChecker(AchievementsChecker):
            """Type B checker."""

            @property
            def achievement_type(self) -> str:  # type: ignore
                """Returns a string representing the achievement type."""
                return "type_b"

        checker_a = TypeAChecker()
        checker_b = TypeBChecker()
        id_a = checker_a.generate_achievement_id("same_seed")
        id_b = checker_b.generate_achievement_id("same_seed")
        assert id_a != id_b

    def test_generate_achievement_id_format(self) -> None:
        """Test that the generated ID is a valid UUID string."""

        class TestChecker(AchievementsChecker):
            """Test checker."""

            @property
            def achievement_type(self) -> str:  # type: ignore
                """Returns a string representing the achievement type."""
                return "test_type"

        test_checker = TestChecker()
        achievement_id = test_checker.generate_achievement_id("test_seed")
        # UUID string format: 8-4-4-4-12 hex digits
        parts = achievement_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    def test_update_achievements_raises_not_implemented(self) -> None:
        """Test that update_achievements raises NotImplementedError on base class."""
        checker = AchievementsChecker()
        achievements = Achievements()
        with pytest.raises(NotImplementedError):
            checker.update_achievements(achievements)

    def test_achievement_type_raises_not_implemented(self) -> None:
        """Test that achievement_type raises NotImplementedError on base class."""
        checker = AchievementsChecker()
        with pytest.raises(NotImplementedError):
            _ = checker.achievement_type
