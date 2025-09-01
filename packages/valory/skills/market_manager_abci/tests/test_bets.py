# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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

"""Test the bets.py module of the skill."""

# pylint: skip-file

import pytest

from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus


@pytest.fixture()
def bet() -> Bet:
    """Return a bet."""
    return Bet(
        id="1",
        market="1",
        title="1",
        collateralToken="1",
        creator="1",
        fee=1,
        openingTimestamp=1,
        outcomeSlotCount=1,
        outcomeTokenAmounts=[1],
        outcomeTokenMarginalPrices=[1],
        outcomes=["Yes", "No"],
        scaledLiquidityMeasure=1,
    )


def test_process_statuses(
    bet: Bet,
) -> None:
    """Test the queue statuses."""
    bet.queue_status = QueueStatus.FRESH

    assert QueueStatus.FRESH.is_fresh()

    bet.queue_status = bet.queue_status.move_to_process()

    assert not bet.queue_status.is_fresh()
    assert bet.queue_status == QueueStatus.TO_PROCESS

    status = bet.queue_status.next_status()
    assert status == QueueStatus.PROCESSED

    bet.queue_status = QueueStatus.PROCESSED

    status = bet.queue_status.next_status()
    assert status == QueueStatus.REPROCESSED

    bet.queue_status = QueueStatus.REPROCESSED

    status = bet.queue_status.next_status()
    assert status == QueueStatus.REPROCESSED


def test_sell_statuses(
    bet: Bet,
) -> None:
    """Test the sell statuses."""
    bet.queue_status = QueueStatus.FRESH

    status = bet.queue_status.move_to_check_for_selling()
    assert status == QueueStatus.CHECK_FOR_SELLING

    bet.queue_status = QueueStatus.CHECK_FOR_SELLING

    status = bet.queue_status.next_status()
    assert status == QueueStatus.REPROCESSED


def test_selected_for_selling_statuses(
    bet: Bet,
) -> None:
    """Test the selected for selling statuses."""
    bet.queue_status = QueueStatus.FRESH

    status = bet.queue_status.move_to_selected_for_selling()
    assert status == QueueStatus.SELECTED_FOR_SELLING

    bet.queue_status = QueueStatus.SELECTED_FOR_SELLING

    status = bet.queue_status.next_status()
    assert status == QueueStatus.REPROCESSED
