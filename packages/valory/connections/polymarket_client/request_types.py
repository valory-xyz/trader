#!/usr/bin/env python3
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

"""Request types for Polymarket connection."""

from enum import Enum


class RequestType(Enum):
    """Enum for supported Polymarket request types."""

    PLACE_BET = "place_bet"
    FETCH_MARKETS = "fetch_markets"
    FETCH_MARKET = "fetch_market"
    GET_POSITIONS = "get_positions"
    FETCH_ALL_POSITIONS = "fetch_all_positions"
    GET_TRADES = "get_trades"
    FETCH_ALL_TRADES = "fetch_all_trades"
    REDEEM_POSITIONS = "redeem_positions"
    SET_APPROVAL = "set_approval"
    CHECK_APPROVAL = "check_approval"
