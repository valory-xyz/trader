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

from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.contracts.gnosis_safe.contract import SafeOperation
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.agent_topup_abci.behaviours import (
    AgentTopUpBehaviour,
    LAST_TOPUP_CHECK_KEY,
    TOPUP_CHECK_INTERVAL_SECONDS,
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
from packages.valory.skills.agent_topup_abci.utils import (
    TOPUP_SUCCEEDED_KEY,
    WXDAI_ADDRESS,
)
from packages.valory.skills.funds_manager.behaviours import (
    GET_AGENT_TOPUP_METHOD_NAME,
    GET_FUNDS_STATUS_METHOD_NAME,
)
from packages.valory.skills.funds_manager.models import FundRequirements
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
    skill_input_hex_to_payload,
)

NOW = 1_800_000_000
SUBMITTER = AgentTopUpRound.auto_round_id()
SAFE_TX_HASH = "0x" + "ab" * 32
WITHDRAW_DATA = bytes.fromhex("2e1a7d4d" + "00" * 32)

SIGNER_SETTLEMENT_THRESHOLD = ETHER // 100

STATE = ContractApiMessage.Performative.STATE
ERROR = ContractApiMessage.Performative.ERROR


def _settled_tx(to_address: str) -> str:
    """The tx settlement hex of a settled top-up tx sent to `to_address`."""
    return hash_payload_to_hex(SAFE_TX_HASH[2:], 0, 0, to_address, b"")


def _response(performative: Any, body: Optional[Dict] = None) -> MagicMock:
    """A contract API response."""
    response = MagicMock(performative=performative)
    response.state.body = body or {}
    return response


class _Harness:
    """Runs AgentTopUpBehaviour against a funds status and a contract API stub."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        chain: str,
        funds: FundRequirements,
        shared_state: Optional[Dict[str, Any]] = None,
        tx_submitter: Optional[str] = None,
        settled_to: str = AGENT,
        settled_tx: Optional[str] = None,
        responses: Optional[List[MagicMock]] = None,
        retry: bool = False,
    ) -> None:
        """Set up the behaviour's context."""
        self.shared_state: Dict[str, Any] = shared_state if shared_state else {}
        self.shared_state[GET_FUNDS_STATUS_METHOD_NAME] = MagicMock(return_value=funds)
        self.shared_state[GET_AGENT_TOPUP_METHOD_NAME] = real_topup_rule(chain)
        setup: Dict[str, Any] = {"safe_contract_address": SAFE}
        if tx_submitter is not None:
            setup["tx_submitter"] = tx_submitter
            setup["most_voted_tx_hash"] = settled_tx or _settled_tx(settled_to)

        self.context = MagicMock(agent_address=AGENT, shared_state=self.shared_state)
        self.context.params.default_chain_id = chain
        self.context.params.agent_balance_threshold = SIGNER_SETTLEMENT_THRESHOLD
        self.context.state.round_sequence.last_round_id = (
            SUBMITTER if retry else "previous_round"
        )
        self.context.state.synchronized_data.db = AbciAppDB(
            setup_data=AbciAppDB.data_to_lists(setup)
        )
        self.responses: List[MagicMock] = list(responses or [])
        self.contract_calls: List[Dict[str, Any]] = []
        self.sent: List[AgentTopUpPayload] = []

    def _contract_api(self, **kwargs: Any) -> Generator[None, None, MagicMock]:
        """Record a contract API call and return the next stubbed response."""
        self.contract_calls.append(kwargs)
        yield
        return self.responses.pop(0)

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
        assert payload.tx_submitter == (None if payload.tx_hash is None else SUBMITTER)
        return payload.tx_hash


def _decode(tx_hex: str) -> Dict[str, Any]:
    """Decode the tx settlement hex."""
    keys = ("safe_tx_hash", "ether_value", "safe_tx_gas", "to_address", "data")
    tx = skill_input_hex_to_payload(tx_hex)
    assert tx["operation"] == SafeOperation.CALL.value
    return {key: tx[key] for key in keys}


