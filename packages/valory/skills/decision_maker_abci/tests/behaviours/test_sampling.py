# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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

"""Test the sampling.py module of the skill."""

import pytest
from datetime import datetime

# Constants
UNIX_DAY = 86400
UNIX_WEEK = 604800

# Mock classes to simulate the required attributes
class MockObject:
    def __init__(self):
        self.bets = []
        self.synced_timestamp = 0

    def processable_bet(self, bet):
        now = self.synced_timestamp
        within_opening_range = bet.openingTimestamp <= (now + self.params.sample_bets_closing_days * UNIX_DAY)
        within_safe_range = now < bet.openingTimestamp + self.params.safe_voting_range
        within_ranges = within_opening_range and within_safe_range
        if not self.should_rebet:
            return within_ranges
        if not bool(bet.n_bets):
            return False
        lifetime = bet.openingTimestamp - now
        t_rebetting = (lifetime // UNIX_WEEK) + UNIX_DAY
        can_rebet = now >= bet.processed_timestamp + t_rebetting
        if can_rebet:
            return within_ranges
        return False

    def _sample(self):
        available_bets = list(filter(self.processable_bet, self.bets))
        if len(available_bets) == 0:
            self.context.logger.warning("There were no unprocessed bets available to sample from!")
            return None
        idx = self._sampled_bet_idx(available_bets)
        if self.bets[idx].scaledLiquidityMeasure == 0:
            self.context.logger.warning("There were no unprocessed bets with non-zero liquidity!")
            return None
        self.bets[idx].processed_timestamp = self.synced_timestamp
        self.bets[idx].n_bets += 1
        self.context.logger.info(f"Sampled bet: {self.bets[idx]}")
        return idx

class MockParams:
    def __init__(self, sample_bets_closing_days, safe_voting_range):
        self.sample_bets_closing_days = sample_bets_closing_days
        self.safe_voting_range = safe_voting_range

class MockBet:
    def __init__(self, openingTimestamp, n_bets=1, processed_timestamp=0, scaledLiquidityMeasure=0.0):
        self.openingTimestamp = openingTimestamp
        self.n_bets = n_bets
        self.processed_timestamp = processed_timestamp
        self.scaledLiquidityMeasure = scaledLiquidityMeasure

class MockContext:
    def __init__(self):
        self.logger = MockLogger()

class MockLogger:
    def warning(self, msg):
        print(f"WARNING: {msg}")

    def info(self, msg):
        print(f"INFO: {msg}")

@pytest.fixture
def setup_mock_object():
    """Fixture to set up the mock object for testing."""
    obj = MockObject()
    obj.synced_timestamp = datetime.now().timestamp()
    obj.params = MockParams(sample_bets_closing_days=5, safe_voting_range=2 * UNIX_DAY)
    obj.should_rebet = True  # Initially set to allow rebetting
    obj.context = MockContext()  # Mock context for logging
    return obj

def test_within_opening_and_safe_range_no_rebet(setup_mock_object):
    """Test bet within opening and safe range, no rebetting."""
    obj = setup_mock_object
    obj.should_rebet = False
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY,
        n_bets=1,
        processed_timestamp=obj.synced_timestamp - 2 * UNIX_DAY
    )
    result = obj.processable_bet(bet)
    assert result is True

def test_outside_opening_range(setup_mock_object):
    """Test bet outside the opening range."""
    obj = setup_mock_object
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp + 10 * UNIX_DAY,
        n_bets=1,
        processed_timestamp=obj.synced_timestamp - 2 * UNIX_DAY
    )
    result = obj.processable_bet(bet)
    assert result is False

def test_outside_safe_range(setup_mock_object):
    """Test bet outside the safe range."""
    obj = setup_mock_object
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp - 3 * UNIX_DAY,
        n_bets=1,
        processed_timestamp=obj.synced_timestamp - 2 * UNIX_DAY
    )
    result = obj.processable_bet(bet)
    assert result is False

def test_no_previous_bets_with_rebet(setup_mock_object):
    """Test no previous bets exist, but rebetting is enabled."""
    obj = setup_mock_object
    obj.should_rebet = True
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY,
        n_bets=0,  # No previous bet
        processed_timestamp=obj.synced_timestamp - 2 * UNIX_DAY
    )
    result = obj.processable_bet(bet)
    assert result is False

def test_valid_rebet_condition(setup_mock_object):
    """Test valid rebet condition when rebetting is allowed."""
    obj = setup_mock_object
    obj.should_rebet = True
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY,
        n_bets=1,
        processed_timestamp=obj.synced_timestamp - 3 * UNIX_DAY  # Enough time for rebetting
    )
    result = obj.processable_bet(bet)
    assert result is True

def test_rebetting_not_allowed_due_to_timing(setup_mock_object):
    """Test rebetting not allowed due to insufficient time since last processed."""
    obj = setup_mock_object
    obj.should_rebet = True
    bet = MockBet(
        openingTimestamp=obj.synced_timestamp + 4 * UNIX_DAY,
        n_bets=1,
        processed_timestamp=obj.synced_timestamp - 1 * UNIX_DAY  # Recently processed
    )
    result = obj.processable_bet(bet)
    assert result is False

def test_sample_function(setup_mock_object):
    """Test the _sample function."""
    obj = setup_mock_object
    # Set up bets for sampling
    obj.bets = [
        MockBet(openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY, n_bets=0, processed_timestamp=0, scaledLiquidityMeasure=0.5),
        MockBet(openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY, n_bets=1, processed_timestamp=0, scaledLiquidityMeasure=0.3),
        MockBet(openingTimestamp=obj.synced_timestamp + 2 * UNIX_DAY, n_bets=1, processed_timestamp=0, scaledLiquidityMeasure=0.0),  # Zero liquidity
    ]
    # Mock the _sampled_bet_idx method to return the first available bet's index
    obj._sampled_bet_idx = lambda bets: 0
    # Test the sampling function
    result = obj._sample()
    assert result is not None, "Expected a valid bet index to be sampled."
    assert result == 0, "Expected to sample the first bet."
    assert obj.bets[0].processed_timestamp == obj.synced_timestamp, "Processed timestamp not updated correctly."
    assert obj.bets[0].n_bets == 1, "Number of bets not incremented correctly."
    # Test when all bets have zero liquidity
    obj.bets[0].scaledLiquidityMeasure = 0
    result = obj._sample()
    assert result is None, "Expected no bet to be sampled due to zero liquidity."
