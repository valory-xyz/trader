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
"""This module contains the transaction payloads for the check stop trading abci."""

from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)


def test_check_stop_trading_payload() -> None:
    """Test `CheckStopTradingPayload`."""

    payload = CheckStopTradingPayload(
        sender="sender", vote=True, review_bets_for_selling=True
    )

    assert payload.vote
    assert payload.data == {
        "vote": True,
        "review_bets_for_selling": True,
        "is_staking_kpi_met": None,
        "is_activity_target_met": None,
        "activity_target": None,
        "activity_completed": None,
    }
    assert CheckStopTradingPayload.from_json(payload.json) == payload


def test_check_stop_trading_payload_with_activity_fields() -> None:
    """Test `CheckStopTradingPayload` carrying the activity-decoupling fields."""

    payload = CheckStopTradingPayload(
        sender="sender",
        vote=False,
        is_staking_kpi_met=True,
        is_activity_target_met=False,
        activity_target=8,
        activity_completed=5,
    )

    assert payload.vote is False
    assert payload.is_staking_kpi_met is True
    assert payload.is_activity_target_met is False
    assert payload.activity_target == 8
    assert payload.activity_completed == 5
    assert CheckStopTradingPayload.from_json(payload.json) == payload