class TestGate:
    """A check runs on start, then once an hour; settled top-up txs and retries re-enter it."""

    def test_recent_check_skips(self) -> None:
        """Within the hour, a fresh visit reads nothing."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60},
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_not_called()
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == NOW - 60

    @pytest.mark.parametrize(
        "shared_state",
        [{}, {LAST_TOPUP_CHECK_KEY: NOW - TOPUP_CHECK_INTERVAL_SECONDS}],
    )
    def test_opens_on_start_and_after_an_hour(
        self, shared_state: Dict[str, Any]
    ) -> None:
        """The gate opens on start and an hour later."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER, 10 * ETHER),
            shared_state=shared_state,
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_called_once()
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == NOW

    def test_retry_repeats_the_check(self) -> None:
        """A visit that ended in no majority is retried, though it already closed the gate."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            responses=[
                _response(STATE, {"tx_hash": SAFE_TX_HASH}),
                _response(STATE, {"tx_hash": SAFE_TX_HASH}),
            ],
        )
        first = harness.run()
        harness.sent.clear()
        harness.context.state.round_sequence.last_round_id = SUBMITTER

        assert first is not None
        assert harness.run() == first

    def test_failed_status_read_prepares_nothing(self) -> None:
        """A failing status read skips the top-up instead of the period."""
        harness = _Harness("polygon", funds_status("polygon", ETHER // 10, 10 * ETHER))
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].side_effect = RuntimeError(
            "rpc down"
        )

        assert harness.run() is None
        assert "rpc down" in harness.context.logger.warning.call_args[0][0]

    @pytest.mark.parametrize(
        "chain, funds, responses",
        [
            ("polygon", funds_status("polygon", ETHER // 10, 10 * ETHER), []),
            (
                "polygon",
                funds_status("polygon", ETHER // 10, 10 * ETHER),
                [_response(ERROR)],
            ),
            (
                "gnosis",
                funds_status(
                    "gnosis",
                    ETHER // 10,
                    ETHER,
                    wxdai_balance=5 * ETHER,
                    track_wxdai=True,
                ),
                [_response(ERROR)],
            ),
        ],
        ids=["status read", "Safe hash", "unwrap build"],
    )
    def test_failure_leaves_the_gate_open(
        self, chain: str, funds: FundRequirements, responses: List[MagicMock]
    ) -> None:
        """A check that fails before a decision is retried next period, not an hour later."""
        last_check = NOW - TOPUP_CHECK_INTERVAL_SECONDS
        harness = _Harness(
            chain,
            funds,
            shared_state={LAST_TOPUP_CHECK_KEY: last_check},
            responses=responses,
        )
        if not responses:
            harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].side_effect = (
                RuntimeError
            )

        assert harness.run() is None
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == last_check

    @pytest.mark.parametrize(
        "signer_balance, safe_balance", [(None, 10 * ETHER), (ETHER // 10, None)]
    )
    def test_unread_balance_leaves_the_gate_open(
        self, signer_balance: Optional[int], safe_balance: Optional[int]
    ) -> None:
        """An unread native balance is no decision: the next period checks again."""
        last_check = NOW - TOPUP_CHECK_INTERVAL_SECONDS
        harness = _Harness(
            "polygon",
            funds_status("polygon", signer_balance, safe_balance),
            shared_state={LAST_TOPUP_CHECK_KEY: last_check, TOPUP_SUCCEEDED_KEY: True},
        )

        assert harness.run() is None
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == last_check
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is True

    def test_retried_check_closes_the_gate_once_its_tx_is_prepared(self) -> None:
        """A check that failed is retried next period, and closes the gate once it prepares its tx."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            responses=[_response(ERROR), _response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )
        failed = harness.run()
        harness.sent.clear()

        assert failed is None
        assert harness.run() is not None
        assert harness.shared_state[LAST_TOPUP_CHECK_KEY] == NOW


