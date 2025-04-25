# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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
        sender="sender", vote=True, n_mech_requests_this_epoch=1
    )

    assert payload.vote
    assert payload.n_mech_requests_this_epoch
    assert payload.data == {"vote": True, "n_mech_requests_this_epoch": 1}
    assert CheckStopTradingPayload.from_json(payload.json) == payload
