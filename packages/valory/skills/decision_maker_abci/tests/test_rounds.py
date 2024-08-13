# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the test rounds for the decision-making."""
import unittest
from unittest.mock import Mock
from unittest.mock import MagicMock
from packages.valory.skills.abstract_round_abci.base import AppState, AbciApp
from packages.valory.skills.decision_maker_abci.states.base import Event, SynchronizedData
from packages.valory.skills.decision_maker_abci.states.bet_placement import BetPlacementRound
from packages.valory.skills.decision_maker_abci.states.blacklisting import BlacklistingRound
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import CheckBenchmarkingModeRound
from packages.valory.skills.decision_maker_abci.states.claim_subscription import ClaimRound
from packages.valory.skills.decision_maker_abci.states.decision_receive import DecisionReceiveRound
from packages.valory.skills.decision_maker_abci.states.decision_request import DecisionRequestRound
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedSubscriptionRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    ImpossibleRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import HandleFailedTxRound
from packages.valory.skills.decision_maker_abci.states.order_subscription import SubscriptionRound
from packages.valory.skills.decision_maker_abci.states.randomness import RandomnessRound
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.decision_maker_abci.states.tool_selection import ToolSelectionRound
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)
from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    get_name,
)

class TestDecisionMakerAbciApp(unittest.TestCase):
    def setUp(self):
        # Create mock objects for required parameters
        self.synchronized_data = Mock()
        self.logger = Mock()
        self.context = Mock()
        
        # Initialize the app with mocks
        self.app = DecisionMakerAbciApp(self.synchronized_data, self.logger, self.context)
        # Mock methods and states
        self.app.get_state = MagicMock()
        self.app.set_state = MagicMock()

    def test_initial_round(self):
        synchronized_data = {}  # Initialize with actual data as required
        context = {}  # Initialize with actual context as required
        initial_round = self.app.initial_round_cls(synchronized_data, context)
        self.assertIsInstance(initial_round, CheckBenchmarkingModeRound)

    def test_initial_states(self):
        initial_states = {
            CheckBenchmarkingModeRound,
            SamplingRound,
            HandleFailedTxRound,
            DecisionReceiveRound,
            RedeemRound,
            ClaimRound,
        }
        self.assertEqual(self.app.initial_states, initial_states)

    def test_transition_function(self):
        # Check transitions from CheckBenchmarkingModeRound
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.BENCHMARKING_ENABLED],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.BENCHMARKING_DISABLED],
            BenchmarkingModeDisabledRound
        )
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.NO_MAJORITY],
            CheckBenchmarkingModeRound
        )
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.ROUND_TIMEOUT],
            CheckBenchmarkingModeRound
        )
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.NO_OP],
            ImpossibleRound
        )
        self.assertEqual(
            self.app.transition_function[CheckBenchmarkingModeRound][Event.BLACKLIST],
            ImpossibleRound
        )

        # Test transitions from SamplingRound
        self.assertEqual(
            self.app.transition_function[SamplingRound][Event.DONE],
            SubscriptionRound
        )
        self.assertEqual(
            self.app.transition_function[SamplingRound][Event.NONE],
            FinishedWithoutDecisionRound
        )
        self.assertEqual(
            self.app.transition_function[SamplingRound][Event.NO_MAJORITY],
            SamplingRound
        )
        self.assertEqual(
            self.app.transition_function[SamplingRound][Event.ROUND_TIMEOUT],
            SamplingRound
        )
        self.assertEqual(
            self.app.transition_function[SamplingRound][MarketManagerEvent.FETCH_ERROR],
            ImpossibleRound
        )

        # Test transitions from SubscriptionRound
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.DONE],
            FinishedSubscriptionRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.MOCK_TX],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.NO_SUBSCRIPTION],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.NONE],
            SubscriptionRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.SUBSCRIPTION_ERROR],
            SubscriptionRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.NO_MAJORITY],
            SubscriptionRound
        )
        self.assertEqual(
            self.app.transition_function[SubscriptionRound][Event.ROUND_TIMEOUT],
            SubscriptionRound
        )

        # Test transitions from ClaimRound
        self.assertEqual(
            self.app.transition_function[ClaimRound][Event.DONE],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[ClaimRound][Event.SUBSCRIPTION_ERROR],
            ClaimRound
        )
        self.assertEqual(
            self.app.transition_function[ClaimRound][Event.NO_MAJORITY],
            ClaimRound
        )
        self.assertEqual(
            self.app.transition_function[ClaimRound][Event.ROUND_TIMEOUT],
            ClaimRound
        )

        # Test transitions from RandomnessRound
        self.assertEqual(
            self.app.transition_function[RandomnessRound][Event.DONE],
            ToolSelectionRound
        )
        self.assertEqual(
            self.app.transition_function[RandomnessRound][Event.ROUND_TIMEOUT],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[RandomnessRound][Event.NO_MAJORITY],
            RandomnessRound
        )

        # Test transitions from ToolSelectionRound
        self.assertEqual(
            self.app.transition_function[ToolSelectionRound][Event.DONE],
            DecisionRequestRound
        )
        self.assertEqual(
            self.app.transition_function[ToolSelectionRound][Event.NONE],
            ToolSelectionRound
        )
        self.assertEqual(
            self.app.transition_function[ToolSelectionRound][Event.NO_MAJORITY],
            ToolSelectionRound
        )
        self.assertEqual(
            self.app.transition_function[ToolSelectionRound][Event.ROUND_TIMEOUT],
            ToolSelectionRound
        )

        # Test transitions from DecisionRequestRound
        self.assertEqual(
            self.app.transition_function[DecisionRequestRound][Event.DONE],
            FinishedDecisionRequestRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionRequestRound][Event.MOCK_MECH_REQUEST],
            DecisionReceiveRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionRequestRound][Event.SLOTS_UNSUPPORTED_ERROR],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionRequestRound][Event.NO_MAJORITY],
            DecisionRequestRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionRequestRound][Event.ROUND_TIMEOUT],
            DecisionRequestRound
        )

        # Test transitions from DecisionReceiveRound
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.DONE],
            BetPlacementRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.MECH_RESPONSE_ERROR],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.NO_MAJORITY],
            DecisionReceiveRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.TIE],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.UNPROFITABLE],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.BENCHMARKING_FINISHED],
            BenchmarkingDoneRound
        )
        self.assertEqual(
            self.app.transition_function[DecisionReceiveRound][Event.ROUND_TIMEOUT],
            DecisionReceiveRound
        )

        # Test transitions from BlacklistingRound
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][Event.DONE],
            FinishedWithoutDecisionRound
        )
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][Event.MOCK_TX],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][Event.NONE],
            ImpossibleRound
        )
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][Event.NO_MAJORITY],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][Event.ROUND_TIMEOUT],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[BlacklistingRound][MarketManagerEvent.FETCH_ERROR],
            ImpossibleRound
        )

        # Test transitions from BetPlacementRound
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.DONE],
            FinishedDecisionMakerRound
        )
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.MOCK_TX],
            RedeemRound
        )
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.INSUFFICIENT_BALANCE],
            RefillRequiredRound
        )
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.NO_MAJORITY],
            BetPlacementRound
        )
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.ROUND_TIMEOUT],
            BetPlacementRound
        )
        self.assertEqual(
            self.app.transition_function[BetPlacementRound][Event.NONE],
            ImpossibleRound
        )

        # Test transitions from RedeemRound
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.DONE],
            FinishedDecisionMakerRound
        )
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.MOCK_TX],
            RandomnessRound
        )
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.NO_REDEEMING],
            FinishedWithoutRedeemingRound
        )
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.NO_MAJORITY],
            RedeemRound
        )
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.REDEEM_ROUND_TIMEOUT],
            FinishedWithoutRedeemingRound
        )
        self.assertEqual(
            self.app.transition_function[RedeemRound][Event.NONE],
            ImpossibleRound
        )

        # Test transitions from HandleFailedTxRound
        self.assertEqual(
            self.app.transition_function[HandleFailedTxRound][Event.BLACKLIST],
            BlacklistingRound
        )
        self.assertEqual(
            self.app.transition_function[HandleFailedTxRound][Event.NO_OP],
            RedeemRound
        )
        self.assertEqual(
            self.app.transition_function[HandleFailedTxRound][Event.NO_MAJORITY],
            HandleFailedTxRound
        )
        
    def test_cross_period_persisted_keys(self):
        expected_keys = frozenset(
            {
                get_name(SynchronizedData.available_mech_tools),
                get_name(SynchronizedData.policy),
                get_name(SynchronizedData.utilized_tools),
                get_name(SynchronizedData.redeemed_condition_ids),
                get_name(SynchronizedData.payout_so_far),
                get_name(SynchronizedData.mech_price),
                get_name(SynchronizedData.mocking_mode),
                get_name(SynchronizedData.next_mock_data_row),
                get_name(SynchronizedData.agreement_id),
            }
        )
        self.assertEqual(self.app.cross_period_persisted_keys, expected_keys)

    
    def test_final_states(self):
        final_states = {
            FinishedDecisionMakerRound,
            BenchmarkingModeDisabledRound,
            FinishedDecisionRequestRound,
            FinishedSubscriptionRound,
            FinishedWithoutDecisionRound,
            FinishedWithoutRedeemingRound,
            RefillRequiredRound,
            ImpossibleRound,
            BenchmarkingDoneRound,
        }
        self.assertEqual(self.app.final_states, final_states)

    def test_event_to_timeout(self):
        self.assertEqual(self.app.event_to_timeout[Event.ROUND_TIMEOUT], 30.0)
        self.assertEqual(self.app.event_to_timeout[Event.REDEEM_ROUND_TIMEOUT], 3600.0)

    def test_db_conditions(self):
        db_pre_conditions = {
            RedeemRound: set(),
            ClaimRound: set(),
            DecisionReceiveRound: {get_name(SynchronizedData.final_tx_hash)},
            HandleFailedTxRound: {get_name(SynchronizedData.bets_hash)},
            SamplingRound: set(),
            CheckBenchmarkingModeRound: set(),
        }
        self.assertEqual(self.app.db_pre_conditions, db_pre_conditions)

        db_post_conditions = {
            FinishedDecisionMakerRound: {
                get_name(SynchronizedData.sampled_bet_index),
                get_name(SynchronizedData.tx_submitter),
                get_name(SynchronizedData.most_voted_tx_hash),
            },
            BenchmarkingModeDisabledRound: set(),
            FinishedDecisionRequestRound: set(),
            FinishedSubscriptionRound: {
                get_name(SynchronizedData.tx_submitter),
                get_name(SynchronizedData.most_voted_tx_hash),
                get_name(SynchronizedData.agreement_id),
            },
            FinishedWithoutDecisionRound: {get_name(SynchronizedData.sampled_bet_index)},
            FinishedWithoutRedeemingRound: set(),
            RefillRequiredRound: set(),
            ImpossibleRound: set(),
            BenchmarkingDoneRound: {
                get_name(SynchronizedData.mocking_mode),
                get_name(SynchronizedData.next_mock_data_row),
            },
        }
        self.assertEqual(self.app.db_post_conditions, db_post_conditions)

    
if __name__ == '__main__':
    unittest.main()