class TestNoMove:
    """Only a non-zero move prepares a tx."""

    @pytest.mark.parametrize(
        "signer_balance, safe_balance",
        [
            (ETHER, 10 * ETHER),  # the Agent Signer is above its threshold
            (ETHER // 10, 0),  # the Agent Safe is empty
            (None, 10 * ETHER),  # unread balance
        ],
    )
    def test_no_tx(
        self, signer_balance: Optional[int], safe_balance: Optional[int]
    ) -> None:
        """A zero move ends the check without a tx."""
        harness = _Harness(
            "polygon", funds_status("polygon", signer_balance, safe_balance)
        )

        assert harness.run() is None
        assert not harness.contract_calls


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

    @pytest.mark.parametrize(
        "signer_balance, tops_up",
        [
            (SIGNER_SETTLEMENT_THRESHOLD - 1, False),
            (SIGNER_SETTLEMENT_THRESHOLD, True),
        ],
    )
    def test_skips_a_signer_below_the_settlement_balance_threshold(
        self, signer_balance: int, tops_up: bool
    ) -> None:
        """The tx settlement would wait for a refill below `agent_balance_threshold`."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", signer_balance, 10 * ETHER),
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        assert (harness.run() is not None) is tops_up

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

    def test_settled_transfer_ends_the_check(self) -> None:
        """No further tx follows a settled transfer, even if the Agent Signer is still short."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60},
            tx_submitter=SUBMITTER,
        )

        assert harness.run() is None
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].assert_not_called()


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

    @pytest.mark.parametrize("extra_xdai", [0, ETHER])
    def test_transfers_when_xdai_covers_the_move(self, extra_xdai: int) -> None:
        """Agent Safe xDAI that covers the move, exactly or more, goes straight to the transfer."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis",
                ETHER // 10,
                19 * ETHER // 10 + extra_xdai,
                wxdai_balance=ETHER,
                track_wxdai=True,
            ),
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        tx = _decode(harness.run() or "")

        assert tx["to_address"] == AGENT
        assert tx["ether_value"] == 19 * ETHER // 10

    @pytest.mark.parametrize("shared_state", [{LAST_TOPUP_CHECK_KEY: NOW - 60}, {}])
    def test_transfers_the_unwrapped_xdai_after_an_unwrap(
        self, shared_state: Dict[str, Any]
    ) -> None:
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
            shared_state=shared_state,
            tx_submitter=SUBMITTER,
            settled_to=WXDAI_ADDRESS,
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        tx = _decode(harness.run() or "")

        assert tx["to_address"] == AGENT
        assert tx["ether_value"] == ETHER + unwrapped

    def test_no_xdai_after_an_unwrap_prepares_nothing(self) -> None:
        """A second unwrap is never prepared in the same check."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, 0, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_SUCCEEDED_KEY: True},
            tx_submitter=SUBMITTER,
            settled_to=WXDAI_ADDRESS,
        )

        assert harness.run() is None
        assert not harness.contract_calls
        assert "holds 0 wei" in harness.context.logger.warning.call_args[0][0]
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is False

    def test_unwrap_gas_pushing_the_signer_below_the_settlement_threshold_skips_the_transfer(
        self,
    ) -> None:
        """The unwrap's gas can take an Agent Signer just above `agent_balance_threshold` below it."""
        gas = 10**15
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis",
                SIGNER_SETTLEMENT_THRESHOLD + gas // 2 - gas,
                2 * ETHER,
                wxdai_balance=3 * ETHER,
                track_wxdai=True,
            ),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60},
            tx_submitter=SUBMITTER,
            settled_to=WXDAI_ADDRESS,
        )

        assert harness.run() is None
        assert not harness.contract_calls
        assert "below the" in harness.context.logger.warning.call_args[0][0]

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

    def test_unwrap_then_transfer_then_success(self) -> None:
        """Each visit acts on the tx the previous one settled, ending in a succeeded top-up."""
        unwrap = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, ETHER, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            responses=[
                _response(STATE, {"data": WITHDRAW_DATA}),
                _response(STATE, {"tx_hash": SAFE_TX_HASH}),
            ],
        )
        unwrap_tx = unwrap.run()
        transfer = _Harness(
            "gnosis",
            funds_status(
                "gnosis",
                ETHER // 10,
                19 * ETHER // 10,
                wxdai_balance=4 * ETHER,
                track_wxdai=True,
            ),
            shared_state=unwrap.shared_state,
            tx_submitter=SUBMITTER,
            settled_tx=unwrap_tx,
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )
        transfer_tx = transfer.run()
        done = _Harness(
            "gnosis",
            funds_status(
                "gnosis", 2 * ETHER, 0, wxdai_balance=4 * ETHER, track_wxdai=True
            ),
            shared_state=transfer.shared_state,
            tx_submitter=SUBMITTER,
            settled_tx=transfer_tx,
        )

        assert _decode(unwrap_tx or "")["to_address"] == WXDAI_ADDRESS
        assert _decode(transfer_tx or "")["to_address"] == AGENT
        assert TOPUP_SUCCEEDED_KEY not in transfer.shared_state
        assert done.run() is None
        assert done.shared_state[TOPUP_SUCCEEDED_KEY] is True


