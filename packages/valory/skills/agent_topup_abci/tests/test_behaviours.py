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

"""Tests for the behaviours of the agent top-up skill."""

from typing import Any, Dict, Generator, Iterator, List, Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.contracts.gnosis_safe.contract import SafeOperation
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.agent_topup_abci.behaviours import (
    AgentTopUpBehaviour,
    LAST_TOPUP_CHECK_KEY,
    TOPUP_CHECK_INTERVAL_SECONDS,
    TOPUP_TXS_THIS_CHECK_KEY,
)
from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload
from packages.valory.skills.agent_topup_abci.rounds import AgentTopUpRound
from packages.valory.skills.agent_topup_abci.tests.helpers import (
    AGENT,
    ETHER,
    SAFE,
    funds_status,
    real_topup_rule,
)
from packages.valory.skills.agent_topup_abci.utils import WXDAI_ADDRESS
from packages.valory.skills.funds_manager.behaviours import (
    GET_AGENT_TOPUP_METHOD_NAME,
    GET_FUNDS_STATUS_METHOD_NAME,
)
from packages.valory.skills.funds_manager.models import FundRequirements
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    skill_input_hex_to_payload,
)

NOW = 1_800_000_000
SUBMITTER = AgentTopUpRound.auto_round_id()
SAFE_TX_HASH = "0x" + "ab" * 32
WITHDRAW_DATA = bytes.fromhex("2e1a7d4d" + "00" * 32)

STATE = ContractApiMessage.Performative.STATE
ERROR = ContractApiMessage.Performative.ERROR


def _response(performative: Any, body: Optional[Dict] = None) -> MagicMock:
    """A contract API response."""
    response = MagicMock(performative=performative)
    response.state.body = body or {}
    return response


class _Harness:
    """Runs AgentTopUpBehaviour against a funds status and a contract API stub."""

    def __init__(
        self,
        chain: str,
        funds: FundRequirements,
        shared_state: Optional[Dict[str, Any]] = None,
        tx_submitter: Optional[str] = None,
        responses: Optional[List[MagicMock]] = None,
    ) -> None:
        """Set up the behaviour's context."""
        self.shared_state: Dict[str, Any] = dict(shared_state or {})
        self.shared_state[GET_FUNDS_STATUS_METHOD_NAME] = MagicMock(return_value=funds)
        self.shared_state[GET_AGENT_TOPUP_METHOD_NAME] = real_topup_rule(chain)
        setup: Dict[str, Any] = {"safe_contract_address": SAFE}
        if tx_submitter is not None:
            setup["tx_submitter"] = tx_submitter

        self.context = MagicMock(agent_address=AGENT, shared_state=self.shared_state)
        self.context.params.default_chain_id = chain
        self.context.state.synchronized_data.db = AbciAppDB(
            setup_data=AbciAppDB.data_to_lists(setup)
        )
        self.responses: Iterator[MagicMock] = iter(responses or [])
        self.contract_calls: List[Dict[str, Any]] = []
        self.sent: List[AgentTopUpPayload] = []

    def _contract_api(self, **kwargs: Any) -> Generator[None, None, MagicMock]:
        """Record a contract API call and return the next stubbed response."""
        self.contract_calls.append(kwargs)
        yield
        return next(self.responses)

    def _send(self, payload: AgentTopUpPayload) -> Generator[None, None, None]:
        """Record the payload sent."""
        self.sent.append(payload)
        yield

    def run(self) -> Optional[str]:
        """Run the behaviour once and return the tx hash it voted for."""
        behaviour = object.__new__(AgentTopUpBehaviour)
        with (
            patch.object(
                AgentTopUpBehaviour,
                "context",
                new_callable=PropertyMock,
                return_value=self.context,
            ),
            patch.object(
                AgentTopUpBehaviour, "get_contract_api_response", new=self._contract_api
            ),
            patch.object(AgentTopUpBehaviour, "send_a2a_transaction", new=self._send),
            patch.object(
                AgentTopUpBehaviour, "wait_until_round_end", new=lambda _: iter(())
            ),
            patch.object(AgentTopUpBehaviour, "set_done"),
            patch(
                "packages.valory.skills.agent_topup_abci.behaviours.time.time",
                return_value=NOW,
            ),
        ):
            for _ in behaviour.async_act():
                pass

        [payload] = self.sent
        assert payload.tx_submitter == SUBMITTER
        return payload.tx_hash


def _decode(tx_hex: str) -> Dict[str, Any]:
    """Decode the tx settlement hex."""
    keys = ("safe_tx_hash", "ether_value", "safe_tx_gas", "to_address", "data")
    tx = skill_input_hex_to_payload(tx_hex)
    assert tx["operation"] == SafeOperation.CALL.value
    return {key: tx[key] for key in keys}


class TestGate:
    """The check runs once an hour, plus the re-entries after a settled top-up tx."""

    def test_recent_check_skips(self) -> None:
        """Within the hour, a fresh visit reads nothing."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_TXS_THIS_CHECK_KEY: 0},
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_not_called()
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == NOW - 60

    @pytest.mark.parametrize(
        "shared_state",
        [
            {},
            {
                LAST_TOPUP_CHECK_KEY: NOW - TOPUP_CHECK_INTERVAL_SECONDS,
                TOPUP_TXS_THIS_CHECK_KEY: 2,
            },
        ],
    )
    def test_opens_on_start_and_after_an_hour(
        self, shared_state: Dict[str, Any]
    ) -> None:
        """The gate opens on start and an hour later, and resets the tx counter."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER, 10 * ETHER),
            shared_state=shared_state,
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_called_once()
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == NOW
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 0

    def test_reentry_skips_the_gate(self) -> None:
        """After a settled top-up tx, the round checks again within the hour."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_TXS_THIS_CHECK_KEY: 1},
            tx_submitter=SUBMITTER,
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_called_once()

    def test_reentry_stops_after_two_txs(self) -> None:
        """No more than two top-up txs per check."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_TXS_THIS_CHECK_KEY: 2},
            tx_submitter=SUBMITTER,
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_not_called()


