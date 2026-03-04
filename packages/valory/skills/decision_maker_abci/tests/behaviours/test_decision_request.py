# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Tests for DecisionRequestBehaviour."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.decision_request import (
    DecisionRequestBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionRequestPayload
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield  # type: ignore[no-untyped-def]


def _return_gen(value):  # type: ignore[no-untyped-def]
    """A generator that yields once and returns a value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a DecisionRequestBehaviour with mocked dependencies."""
    behaviour = object.__new__(DecisionRequestBehaviour)  # type: ignore[no-untyped-def]
    behaviour._metadata = None

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecisionRequestBehaviour:
    """Tests for DecisionRequestBehaviour."""

    def test_matching_round(self) -> None:
        """matching_round should be DecisionRequestRound."""
        assert DecisionRequestBehaviour.matching_round == DecisionRequestRound

    def test_init(self) -> None:
        """__init__ should set _metadata to None."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.decision_request.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = DecisionRequestBehaviour(name="test", skill_context=MagicMock())
            assert behaviour._metadata is None

    def test_n_slots_supported_true(self) -> None:
        """n_slots_supported should be True when slot_count matches BINARY_N_SLOTS."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            assert behaviour.n_slots_supported is True

    def test_n_slots_supported_false(self) -> None:
        """n_slots_supported should be False when slot_count does not match."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=5)
            assert behaviour.n_slots_supported is False

    def test_metadata_property(self) -> None:
        """Metadata property should return asdict of _metadata."""
        from dataclasses import asdict

        from packages.valory.skills.mech_interact_abci.states.base import MechMetadata

        behaviour = _make_behaviour()
        meta = MechMetadata(prompt="test?", tool="tool1", nonce="n1")
        behaviour._metadata = meta
        result = behaviour.metadata
        assert result == asdict(meta)
        assert result["prompt"] == "test?"
        assert result["tool"] == "tool1"
        assert result["nonce"] == "n1"

    def test_setup_unsupported_slots(self) -> None:
        """Setup should return early when n_slots_supported is False."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=5)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)
                behaviour.setup()
                assert behaviour._metadata is None

    def test_setup_benchmarking_enabled(self) -> None:
        """Setup should return early when benchmarking is enabled."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=True)
                behaviour.setup()
                assert behaviour._metadata is None

    def test_setup_creates_metadata(self) -> None:
        """Setup should create metadata when conditions are met."""
        from string import Template

        behaviour = _make_behaviour()

        mock_bet = MagicMock()
        mock_bet.title = "Will it rain?"
        mock_bet.yes = "Yes"
        mock_bet.no = "No"

        template = Template("$question $yes $no")

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                slot_count=BINARY_N_SLOTS, prompt_template=template
            )
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)
                with patch.object(
                    type(behaviour), "sampled_bet", new_callable=PropertyMock
                ) as mock_sb:
                    mock_sb.return_value = mock_bet
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(mech_tool="tool1")
                        behaviour.setup()

        assert behaviour._metadata is not None
        assert behaviour._metadata.prompt == "Will it rain? Yes No"
        assert behaviour._metadata.tool == "tool1"

    def test_async_act_with_metadata(self) -> None:
        """async_act should produce a payload with mech_requests when _metadata is set."""
        from packages.valory.skills.mech_interact_abci.states.base import MechMetadata

        behaviour = _make_behaviour()
        behaviour._metadata = MechMetadata(prompt="q?", tool="t1", nonce="n1")

        payloads_sent = []

        def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock finish behaviour."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = MagicMock(mech_timed_out=False)

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, DecisionRequestPayload)
        assert payload.mech_requests is not None
        # The mech_requests should be valid JSON
        parsed = json.loads(payload.mech_requests)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_async_act_no_metadata(self) -> None:
        """async_act should produce a payload with None mech_requests when _metadata is None."""
        behaviour = _make_behaviour()
        behaviour._metadata = None

        payloads_sent = []

        def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock finish behaviour."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = MagicMock(mech_timed_out=False)

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert payload.mech_requests is None

    def test_async_act_unsupported_slots_nullifies_mocking_mode(self) -> None:
        """When n_slots is unsupported, mocking_mode in payload should be None."""
        behaviour = _make_behaviour()
        behaviour._metadata = None

        payloads_sent = []

        def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock finish behaviour."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=5)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = MagicMock(mech_timed_out=False)

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].mocking_mode is None

    def test_async_act_benchmarking_loads_bet_id_manager(self) -> None:
        """In benchmarking mode, should initialize bet_id_row_manager when empty."""
        from packages.valory.skills.mech_interact_abci.states.base import MechMetadata

        behaviour = _make_behaviour()
        behaviour._metadata = MechMetadata(prompt="q?", tool="t1", nonce="n1")

        payloads_sent = []

        def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock finish behaviour."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.initialize_bet_id_row_manager = MagicMock(return_value={"q1": [1, 2]})  # type: ignore[method-assign]

        shared_state = MagicMock()
        shared_state.mech_timed_out = False
        shared_state.bet_id_row_manager = {}

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=True)
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = shared_state

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        behaviour.initialize_bet_id_row_manager.assert_called_once()
        assert shared_state.bet_id_row_manager == {"q1": [1, 2]}

    def test_async_act_benchmarking_bet_id_already_loaded(self) -> None:
        """In benchmarking mode with non-empty bet_id_row_manager, should not reinitialize."""
        from packages.valory.skills.mech_interact_abci.states.base import MechMetadata

        behaviour = _make_behaviour()
        behaviour._metadata = MechMetadata(prompt="q?", tool="t1", nonce="n1")

        payloads_sent = []

        def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock finish behaviour."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.initialize_bet_id_row_manager = MagicMock(return_value={"q1": [1]})  # type: ignore[method-assign]

        shared_state = MagicMock()
        shared_state.mech_timed_out = False
        # Already has data -> len() != 0 -> should skip initialization
        shared_state.bet_id_row_manager = {"existing": [1, 2]}

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(slot_count=BINARY_N_SLOTS)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=True)
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = shared_state

                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        # Should NOT have called initialize_bet_id_row_manager since it was already loaded
        behaviour.initialize_bet_id_row_manager.assert_not_called()
        assert len(payloads_sent) == 1

    def test_initialize_bet_id_row_manager(self) -> None:
        """initialize_bet_id_row_manager should parse CSV and return mapping."""
        behaviour = _make_behaviour()

        csv_content = "question_id,p_yes_tool1,other\nq1,0.8,x\nq2,0.9,y\nq1,0.7,z\n"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            tmp_path = Path(f.name)

        try:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=tmp_path.parent)
                with patch.object(
                    type(behaviour), "benchmarking_mode", new_callable=PropertyMock
                ) as mock_bm:
                    mock_bm.return_value = MagicMock(
                        dataset_filename=tmp_path.name,
                        question_id_field="question_id",
                    )
                    result = behaviour.initialize_bet_id_row_manager()
        finally:
            tmp_path.unlink()

        assert "q1" in result
        assert "q2" in result
        assert len(result["q1"]) == 2
        assert len(result["q2"]) == 1
        assert result["q1"] == [1, 3]
        assert result["q2"] == [2]