class TestTopUpSucceeded:
    """`/funds-status` may report the top-up deficits only once a transfer has settled."""

    def test_settled_transfer_succeeds(self) -> None:
        """A settled transfer to the Agent Signer marks the top-up as succeeded."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", 2 * ETHER, 8 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_SUCCEEDED_KEY: False},
            tx_submitter=SUBMITTER,
        )

        assert harness.run() is None
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is True

    def test_settled_unwrap_is_not_a_success(self) -> None:
        """A settled wxDAI unwrap moves nothing to the Agent Signer yet."""
        harness = _Harness(
            "gnosis",
            funds_status(
                "gnosis", ETHER // 10, 0, wxdai_balance=5 * ETHER, track_wxdai=True
            ),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_SUCCEEDED_KEY: False},
            tx_submitter=SUBMITTER,
            settled_to=WXDAI_ADDRESS,
        )

        assert harness.run() is None
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is False

    @pytest.mark.parametrize(
        "signer_balance",
        [ETHER // 10, ETHER],  # a top-up tx is prepared / nothing is due
    )
    def test_new_check_keeps_the_success(self, signer_balance: int) -> None:
        """A signer that drains between checks is still reported as the agent's to top up."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", signer_balance, 10 * ETHER),
            shared_state={TOPUP_SUCCEEDED_KEY: True},
            responses=[_response(STATE, {"tx_hash": SAFE_TX_HASH})],
        )

        harness.run()
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is True

    @pytest.mark.parametrize(
        "chain, funds",
        [
            ("polygon", funds_status("polygon", ETHER // 10, 10 * ETHER)),
            (
                "gnosis",
                funds_status(
                    "gnosis",
                    ETHER // 10,
                    ETHER,
                    wxdai_balance=5 * ETHER,
                    track_wxdai=True,
                ),
            ),
        ],
        ids=["transfer", "unwrap"],
    )
    def test_failed_build_clears_the_success(
        self, chain: str, funds: FundRequirements
    ) -> None:
        """A top-up tx that cannot be built, even on a retry, does not keep an earlier success."""
        harness = _Harness(
            chain,
            funds,
            shared_state={TOPUP_SUCCEEDED_KEY: True},
            responses=[_response(ERROR)],
            retry=True,
        )

        assert harness.run() is None
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is False

    def test_failed_read_clears_the_success(self) -> None:
        """A check that cannot read the status does not keep an earlier success."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER, 10 * ETHER),
            shared_state={TOPUP_SUCCEEDED_KEY: True},
        )
        harness.shared_state[GET_FUNDS_STATUS_METHOD_NAME].side_effect = RuntimeError

        assert harness.run() is None
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is False

    def test_success_stands_between_checks(self) -> None:
        """Within the hour, the last outcome is kept."""
        harness = _Harness(
            "polygon",
            funds_status("polygon", ETHER // 10, 10 * ETHER),
            shared_state={LAST_TOPUP_CHECK_KEY: NOW - 60, TOPUP_SUCCEEDED_KEY: True},
        )

        assert harness.run() is None
        assert harness.shared_state[TOPUP_SUCCEEDED_KEY] is True
