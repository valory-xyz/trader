import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from packages.valory.skills.staking_abci.behaviours import CallCheckpointBehaviour, StakingInteractBaseBehaviour
from packages.valory.skills.staking_abci.rounds import SynchronizedData, CallCheckpointRound
from packages.valory.skills.staking_abci.models import StakingParams
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract

from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)


PACKAGE_DIR = Path(__file__).parent.parent


class StackingFSMBehaviourBaseCase(FSMBehaviourBaseCase):
    """Base case for testing Stacking FSMBehaviour."""

    path_to_skill = PACKAGE_DIR


class TestCallCheckpointBehaviour(StackingFSMBehaviourBaseCase):
    def setUp(self):
        # Set up the behaviour instance
        self.behaviour = CallCheckpointBehaviour(name="test_behaviour", skill_context=MagicMock())
        self.behaviour.context.params = MagicMock(spec=StakingParams)
        self.behaviour.context.params.mech_activity_checker_contract = "0x0000000000000000000000000000000000000000"
        self.behaviour.context.params.staking_contract_address = "0xStakingContractAddress"
        self.behaviour.context.params.on_chain_service_id = 1
        self.behaviour.context.params.staking_interaction_sleep_time = 1
        self.behaviour.context.logger = MagicMock()
        self.behaviour.synchronized_data = MagicMock(spec=SynchronizedData)
        self.behaviour.synchronized_data.safe_contract_address = "0xSafeContractAddress"
        self.behaviour._service_staking_state = StakingInteractBaseBehaviour.StakingState.UNSTAKED

    @patch('packages.valory.skills.staking_abci.behaviours.CallCheckpointBehaviour.wait_for_condition_with_sleep')
    def test_async_act_service_staked(self, mock_wait_for_condition_with_sleep):
        # Mock the wait_for_condition_with_sleep method
        mock_wait_for_condition_with_sleep.side_effect = [True, True]

        # Mock the interaction with the staking contract
        self.behaviour._check_service_staked = MagicMock(return_value=True)
        self.behaviour._get_next_checkpoint = MagicMock(return_value=True)
        self.behaviour._prepare_safe_tx = MagicMock(return_value="0x123")

        # Set the service staking state to STAKED
        self.behaviour.service_staking_state = StakingInteractBaseBehaviour.StakingState.STAKED
        self.behaviour.is_checkpoint_reached = True

        # Run the async_act method
        with patch.object(self.behaviour, 'send_a2a_transaction', return_value=None) as mock_send_a2a_transaction, \
             patch.object(self.behaviour, 'wait_until_round_end', return_value=None):
            self.behaviour.async_act()

        # Assert that the checkpoint transaction was prepared and sent
        self.behaviour._prepare_safe_tx.assert_called_once()
        mock_send_a2a_transaction.assert_called_once()

    @patch('packages.valory.skills.staking_abci.behaviours.CallCheckpointBehaviour.wait_for_condition_with_sleep')
    def test_async_act_service_evicted(self, mock_wait_for_condition_with_sleep):
        # Mock the wait_for_condition_with_sleep method
        mock_wait_for_condition_with_sleep.side_effect = [True, True]

        # Set the service staking state to EVICTED
        self.behaviour.service_staking_state = StakingInteractBaseBehaviour.StakingState.EVICTED

        # Run the async_act method
        with patch.object(self.behaviour, 'send_a2a_transaction', return_value=None) as mock_send_a2a_transaction, \
             patch.object(self.behaviour, 'wait_until_round_end', return_value=None):
            self.behaviour.async_act()

        # Assert that no transaction was prepared or sent
        self.behaviour._prepare_safe_tx.assert_not_called()
        mock_send_a2a_transaction.assert_not_called()
