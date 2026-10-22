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

"""Tests for the helpers shared by the top-up round and `/funds-status`."""

from unittest.mock import MagicMock

from packages.valory.skills.agent_topup_abci.tests.helpers import (
    AGENT,
    ETHER,
    SAFE,
    funds_status,
    real_topup_rule,
)
from packages.valory.skills.agent_topup_abci.utils import (
    NO_TOPUP,
    get_agent_topups,
    get_safe_native_balance,
    get_signer_native_deficit,
)
from packages.valory.skills.funds_manager.models import (
    AccountRequirements,
    ChainRequirements,
    FundRequirements,
)

MIN = ETHER // 100


class TestGetAgentTopUps:
    """Tests for get_agent_topups."""

    def test_counts_safe_wxdai_as_native_on_gnosis(self) -> None:
        """Agent Safe wxDAI makes up for the xDAI the Agent Safe lacks."""
        funds = funds_status(
            "gnosis", ETHER // 10, ETHER, wxdai_balance=5 * ETHER, track_wxdai=True
        )

        topup = get_agent_topups(real_topup_rule("gnosis"), funds, AGENT, MIN)["gnosis"]

        assert topup.move == 19 * ETHER // 10
        assert topup.safe_deficit == 0

    def test_unread_wxdai_moves_nothing(self) -> None:
        """An unknown wxDAI balance never moves funds on Gnosis."""
        funds = funds_status(
            "gnosis", ETHER // 10, 5 * ETHER, wxdai_balance=None, track_wxdai=True
        )

        topups = get_agent_topups(real_topup_rule("gnosis"), funds, AGENT, MIN)

        assert topups["gnosis"] == NO_TOPUP

    def test_polygon_counts_only_safe_native(self) -> None:
        """Off Gnosis, nothing but the Agent Safe native balance counts."""
        rule = MagicMock(return_value={})
        funds = funds_status("polygon", ETHER // 10, ETHER)

        get_agent_topups(rule, funds, AGENT, MIN)

        rule.assert_called_once_with(funds, safe_native_extra={})

    def test_reports_the_combined_safe_request(self) -> None:
        """A short Agent Safe asks for the Agent Signer shortfall plus its own topup."""
        funds = funds_status("polygon", ETHER // 10, ETHER // 2)

        topup = get_agent_topups(real_topup_rule("polygon"), funds, AGENT, MIN)[
            "polygon"
        ]

        assert topup.move == ETHER // 2
        assert topup.signer_deficit == 0
        assert topup.safe_deficit == 19 * ETHER // 10 - ETHER // 2 + 10 * ETHER

    def test_signer_below_the_minimum_moves_nothing(self) -> None:
        """Below `min_signer_balance`, the deficits are reported as read."""
        funds = funds_status("polygon", MIN - 1, 10 * ETHER)

        topups = get_agent_topups(real_topup_rule("polygon"), funds, AGENT, MIN)

        assert topups["polygon"] == NO_TOPUP

    def test_signer_at_the_minimum_is_topped_up(self) -> None:
        """At `min_signer_balance`, the Agent Signer is topped up."""
        funds = funds_status("polygon", MIN, 10 * ETHER)

        topups = get_agent_topups(real_topup_rule("polygon"), funds, AGENT, MIN)

        assert topups["polygon"].move == 2 * ETHER - MIN


class TestGetSignerNativeDeficit:
    """Tests for get_signer_native_deficit."""

    def test_returns_the_signer_native_deficit(self) -> None:
        """The Agent Signer native deficit is read from the status."""
        funds = funds_status("gnosis", ETHER // 10, 3 * ETHER)

        assert get_signer_native_deficit(funds, "gnosis", AGENT) == 19 * ETHER // 10

    def test_status_without_signer(self) -> None:
        """A status with the Agent Safe only has no Agent Signer deficit."""
        funds = FundRequirements(
            {
                "gnosis": ChainRequirements(
                    accounts={SAFE: AccountRequirements(tokens={})}
                )
            }
        )

        assert get_signer_native_deficit(funds, "gnosis", AGENT) is None


class TestGetSafeNativeBalance:
    """Tests for get_safe_native_balance."""

    def test_returns_the_safe_native_balance(self) -> None:
        """The Agent Safe native balance is read from the status."""
        funds = funds_status("gnosis", ETHER, 3 * ETHER)

        assert get_safe_native_balance(funds, "gnosis", AGENT) == 3 * ETHER

    def test_unknown_chain(self) -> None:
        """A chain absent from the status has no balance."""
        funds = funds_status("gnosis", ETHER, 3 * ETHER)

        assert get_safe_native_balance(funds, "polygon", AGENT) is None

    def test_safe_without_native_entry(self) -> None:
        """An Agent Safe that tracks no native token has no balance."""
        funds = FundRequirements(
            {
                "gnosis": ChainRequirements(
                    accounts={SAFE: AccountRequirements(tokens={})}
                )
            }
        )

        assert get_safe_native_balance(funds, "gnosis", AGENT) is None

    def test_status_without_safe(self) -> None:
        """A status with the Agent Signer only has no Agent Safe balance."""
        funds = FundRequirements(
            {
                "gnosis": ChainRequirements(
                    accounts={AGENT: AccountRequirements(tokens={})}
                )
            }
        )

        assert get_safe_native_balance(funds, "gnosis", AGENT) is None