class TestNoMove:
    """Only a MOVE decision prepares a tx."""

    @pytest.mark.parametrize(
        "signer_balance, safe_balance",
        [
            (ETHER, 10 * ETHER),  # NONE: the Agent Signer is above its threshold
            (ETHER // 100, 10 * ETHER),  # SIGNER_ALERT: below min_tx_balance
            (ETHER // 10, 0),  # SAFE_ALERT: the Agent Safe is empty
            (None, 10 * ETHER),  # NONE: unread balance
        ],
    )
    def test_no_tx(
        self, signer_balance: Optional[int], safe_balance: Optional[int]
    ) -> None:
        """Alerts and nothing-due end the check without a tx."""
        harness = _Harness(
            "polygon", funds_status("polygon", signer_balance, safe_balance)
        )

        assert harness.run() is None
        assert harness.contract_calls == []
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 0


class TestTransfer:
    """The Agent Safe sends native token to the Agent Signer."""

    def test_moves_what_the_signer_requires(self) -> None:
        """A single plain CALL to the Agent Signer, carrying the amount as value."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        tx = _decode(harness.run() or "")

        assert tx == {
            "safe_tx_hash": SAFE_TX_HASH[2:],
            "ether_value": 19 * ETHER // 10,
            "safe_tx_gas": 0,
            "to_address": AGENT,
            "data": b"",
        }
        [call] = harness.contract_calls
        assert call["contract_address"] == SAFE
        assert call["contract_callable"] == "get_raw_safe_transaction_hash"
        assert call["chain_id"] == "polygon"
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 1

    def test_moves_all_of_a_short_safe(self) -> None:
        """An Agent Safe holding less than required sends all it holds."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, ETHER // 2),
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        assert _decode(harness.run() or "")["ether_value"] == ETHER // 2

    def test_safe_hash_failure_prepares_nothing(self) -> None:
        """A Safe hash that cannot be read ends the check."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            responses=[_response(ERROR)],
        )

        assert harness.run() is None
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 0


class TestGnosisUnwrap:
    """On Gnosis, Agent Safe wxDAI is unwrapped first when its xDAI is short."""

    def test_unwraps_the_xdai_shortfall(self) -> None:
        """The first tx unwraps `move - xDAI`, as a plain CALL to WXDAI."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, ETHER, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            responses=[
                _response(STATE, {"data": WITHDRAW_DATA}),
                _response(STATE, {"tx_hash": SAFE_TX_HASH}),
            ],
        )

        tx = _decode(harness.run() or "")

        withdraw_call, safe_call = harness.contract_calls
        assert withdraw_call["contract_address"] == WXDAI_ADDRESS
        assert withdraw_call["contract_callable"] == "build_withdraw_tx"
        assert withdraw_call["amount"] == 19 * ETHER // 10 - ETHER
        assert safe_call["to_address"] == WXDAI_ADDRESS
        assert safe_call["value"] == 0
        assert tx["to_address"] == WXDAI_ADDRESS
        assert tx["ether_value"] == 0
        assert tx["data"] == WITHDRAW_DATA
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 1

    def test_transfers_when_xdai_covers_the_move(self) -> None:
        """Enough Agent Safe xDAI goes straight to the transfer."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, 5 * ETHER, wxdai_balance=ETHER, track_wxdai=True
            ),
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        tx = _decode(harness.run() or "")

        assert tx["to_address"] == AGENT
        assert tx["ether_value"] == 19 * ETHER // 10

    def test_transfers_the_unwrapped_xdai_after_an_unwrap(self) -> None:
        """After the unwrap, the Agent Signer's gas makes the need exceed the xDAI: move the xDAI."""
        gas = 10**15
        unwrapped = 19 * ETHER // 10 - ETHER
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis",
                ETHER // 10 - gas,
                ETHER + unwrapped,
                wxdai_balance=5 * ETHER - unwrapped,
                track_wxdai=True,
            ),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_TXS_THIS_CHECK_KEY: 1},
            tx_submitter=SUBMITTER,
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        tx = _decode(harness.run() or "")

        assert tx["to_address"] == AGENT
        assert tx["ether_value"] == ETHER + unwrapped
        assert harness.shared_state[TOPUP_TXS_THIS_CHECK_KEY] == 2

    def test_no_xdai_after_an_unwrap_prepares_nothing(self) -> None:
        """A second unwrap is never prepared in the same check."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, 0, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_TXS_THIS_CHECK_KEY: 1},
            tx_submitter=SUBMITTER,
        )

        assert harness.run() is None
        assert harness.contract_calls == []

    def test_withdraw_build_failure_prepares_nothing(self) -> None:
        """An unwrap that cannot be built ends the check."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, ETHER, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            responses=[_response(ERROR)],
        )

        assert harness.run() is None
        assert len(harness.contract_calls) == 1
