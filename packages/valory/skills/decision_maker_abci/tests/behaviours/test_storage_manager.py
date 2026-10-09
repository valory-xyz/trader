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

"""Tests for StorageManagerBehaviour."""

import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.chatui_abci.tool_keys import VALORY_LABEL, tool_key
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    AVAILABLE_TOOLS_STORE,
    NO_METADATA_HASH,
    OK_CODE,
    POLICY_STORE,
    StorageManagerBehaviour,
    UTILIZED_TOOLS_STORE,
)
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    ConsecutiveFailures,
    EGreedyPolicy,
)
from packages.valory.skills.mech_interact_abci.states.base import MechInfo, Service

V1_MECH = "0x" + "1" * 40
MECH_A = "0x" + "a" * 40
MECH_B = "0x" + "b" * 40
MECH_C = "0x" + "c" * 40


def _mech_info(address: str, relevant_tools: set) -> MechInfo:
    """A discovered mech as mech-interact records it."""
    return MechInfo(
        id="1",
        address=address,
        service=Service(metadata=[{"metadata": "0x" + "ab" * 32}], deliveries=[]),
        karma=1,
        received_requests=1,
        self_delivered=1,
        max_delivery_rate=1,
        relevant_tools=relevant_tools,
    )


def _valory(tool: str) -> str:
    """The key of a tool served by Valory's mechs."""
    return tool_key(VALORY_LABEL, tool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Since StorageManagerBehaviour is abstract, we use BlacklistingBehaviour
# which inherits from it, or we create a concrete subclass for testing.


def _return_gen(value):  # type: ignore[no-untyped-def]
    """Helper that creates a generator returning the given value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_policy(tools=None):  # type: ignore[no-untyped-def]
    """Create a test policy."""
    if tools is None:  # type: ignore[no-untyped-def]
        tools = {"tool1": AccuracyInfo(requests=5, accuracy=0.6)}
    return EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=3,
        quarantine_duration=100,
        accuracy_store=tools,
    )


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a concrete StorageManagerBehaviour subclass instance with mocked dependencies."""
    # Import a concrete subclass  # type: ignore[no-untyped-def]
    from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
        BlacklistingBehaviour,
    )

    behaviour = object.__new__(BlacklistingBehaviour)
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()
    behaviour._remote_accuracy_information = StringIO()
    behaviour._policy = None

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


class TestStorageManagerInit:
    """Tests for StorageManagerBehaviour.__init__."""

    @patch(
        "packages.valory.skills.decision_maker_abci.behaviours.storage_manager.DecisionMakerBaseBehaviour.__init__",
        return_value=None,
    )
    def test_init_sets_attributes(self, mock_parent_init: MagicMock) -> None:
        """__init__ should set default attributes."""
        from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
            BlacklistingBehaviour,
        )

        behaviour = BlacklistingBehaviour.__new__(BlacklistingBehaviour)  # type: ignore[type-abstract]
        StorageManagerBehaviour.__init__(behaviour)
        assert behaviour._mech_id == 0  # type: ignore[type-abstract]
        assert behaviour._mech_hash == ""
        assert behaviour._utilized_tools == {}
        assert behaviour._mech_tools == set()
        assert isinstance(behaviour._remote_accuracy_information, StringIO)


class TestStorageManagerProperties:
    """Tests for StorageManagerBehaviour properties."""

    def test_mech_tools_getter_raises_when_empty(self) -> None:
        """mech_tools should raise ValueError when not set."""
        behaviour = _make_behaviour()
        with pytest.raises(ValueError, match="tools have not been set"):
            _ = behaviour.mech_tools

    def test_mech_tools_setter_and_getter(self) -> None:
        """mech_tools setter and getter should work correctly."""
        behaviour = _make_behaviour()
        behaviour.mech_tools = {"tool1", "tool2"}
        assert behaviour.mech_tools == {"tool1", "tool2"}

    def test_mech_id_property(self) -> None:
        """mech_id should get/set correctly."""
        behaviour = _make_behaviour()
        assert behaviour.mech_id == 0
        behaviour.mech_id = 42
        assert behaviour.mech_id == 42

    def test_mech_hash_property(self) -> None:
        """mech_hash should get/set correctly."""
        behaviour = _make_behaviour()
        assert behaviour.mech_hash == ""
        behaviour.mech_hash = "abc123"
        assert behaviour.mech_hash == "abc123"

    def test_utilized_tools_property(self) -> None:
        """utilized_tools should get/set correctly."""
        behaviour = _make_behaviour()
        assert behaviour.utilized_tools == {}
        behaviour.utilized_tools = {"cond1": "tool1"}
        assert behaviour.utilized_tools == {"cond1": "tool1"}

    def test_remote_accuracy_information_property(self) -> None:
        """remote_accuracy_information should get/set correctly."""
        behaviour = _make_behaviour()
        sio = StringIO("test data")
        behaviour.remote_accuracy_information = sio
        assert behaviour.remote_accuracy_information is sio

    def test_mech_tools_api_property(self) -> None:
        """mech_tools_api should return context.agent_tools."""
        behaviour = _make_behaviour()
        mock_api = MagicMock()
        behaviour.__dict__["_context"].agent_tools = mock_api
        assert behaviour.mech_tools_api is mock_api


class TestSetup:
    """Tests for StorageManagerBehaviour.setup."""

    def test_setup_with_synchronized_data(self) -> None:
        """Setup should use synchronized_data.utilized_tools when available."""
        behaviour = _make_behaviour()
        tools = {"cond1": "tool1"}
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(utilized_tools=tools)
            behaviour.setup()
        assert behaviour.utilized_tools == tools

    def test_setup_with_synchronized_data_returns_none(self) -> None:
        """Setup should fall back when synchronized_data.utilized_tools is None."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(utilized_tools=None)
            with patch.object(
                behaviour, "_try_recover_utilized_tools", return_value={"a": "b"}
            ) as mock_recover:
                behaviour.setup()
        mock_recover.assert_called_once()
        assert behaviour.utilized_tools == {"a": "b"}

    def test_setup_with_exception_falls_back(self) -> None:
        """Setup should fall back to recovery when synchronized_data raises."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(
                utilized_tools=property(lambda s: (_ for _ in ()).throw(RuntimeError))
            )
            # Simulating property access that throws
            type(mock_sd.return_value).utilized_tools = PropertyMock(
                side_effect=RuntimeError("test")
            )
            with patch.object(
                behaviour, "_try_recover_utilized_tools", return_value={}
            ) as mock_recover:
                behaviour.setup()
        mock_recover.assert_called_once()


class TestSetMechAgentSpecs:
    """Tests for set_mech_agent_specs."""

    def test_sets_url_marketplace_v2(self) -> None:
        """When is_marketplace_v2, URL should be the hash directly."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "my_hash"

        mech_tools_api = MagicMock()
        mech_tools_api.__dict__["_frozen"] = True

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as mock_api:
            mock_api.return_value = mech_tools_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                behaviour.set_mech_agent_specs()

        assert mech_tools_api.url == "my_hash"

    def test_sets_url_not_marketplace_v2(self) -> None:
        """When not is_marketplace_v2, URL should include ipfs prefix."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "abc123"

        mech_tools_api = MagicMock()
        mech_tools_api.__dict__["_frozen"] = True

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as mock_api:
            mock_api.return_value = mech_tools_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=False)
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        ipfs_address="https://ipfs.io/"
                    )
                    from packages.valory.skills.decision_maker_abci.behaviours.base import (
                        CID_PREFIX,
                    )

                    behaviour.set_mech_agent_specs()

        assert mech_tools_api.url == "https://ipfs.io/" + CID_PREFIX + "abc123"


# Tests for get_tools_from_benchmark_file
# ---------------------------------------------------------------------------


class TestGetToolsFromBenchmarkFile:
    """Tests for _get_tools_from_benchmark_file."""

    def test_parses_tools_from_headers(self) -> None:
        """Should parse mech tools from benchmark dataset headers."""
        behaviour = _make_behaviour()
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_file = Path(tmpdir) / "dataset.csv"
            dataset_file.write_text("id,p_yes_tool1,p_yes_tool2,other_col\n")

            bm = MagicMock()
            bm.dataset_filename = "dataset.csv"
            bm.sep = ","
            bm.p_yes_field_part = "p_yes_"

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                with patch.object(
                    type(behaviour),
                    "benchmarking_mode",
                    new_callable=PropertyMock,
                    return_value=bm,
                ):
                    behaviour._get_tools_from_benchmark_file()

        assert behaviour._mech_tools == {"tool1", "tool2"}

    def test_empty_file_logs_error(self) -> None:
        """Should log error when benchmark file has no headers."""
        behaviour = _make_behaviour()
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_file = Path(tmpdir) / "dataset.csv"
            dataset_file.write_text("")

            bm = MagicMock()
            bm.dataset_filename = "dataset.csv"

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                with patch.object(
                    type(behaviour),
                    "benchmarking_mode",
                    new_callable=PropertyMock,
                    return_value=bm,
                ):
                    behaviour._get_tools_from_benchmark_file()

        behaviour.__dict__["_context"].logger.error.assert_called_once()


# Tests for get_mech_id
# ---------------------------------------------------------------------------


class TestGetMechId:
    """Tests for _get_mech_id."""

    def test_get_mech_id(self) -> None:
        """Should call _mech_contract_interact with correct params."""
        behaviour = _make_behaviour()
        behaviour._mech_contract_interact = MagicMock(return_value=_return_gen(True))  # type: ignore[method-assign]
        gen = behaviour._get_mech_id()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is True
        behaviour._mech_contract_interact.assert_called_once()


# Tests for get_mech_hash
# ---------------------------------------------------------------------------


class TestGetMechHash:
    """Tests for _get_mech_hash."""

    def test_get_mech_hash(self) -> None:
        """Should call contract_interact with correct params."""
        behaviour = _make_behaviour()
        behaviour._mech_id = 42
        behaviour.contract_interact = MagicMock(return_value=_return_gen(True))  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(agent_registry_address="0xregistry")
            gen = behaviour._get_mech_hash()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True


# Tests for check_hash
# ---------------------------------------------------------------------------


class TestCheckHash:
    """Tests for _check_hash."""

    def test_no_metadata_hash_logs_error(self) -> None:
        """Should log error when hash ends with NO_METADATA_HASH."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "0x" + NO_METADATA_HASH

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(mech_contract_address="0xmech")
            behaviour._check_hash()

        behaviour.__dict__["_context"].logger.error.assert_called_once()

    def test_valid_hash_no_error(self) -> None:
        """Should not log error for a valid hash."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "0xabcdef1234567890"

        behaviour._check_hash()
        behaviour.__dict__["_context"].logger.error.assert_not_called()


# Tests for get_mech_tools
# ---------------------------------------------------------------------------


class TestGetMechTools:
    """Tests for _get_mech_tools."""

    def test_get_mech_tools_success(self) -> None:
        """Should return True and set mech_tools when successful."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = ["tool1", "tool2"]
        mock_api.is_retries_exceeded.return_value = False

        mock_response = MagicMock()

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        mech_marketplace_v1_suitable_tools=frozenset(),
                        use_mech_marketplace=False,
                        mech_contract_address=V1_MECH,
                    )
                    behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                        return_value=_return_gen(mock_response)
                    )
                    behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                    behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                    gen = behaviour._get_mech_tools()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

        assert result is True
        assert behaviour._mech_tools == {
            tool_key(V1_MECH, "tool1"),
            tool_key(V1_MECH, "tool2"),
        }

    def test_get_mech_tools_intersects_with_v1_suitable_tools(self) -> None:
        """V1 path intersects on-chain tools with the V1 operator allowlist."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = ["tool1", "tool2", "tool3"]
        mock_api.is_retries_exceeded.return_value = False

        mock_response = MagicMock()

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=False)
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        mech_marketplace_v1_suitable_tools=frozenset(
                            {"tool1", "tool3"}
                        ),
                        use_mech_marketplace=False,
                        mech_contract_address=V1_MECH,
                    )
                    behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                        return_value=_return_gen(mock_response)
                    )
                    behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                    behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                    gen = behaviour._get_mech_tools()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

        assert result is True
        # tool2 dropped: not in the operator allowlist
        assert behaviour._mech_tools == {
            tool_key(V1_MECH, "tool1"),
            tool_key(V1_MECH, "tool3"),
        }

    def test_get_mech_tools_skips_v1_allowlist_on_v2(self) -> None:
        """The V1 allowlist guard suppresses intersection on V2 paths.

        Belt-and-suspenders: `_get_tools` already short-circuits on V2
        before reaching this method, but if a future refactor ever
        routes V2 through `_get_mech_tools` the inner guard must NOT
        apply the V1-shaped allowlist.
        """
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = ["tool1", "tool2", "tool3"]
        mock_api.is_retries_exceeded.return_value = False

        mock_response = MagicMock()

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        mech_marketplace_v1_suitable_tools=frozenset(
                            {"tool1", "tool3"}
                        ),
                        use_mech_marketplace=False,
                        mech_contract_address=V1_MECH,
                    )
                    behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                        return_value=_return_gen(mock_response)
                    )
                    behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                    behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                    gen = behaviour._get_mech_tools()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

        assert result is True
        # V2 path: tool2 NOT dropped despite being absent from the allowlist.
        assert behaviour._mech_tools == {
            tool_key(V1_MECH, "tool1"),
            tool_key(V1_MECH, "tool2"),
            tool_key(V1_MECH, "tool3"),
        }

    def test_get_mech_tools_retries_exceeded(self) -> None:
        """Should return True with error log when retries exceeded."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = None
        mock_api.is_retries_exceeded.return_value = True

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                    return_value=_return_gen(MagicMock())
                )
                behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                gen = behaviour._get_mech_tools()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is True
        mock_api.reset_retries.assert_called_once()

    def test_get_mech_tools_response_none(self) -> None:
        """Should return False when response is None."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = None
        mock_api.is_retries_exceeded.return_value = False
        mock_api.url = "http://test"

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                    return_value=_return_gen(MagicMock())
                )
                behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                gen = behaviour._get_mech_tools()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is False

    def test_get_mech_tools_empty_manifest(self) -> None:
        """Should return False when the mech's manifest tools list is empty."""
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = []
        mock_api.is_retries_exceeded.return_value = False

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                    return_value=_return_gen(MagicMock())
                )
                behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                gen = behaviour._get_mech_tools()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is False

    def test_get_mech_tools_normalizes_case(self) -> None:
        """Mixed-case manifest tools are lowercased before being stored.

        Verifies the lowercasing happens regardless of whether the V1
        allowlist intersection runs (allowlist is empty here, so the
        intersection branch is skipped). The downstream suitability
        classifier, ChatUI pin lookup, and V1 allowlist all key on
        lowercased names, so this normalization is the consumer-side
        contract every filter downstream depends on.
        """
        behaviour = _make_behaviour()
        behaviour._mech_hash = "valid_hash"

        mock_api = MagicMock()
        mock_api.get_spec.return_value = {"method": "GET", "url": "http://test"}
        mock_api.process_response.return_value = [
            "Prediction-Offline",
            "Superforcaster",
        ]
        mock_api.is_retries_exceeded.return_value = False

        with patch.object(
            type(behaviour), "mech_tools_api", new_callable=PropertyMock
        ) as api_mock:
            api_mock.return_value = mock_api
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=True)
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        mech_marketplace_v1_suitable_tools=frozenset(),
                        use_mech_marketplace=False,
                        mech_contract_address=V1_MECH,
                    )
                    behaviour.get_http_response = MagicMock(  # type: ignore[method-assign]
                        return_value=_return_gen(MagicMock())
                    )
                    behaviour._check_hash = MagicMock()  # type: ignore[method-assign]
                    behaviour.set_mech_agent_specs = MagicMock()  # type: ignore[method-assign]

                    gen = behaviour._get_mech_tools()
                    result = None
                    try:
                        while True:
                            next(gen)
                    except StopIteration as e:
                        result = e.value

        assert result is True
        assert behaviour._mech_tools == {
            tool_key(V1_MECH, "prediction-offline"),
            tool_key(V1_MECH, "superforcaster"),
        }


# Tests for get_tools
# ---------------------------------------------------------------------------


class TestGetTools:
    """Tests for _get_tools."""

    def test_get_tools_benchmarking(self) -> None:
        """Should call _get_tools_from_benchmark_file in benchmarking mode."""
        behaviour = _make_behaviour()
        bm = MagicMock()
        bm.enabled = True

        with patch.object(
            type(behaviour),
            "benchmarking_mode",
            new_callable=PropertyMock,
            return_value=bm,
        ):
            behaviour._get_tools_from_benchmark_file = MagicMock()  # type: ignore[method-assign]
            gen = behaviour._get_tools()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        behaviour._get_tools_from_benchmark_file.assert_called_once()

    def test_get_tools_marketplace_v2(self) -> None:
        """Marketplace v2 keys every (identity, tool) pair of the discovered mechs."""
        behaviour = _make_behaviour()
        bm = MagicMock()
        bm.enabled = False

        with (
            patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ),
            patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params,
            patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
        ):
            mock_params.return_value = MagicMock(
                valid_mechs=frozenset({MECH_A, MECH_B})
            )
            mock_sd.return_value = MagicMock(
                is_marketplace_v2=True,
                mechs_info=[
                    _mech_info(MECH_A, {"tool_a", "tool_b"}),
                    _mech_info(MECH_B.upper().replace("0X", "0x"), {"tool_b"}),
                    _mech_info(MECH_C, {"tool_b"}),
                ],
                selected_mechs=[MECH_C],
            )
            gen = behaviour._get_tools()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Valory's mechs share one key per tool; the ChatUI pin does not shrink
        # the universe.
        assert behaviour._mech_tools == {
            _valory("tool_a"),
            _valory("tool_b"),
            tool_key(MECH_C, "tool_b"),
        }

    def test_get_tools_standard_path(self) -> None:
        """Should call the three-step flow for standard tools retrieval."""
        behaviour = _make_behaviour()
        bm = MagicMock()
        bm.enabled = False

        call_count = 0

        def fake_wait(step) -> None:  # type: ignore[no-untyped-def, misc]
            """Fake wait_for_condition_with_sleep."""
            nonlocal call_count  # type: ignore[no-untyped-def]
            call_count += 1
            yield

        with patch.object(
            type(behaviour),
            "benchmarking_mode",
            new_callable=PropertyMock,
            return_value=bm,
        ):
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_marketplace_v2=False)
                behaviour.wait_for_condition_with_sleep = fake_wait  # type: ignore[method-assign]
                gen = behaviour._get_tools()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert call_count == 3


# Tests for try_recover_policy
# ---------------------------------------------------------------------------


class TestTryRecoverPolicy:
    """Tests for _try_recover_policy."""

    def test_recover_policy_from_file(self) -> None:
        """Should recover a policy from a valid file."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        serialized = policy.serialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / POLICY_STORE
            with open(policy_path, "w") as f:
                f.write(serialized)

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(
                    store_path=Path(tmpdir),
                    epsilon=0.1,
                    policy_threshold=3,
                    tool_quarantine_duration=100,
                )
                result = behaviour._try_recover_policy()

        assert result is not None
        assert isinstance(result, EGreedyPolicy)

    def test_recover_policy_file_not_found(self) -> None:
        """Should return None when file doesn't exist."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_policy()

        assert result is None


# Tests for get_init_policy
# ---------------------------------------------------------------------------


class TestGetInitPolicy:
    """Tests for _get_init_policy."""

    def test_creates_new_policy_on_failure(self) -> None:
        """Should create a new policy when recovery fails."""
        behaviour = _make_behaviour()

        with patch.object(behaviour, "_try_recover_policy", return_value=None):
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(
                    epsilon=0.2,
                    policy_threshold=5,
                    tool_quarantine_duration=200,
                )
                result = behaviour._get_init_policy()

        assert isinstance(result, EGreedyPolicy)
        assert result.eps == 0.2

    def test_returns_recovered_policy(self) -> None:
        """Should return the recovered policy when available."""
        behaviour = _make_behaviour()
        recovered = _make_policy()

        with patch.object(behaviour, "_try_recover_policy", return_value=recovered):
            result = behaviour._get_init_policy()

        assert result is recovered


# Tests for fetch_accuracy_info
# ---------------------------------------------------------------------------


class TestFetchAccuracyInfo:
    """Tests for _fetch_accuracy_info."""

    def test_fetch_accuracy_info_success(self) -> None:
        """Should return True and set accuracy info when successful."""
        behaviour = _make_behaviour()
        response = MagicMock()
        response.status_code = OK_CODE
        response.body = b"tool,requests,accuracy\ntool1,10,0.8"

        behaviour.get_http_response = MagicMock(return_value=_return_gen(response))  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                ipfs_address="https://ipfs.io/",
                tools_accuracy_hash="Qm123",
            )
            gen = behaviour._fetch_accuracy_info()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True

    def test_fetch_accuracy_info_bad_status(self) -> None:
        """Should return False when HTTP status is not OK."""
        behaviour = _make_behaviour()
        response = MagicMock()
        response.status_code = 404

        behaviour.get_http_response = MagicMock(return_value=_return_gen(response))  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                ipfs_address="https://ipfs.io/",
                tools_accuracy_hash="Qm123",
            )
            gen = behaviour._fetch_accuracy_info()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is False

    def test_fetch_accuracy_info_decode_error(self) -> None:
        """Should return False when response body can't be decoded."""
        behaviour = _make_behaviour()
        response = MagicMock()
        response.status_code = OK_CODE
        response.body = MagicMock()
        response.body.decode.side_effect = ValueError("decode error")

        behaviour.get_http_response = MagicMock(return_value=_return_gen(response))  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                ipfs_address="https://ipfs.io/",
                tools_accuracy_hash="Qm123",
            )
            gen = behaviour._fetch_accuracy_info()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is False


# Tests for prune_accuracy_store_to_current_tools
# ---------------------------------------------------------------------------


class TestPruneAccuracyStoreToCurrentTools:
    """Tests for _prune_accuracy_store_to_current_tools."""

    def test_drops_only_unoffered_records_without_history(self) -> None:
        """Unoffered records with requests or pending bets survive; empty ones go."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1"}
        policy = _make_policy(
            {
                "tool1": AccuracyInfo(),
                "earned": AccuracyInfo(requests=3, accuracy=0.5),
                "pending": AccuracyInfo(pending=1),
                "empty": AccuracyInfo(),
            }
        )
        behaviour._policy = policy

        behaviour._prune_accuracy_store_to_current_tools()

        assert set(policy.accuracy_store) == {"tool1", "earned", "pending"}
        behaviour.context.logger.info.assert_called_once()
        assert "['empty']" in behaviour.context.logger.info.call_args[0][0]

    def test_logs_nothing_when_nothing_is_dropped(self) -> None:
        """A store that only holds offered tools stays quiet."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1"}
        behaviour._policy = _make_policy({"tool1": AccuracyInfo()})

        behaviour._prune_accuracy_store_to_current_tools()

        behaviour.context.logger.info.assert_not_called()


# Tests for global_info_date_to_unix
# ---------------------------------------------------------------------------


class TestGlobalInfoDateToUnix:
    """Tests for _global_info_date_to_unix."""

    def test_valid_date_conversion(self) -> None:
        """Should convert a valid date string to unix timestamp."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = MagicMock(datetime_format="%Y-%m-%d %H:%M:%S")
            result = behaviour._global_info_date_to_unix("2024-01-01 00:00:00")

        assert isinstance(result, int)
        assert result > 0

    def test_invalid_date_returns_none(self) -> None:
        """Should return None for invalid date string."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = MagicMock(datetime_format="%Y-%m-%d %H:%M:%S")
            result = behaviour._global_info_date_to_unix("not a date")

        assert result is None


# Tests for parse_global_info_row
# ---------------------------------------------------------------------------


class TestParseGlobalInfoRow:
    """Tests for _parse_global_info_row."""

    def test_row_lands_under_valory(self) -> None:
        """The global file was measured on Valory's mechs."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {_valory("tool1"), tool_key(MECH_C, "tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"
        mock_fields.max = "max_date_col"
        row = {"tool_col": "tool1", "max_date_col": "2024-06-01 00:00:00"}
        tool_to_global_info = {}  # type: ignore[var-annotated]

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            with patch.object(
                behaviour, "_global_info_date_to_unix", return_value=1717200000
            ):
                result = behaviour._parse_global_info_row(row, 100, tool_to_global_info)

        assert result == 1717200000
        assert tool_to_global_info == {_valory("tool1"): row}

    def test_row_is_skipped_when_only_other_identities_serve_the_tool(self) -> None:
        """A non-Valory mech serving the same tool never inherits the global record."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {tool_key(MECH_C, "tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"
        row = {"tool_col": "tool1", "max_date_col": "2024-06-01 00:00:00"}
        tool_to_global_info = {}  # type: ignore[var-annotated]

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            result = behaviour._parse_global_info_row(row, 100, tool_to_global_info)

        assert result == 100
        assert tool_to_global_info == {}

    def test_irrelevant_tool_is_skipped(self) -> None:
        """Should return the same max_transaction_date for irrelevant tools."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {_valory("tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"

        row = {"tool_col": "unknown_tool"}

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            result = behaviour._parse_global_info_row(row, 100, {})

        assert result == 100

    def test_relevant_tool_updates_max_date(self) -> None:
        """Should update max_transaction_date for relevant tools."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {_valory("tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"
        mock_fields.max = "max_date_col"

        row = {"tool_col": "tool1", "max_date_col": "2024-06-01 00:00:00"}
        tool_to_global_info = {}  # type: ignore[var-annotated]

        with patch.object(  # type: ignore[var-annotated]
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            with patch.object(
                behaviour,
                "_global_info_date_to_unix",
                return_value=1717200000,
            ):
                result = behaviour._parse_global_info_row(row, 100, tool_to_global_info)

        assert result == 1717200000
        assert _valory("tool1") in tool_to_global_info

    def test_relevant_tool_with_lower_date(self) -> None:
        """Should keep current max_transaction_date when row date is lower."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {_valory("tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"
        mock_fields.max = "max_date_col"

        row = {"tool_col": "tool1", "max_date_col": "2024-01-01 00:00:00"}
        tool_to_global_info = {}  # type: ignore[var-annotated]

        with patch.object(  # type: ignore[var-annotated]
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            with patch.object(
                behaviour,
                "_global_info_date_to_unix",
                return_value=50,
            ):
                result = behaviour._parse_global_info_row(row, 100, tool_to_global_info)

        assert result == 100

    def test_relevant_tool_with_none_date(self) -> None:
        """Should keep current max when date parsing returns None."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {_valory("tool1")}

        mock_fields = MagicMock()
        mock_fields.tool = "tool_col"
        mock_fields.max = "max_date_col"

        row = {"tool_col": "tool1", "max_date_col": "invalid"}
        tool_to_global_info = {}  # type: ignore[var-annotated]

        with patch.object(  # type: ignore[var-annotated]
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            with patch.object(
                behaviour,
                "_global_info_date_to_unix",
                return_value=None,
            ):
                result = behaviour._parse_global_info_row(row, 100, tool_to_global_info)

        assert result == 100


# Tests for parse_global_info
# ---------------------------------------------------------------------------


class TestParseGlobalInfo:
    """Tests for _parse_global_info."""

    def test_parse_global_info(self) -> None:
        """Should parse CSV and return max_transaction_date and tool info."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1"}

        csv_data = "tool_col\tsep_col\tmax_date_col\treq_col\tacc_col\ntool1\tval\t2024-01-01\t5\t0.8\n"
        behaviour._remote_accuracy_information = StringIO(csv_data)

        mock_fields = MagicMock()
        mock_fields.sep = "\t"

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            with patch.object(
                behaviour,
                "_parse_global_info_row",
                return_value=1704067200,
            ) as mock_row:
                max_date, tool_info = behaviour._parse_global_info()

        assert max_date == 1704067200
        mock_row.assert_called_once()


# Tests for should_use_global_info
# ---------------------------------------------------------------------------


class TestShouldUseGlobalInfo:
    """Tests for _should_use_global_info."""

    def test_should_use_global_info_true(self) -> None:
        """Should return True when global timestamp is newer."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        policy.updated_ts = 1000
        behaviour._policy = policy

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(policy_store_update_offset=100)
            result = behaviour._should_use_global_info(1500)

        assert result is True

    def test_should_use_global_info_false(self) -> None:
        """Should return False when global timestamp is not newer enough."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        policy.updated_ts = 2000
        behaviour._policy = policy

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(policy_store_update_offset=100)
            result = behaviour._should_use_global_info(100)

        assert result is False


# Tests for overwrite_local_info
# ---------------------------------------------------------------------------


class TestOverwriteLocalInfo:
    """Tests for _overwrite_local_info."""

    def test_overwrites_accuracy_store(self) -> None:
        """Should overwrite accuracy store with global information."""
        behaviour = _make_behaviour()
        policy = _make_policy({"tool1": AccuracyInfo(requests=1, accuracy=0.5)})
        behaviour._policy = policy

        mock_fields = MagicMock()
        mock_fields.requests = "req_col"
        mock_fields.accuracy = "acc_col"

        tool_to_global_info = {
            "tool1": {"req_col": "10", "acc_col": "90.0"},
        }

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            behaviour._overwrite_local_info(tool_to_global_info)

        assert policy.accuracy_store["tool1"].requests == 10
        # The global file is in percent; the store keeps a fraction.
        assert policy.accuracy_store["tool1"].accuracy == pytest.approx(0.9)

    def test_seeded_and_locally_updated_records_share_one_scale(self) -> None:
        """After seeding, a local win moves the record by one request's worth."""
        behaviour = _make_behaviour()
        policy = _make_policy({})
        behaviour._policy = policy
        mock_fields = MagicMock(requests="req_col", accuracy="acc_col")

        with patch.object(
            type(behaviour), "acc_info_fields", new_callable=PropertyMock
        ) as mock_aif:
            mock_aif.return_value = mock_fields
            behaviour._overwrite_local_info(
                {"tool1": {"req_col": "3", "acc_col": "50.0"}}
            )
        policy.update_accuracy_store("tool1", winning=True)

        # (0.5 * 3 + 1) / 4: a percent seed would have stayed near 37.5 instead.
        assert policy.accuracy_store["tool1"].accuracy == pytest.approx(0.625)


# Tests for update_accuracy_store
# ---------------------------------------------------------------------------


class TestUpdateAccuracyStore:
    """Tests for _update_accuracy_store."""

    def test_calls_overwrite_when_global_info_newer(self) -> None:
        """Should call _overwrite_local_info when global info is newer."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1", "tool2"}
        policy = _make_policy({"tool1": AccuracyInfo(requests=1)})
        behaviour._policy = policy

        with patch.object(behaviour, "_should_use_global_info", return_value=True):
            with patch.object(behaviour, "_overwrite_local_info") as mock_overwrite:
                behaviour._update_accuracy_store(1000, {"tool1": {}})

        mock_overwrite.assert_called_once()
        # tool2 should be added as default
        assert "tool2" in policy.accuracy_store

    def test_does_not_overwrite_when_not_needed(self) -> None:
        """Should not call _overwrite_local_info when global info is not needed."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1"}
        policy = _make_policy({})
        behaviour._policy = policy

        with patch.object(behaviour, "_should_use_global_info", return_value=False):
            with patch.object(behaviour, "_overwrite_local_info") as mock_overwrite:
                behaviour._update_accuracy_store(100, {})

        mock_overwrite.assert_not_called()
        assert "tool1" in policy.accuracy_store


# Tests for update_policy_tools
# ---------------------------------------------------------------------------


class TestUpdatePolicyTools:
    """Tests for _update_policy_tools."""

    def test_update_policy_tools(self) -> None:
        """Should call all sub-methods to update policy."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy

        with patch.object(
            behaviour, "_prune_accuracy_store_to_current_tools"
        ) as mock_remove:
            with patch.object(
                behaviour, "_parse_global_info", return_value=(100, {"tool1": {}})
            ) as mock_parse:
                with patch.object(behaviour, "_update_accuracy_store") as mock_update:
                    behaviour._update_policy_tools()

        mock_remove.assert_called_once()
        mock_parse.assert_called_once()
        mock_update.assert_called_once_with(100, {"tool1": {}})


# Tests for set_policy
# ---------------------------------------------------------------------------


class TestSetPolicy:
    """Tests for _set_policy."""

    def test_set_policy_first_period(self) -> None:
        """Should set initial policy on first period."""
        behaviour = _make_behaviour()
        policy = _make_policy()

        def fake_wait(step, sleep_time_override=None) -> None:  # type: ignore[no-untyped-def, misc]
            """Fake wait_for_condition_with_sleep."""
            yield  # type: ignore[no-untyped-def]

        with patch.object(
            type(behaviour), "is_first_period", new_callable=PropertyMock
        ) as mock_fp:
            mock_fp.return_value = True
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_policy_set=False)
                with patch.object(behaviour, "_get_init_policy", return_value=policy):
                    with patch.object(
                        type(behaviour), "params", new_callable=PropertyMock
                    ) as mock_params:
                        mock_params.return_value = MagicMock(sleep_time=1)
                        behaviour.wait_for_condition_with_sleep = fake_wait  # type: ignore[method-assign]
                        with patch.object(
                            behaviour, "_update_policy_tools"
                        ) as mock_update:
                            gen = behaviour._set_policy()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert behaviour._policy is policy
        mock_update.assert_called_once()

    def test_set_policy_subsequent_period(self) -> None:
        """Should read policy from synchronized_data on subsequent periods."""
        behaviour = _make_behaviour()
        existing_policy = _make_policy()

        def fake_wait(step, sleep_time_override=None) -> None:  # type: ignore[no-untyped-def, misc]
            """Fake wait_for_condition_with_sleep."""
            yield  # type: ignore[no-untyped-def]

        with patch.object(
            type(behaviour), "is_first_period", new_callable=PropertyMock
        ) as mock_fp:
            mock_fp.return_value = False
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(
                    is_policy_set=True, policy=existing_policy
                )
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(sleep_time=1)
                    behaviour.wait_for_condition_with_sleep = fake_wait  # type: ignore[method-assign]
                    gen = behaviour._set_policy()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert behaviour._policy is existing_policy

    def test_set_policy_not_set_in_synced_data(self) -> None:
        """Should create initial policy when is_policy_set is False."""
        behaviour = _make_behaviour()
        policy = _make_policy()

        def fake_wait(step, sleep_time_override=None) -> None:  # type: ignore[no-untyped-def, misc]
            """Fake wait_for_condition_with_sleep."""
            yield  # type: ignore[no-untyped-def]

        with patch.object(
            type(behaviour), "is_first_period", new_callable=PropertyMock
        ) as mock_fp:
            mock_fp.return_value = False
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(is_policy_set=False)
                with patch.object(behaviour, "_get_init_policy", return_value=policy):
                    with patch.object(
                        type(behaviour), "params", new_callable=PropertyMock
                    ) as mock_params:
                        mock_params.return_value = MagicMock(sleep_time=1)
                        behaviour.wait_for_condition_with_sleep = fake_wait  # type: ignore[method-assign]
                        gen = behaviour._set_policy()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert behaviour._policy is policy


# Tests for try_recover_utilized_tools
# ---------------------------------------------------------------------------


class TestTryRecoverUtilizedTools:
    """Tests for _try_recover_utilized_tools."""

    def test_recover_from_file(self) -> None:
        """Should recover tools from a valid JSON file."""
        behaviour = _make_behaviour()
        tools_data = {"cond1": "tool1", "cond2": "tool2"}

        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / UTILIZED_TOOLS_STORE
            with open(tools_path, "w") as f:
                json.dump(tools_data, f)

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_utilized_tools()

        assert result == tools_data

    def test_file_not_found_returns_empty(self) -> None:
        """Should return empty dict when file doesn't exist."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_utilized_tools()

        assert result == {}

    def test_corrupt_file_returns_empty(self) -> None:
        """Should return empty dict when file content is corrupt."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / UTILIZED_TOOLS_STORE
            with open(tools_path, "w") as f:
                f.write("not valid json {{{{")

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_utilized_tools()

        assert result == {}
        behaviour.__dict__["_context"].logger.warning.assert_called()


# Tests for try_recover_mech_tools
# ---------------------------------------------------------------------------


class TestTryRecoverMechTools:
    """Tests for _try_recover_mech_tools."""

    def test_recover_from_file(self) -> None:
        """Should recover tools from a valid JSON file."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            tools_path = Path(tmpdir) / AVAILABLE_TOOLS_STORE
            with open(tools_path, "w") as f:
                json.dump(["tool1", "tool2"], f)

            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_mech_tools()

        assert result == ["tool1", "tool2"]

    def test_file_not_found_returns_none(self) -> None:
        """Should return None when file doesn't exist."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                result = behaviour._try_recover_mech_tools()

        assert result is None


# Tests for setup_policy_and_tools
# ---------------------------------------------------------------------------


class TestSetupPolicyAndTools:
    """Tests for _setup_policy_and_tools."""

    def test_returns_false_when_no_mech_tools(self) -> None:
        """Should return False when _get_tools produces no mech_tools."""
        behaviour = _make_behaviour()

        def fake_get_tools() -> None:  # type: ignore[no-untyped-def, misc]
            """Fake _get_tools."""
            yield  # type: ignore[no-untyped-def]

        behaviour._get_tools = fake_get_tools  # type: ignore[method-assign]

        gen = behaviour._setup_policy_and_tools()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is False

    def test_returns_true_when_tools_and_policy_set(self) -> None:
        """Should return True when tools and policy are set up."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1"}

        def fake_get_tools() -> None:  # type: ignore[no-untyped-def, misc]
            """Fake _get_tools that already set mech_tools."""
            behaviour._mech_tools = {"tool1"}  # type: ignore[no-untyped-def]
            yield

        def fake_set_policy() -> None:  # type: ignore[no-untyped-def, misc]
            """Fake _set_policy."""
            behaviour._policy = _make_policy()  # type: ignore[no-untyped-def]
            yield

        behaviour._get_tools = fake_get_tools  # type: ignore[method-assign]
        behaviour._set_policy = fake_set_policy  # type: ignore[method-assign]

        gen = behaviour._setup_policy_and_tools()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is True

    def test_invokes_maybe_publish_suitable_tools(self) -> None:
        """Setup must invoke _maybe_publish_suitable_tools, after the policy is set."""
        behaviour = _make_behaviour()
        calls = []

        def fake_get_tools() -> None:  # type: ignore[no-untyped-def, misc]
            """Fake _get_tools that sets mech_tools."""
            behaviour._mech_tools = {"tool1"}  # type: ignore[no-untyped-def]
            yield

        def fake_set_policy() -> None:  # type: ignore[no-untyped-def, misc]
            """Fake _set_policy."""
            calls.append("set_policy")  # type: ignore[no-untyped-def]
            behaviour._policy = _make_policy()
            yield

        def fake_publish() -> None:  # type: ignore[no-untyped-def, misc]
            """Spy for _maybe_publish_suitable_tools."""
            calls.append("publish")  # type: ignore[no-untyped-def]
            yield

        behaviour._get_tools = fake_get_tools  # type: ignore[method-assign]
        behaviour._set_policy = fake_set_policy  # type: ignore[method-assign]
        behaviour._maybe_publish_suitable_tools = fake_publish  # type: ignore[method-assign]

        gen = behaviour._setup_policy_and_tools()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is True
        # Wiring: publish is invoked, and only after the policy is set.
        assert calls == ["set_policy", "publish"]


# ---------------------------------------------------------------------------
# Tests for store methods
# ---------------------------------------------------------------------------


class TestStoreMethods:
    """Tests for _store_policy, _store_available_mech_tools, _store_utilized_tools."""

    def test_store_policy(self) -> None:
        """_store_policy should write policy to file."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                behaviour._store_policy()

            assert (Path(tmpdir) / POLICY_STORE).exists()

    def test_store_available_mech_tools(self) -> None:
        """_store_available_mech_tools should write tools to file."""
        behaviour = _make_behaviour()
        behaviour._mech_tools = {"tool1", "tool2"}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                behaviour._store_available_mech_tools()

            assert (Path(tmpdir) / AVAILABLE_TOOLS_STORE).exists()
            with open(Path(tmpdir) / AVAILABLE_TOOLS_STORE) as f:
                tools = json.load(f)
            assert set(tools) == {"tool1", "tool2"}

    def test_store_utilized_tools(self) -> None:
        """_store_utilized_tools should write tools to file."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {"cond1": "tool1"}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                behaviour._store_utilized_tools()

            assert (Path(tmpdir) / UTILIZED_TOOLS_STORE).exists()
            with open(Path(tmpdir) / UTILIZED_TOOLS_STORE) as f:
                tools = json.load(f)
            assert tools == {"cond1": "tool1"}

    def test_store_all(self) -> None:
        """_store_all should call all store methods."""
        behaviour = _make_behaviour()
        behaviour._store_policy = MagicMock()  # type: ignore[method-assign]
        behaviour._store_available_mech_tools = MagicMock()  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        behaviour._store_all()

        behaviour._store_policy.assert_called_once()
        behaviour._store_available_mech_tools.assert_called_once()
        behaviour._store_utilized_tools.assert_called_once()


# Tests for the (identity, tool) key universe and the legacy migration
# ---------------------------------------------------------------------------


def _with_identity_context(behaviour, mechs: list, valid_mechs: set):  # type: ignore[no-untyped-def]
    """Patch the behaviour's params and synchronized data, returning the patchers."""
    patchers = [
        patch.object(type(behaviour), "params", new_callable=PropertyMock),
        patch.object(type(behaviour), "synchronized_data", new_callable=PropertyMock),
    ]
    mock_params, mock_sd = (patcher.start() for patcher in patchers)
    mock_params.return_value = MagicMock(valid_mechs=frozenset(valid_mechs))
    mock_sd.return_value = MagicMock(mechs_info=mechs)
    return patchers


class TestToolKeyUniverse:
    """Tests for _identity, _mech_identities and _mechs_by_key."""

    @pytest.mark.parametrize(
        "address, valid_mechs, expected",
        [
            (MECH_A, {MECH_A}, VALORY_LABEL),
            (MECH_A.upper().replace("0X", "0x"), {MECH_A}, VALORY_LABEL),
            (MECH_C, {MECH_A}, MECH_C),
            (MECH_A, set(), MECH_A),
        ],
    )
    def test_identity(self, address: str, valid_mechs: set, expected: str) -> None:
        """Only mechs in valid_mechs share the Valory label; an empty list labels none."""
        behaviour = _make_behaviour()
        patchers = _with_identity_context(behaviour, [], valid_mechs)
        try:
            assert behaviour._identity(address) == expected
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_mechs_by_key_lists_every_mech_behind_a_pooled_key(self) -> None:
        """A pooled key maps to all of its mechs; an address key to its own mech."""
        behaviour = _make_behaviour()
        patchers = _with_identity_context(
            behaviour,
            [
                _mech_info(MECH_A, {"tool1", "tool2"}),
                _mech_info(MECH_B.upper().replace("0X", "0x"), {"tool1"}),
                _mech_info(MECH_C, {"tool1"}),
            ],
            {MECH_A, MECH_B},
        )
        try:
            mechs = behaviour._mechs_by_key()
            serving = behaviour._mech_identities("tool2")
        finally:
            for patcher in patchers:
                patcher.stop()
        assert mechs == {
            _valory("tool1"): [MECH_A, MECH_B],
            _valory("tool2"): [MECH_A],
            tool_key(MECH_C, "tool1"): [MECH_C],
        }
        assert serving == {MECH_A: VALORY_LABEL}

    def test_mechs_by_key_without_mechs_is_empty(self) -> None:
        """No discovered mechs means no keys, so the setup reports no tools."""
        behaviour = _make_behaviour()
        patchers = _with_identity_context(behaviour, [], {MECH_A})
        try:
            assert behaviour._mechs_by_key() == {}
        finally:
            for patcher in patchers:
                patcher.stop()

    @pytest.mark.parametrize(
        "use_mech_marketplace, expected",
        [(False, "0xlegacy"), (True, "0xpriority")],
    )
    def test_v1_mech_address_follows_the_marketplace_flag(
        self, use_mech_marketplace: bool, expected: str
    ) -> None:
        """V1 requests go to the legacy mech, or the static priority mech on the legacy marketplace."""
        behaviour = _make_behaviour()
        params = MagicMock(
            use_mech_marketplace=use_mech_marketplace,
            mech_contract_address="0xlegacy",
        )
        params.mech_marketplace_config.priority_mech_address = "0xpriority"
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = params
            assert behaviour.v1_mech_address == expected


def _make_migrating_behaviour(benchmarking: bool = False):  # type: ignore[no-untyped-def]
    """A behaviour ready to run the legacy migration."""
    behaviour = _make_behaviour()
    behaviour.context.benchmarking_mode.enabled = benchmarking
    return behaviour


class TestMigrateLegacyKeys:
    """Tests for _migrate_legacy_keys."""

    def test_moves_every_tool_keyed_record_under_valory(self) -> None:
        """Accuracy, failures and utilized tools keyed by tool name are all kept."""
        behaviour = _make_migrating_behaviour()
        policy = _make_policy(
            {
                "tool1": AccuracyInfo(requests=7, pending=2, accuracy=0.6),
                "tool2": AccuracyInfo(requests=3, accuracy=0.0),
            }
        )
        policy.consecutive_failures = {
            "tool1": ConsecutiveFailures(n_failures=1, timestamp=5)
        }
        behaviour._policy = policy
        behaviour._utilized_tools = {"0xtx": "tool1", "cond": "tool2"}

        behaviour._migrate_legacy_keys()

        assert policy.accuracy_store == {
            _valory("tool1"): AccuracyInfo(requests=7, pending=2, accuracy=0.6),
            _valory("tool2"): AccuracyInfo(requests=3, accuracy=0.0),
        }
        assert policy.consecutive_failures == {
            _valory("tool1"): ConsecutiveFailures(n_failures=1, timestamp=5)
        }
        assert behaviour._utilized_tools == {
            "0xtx": _valory("tool1"),
            "cond": _valory("tool2"),
        }
        assert set(policy.weighted_accuracy) == {_valory("tool1"), _valory("tool2")}

    @pytest.mark.parametrize(
        "stored, expected",
        [(66.0, 0.66), (1.5, 0.015), (1.0, 1.0), (0.66, 0.66), (0.0, 0.0)],
    )
    def test_percent_accuracy_is_converted_to_a_fraction(
        self, stored: float, expected: float
    ) -> None:
        """Seeded percent rows are brought to the fraction scale; fractions are kept."""
        behaviour = _make_migrating_behaviour()
        behaviour._policy = _make_policy(
            {"tool1": AccuracyInfo(requests=9, accuracy=stored)}
        )

        behaviour._migrate_legacy_keys()

        migrated = behaviour.policy.accuracy_store[_valory("tool1")]
        assert migrated.accuracy == pytest.approx(expected)
        assert migrated.requests == 9

    def test_identity_keyed_records_are_left_alone(self) -> None:
        """Running the migration on an already migrated store changes nothing."""
        behaviour = _make_migrating_behaviour()
        policy = _make_policy(
            {
                _valory("tool1"): AccuracyInfo(requests=7, accuracy=0.6),
                tool_key(MECH_C, "tool1"): AccuracyInfo(requests=2, accuracy=1.0),
            }
        )
        behaviour._policy = policy
        behaviour._utilized_tools = {"0xtx": tool_key(MECH_C, "tool1")}
        before = policy.serialize()

        behaviour._migrate_legacy_keys()

        assert policy.serialize() == before
        assert behaviour._utilized_tools == {"0xtx": tool_key(MECH_C, "tool1")}
        behaviour.context.logger.info.assert_not_called()

    def test_existing_valory_records_win_over_legacy_ones(self) -> None:
        """Records and failure counts already under the new key are not overwritten."""
        behaviour = _make_migrating_behaviour()
        policy = _make_policy(
            {
                _valory("tool1"): AccuracyInfo(requests=2, accuracy=1.0),
                "tool1": AccuracyInfo(requests=9, accuracy=50.0),
            }
        )
        policy.consecutive_failures = {
            _valory("tool1"): ConsecutiveFailures(n_failures=0, timestamp=9),
            "tool1": ConsecutiveFailures(n_failures=4, timestamp=1),
        }
        behaviour._policy = policy

        behaviour._migrate_legacy_keys()

        assert policy.accuracy_store == {
            _valory("tool1"): AccuracyInfo(requests=2, accuracy=1.0)
        }
        assert policy.consecutive_failures == {
            _valory("tool1"): ConsecutiveFailures(n_failures=0, timestamp=9)
        }

    def test_no_op_in_benchmarking_mode(self) -> None:
        """Benchmarking keys are bare tool names by design, not legacy rows."""
        behaviour = _make_migrating_behaviour(benchmarking=True)
        behaviour._policy = _make_policy(
            {"tool1": AccuracyInfo(requests=7, accuracy=60.0)}
        )
        behaviour._utilized_tools = {"0xtx": "tool1"}

        behaviour._migrate_legacy_keys()

        assert behaviour.policy.accuracy_store == {
            "tool1": AccuracyInfo(requests=7, accuracy=60.0)
        }
        assert behaviour._utilized_tools == {"0xtx": "tool1"}


def test_migrated_records_survive_the_first_period_prune() -> None:
    """Migrate then prune, as on the first period: the history is kept."""
    behaviour = _make_migrating_behaviour()
    behaviour._mech_tools = {_valory("tool1")}
    behaviour._policy = _make_policy(
        {
            "tool1": AccuracyInfo(requests=7, accuracy=60.0),
            "retired": AccuracyInfo(requests=4, pending=1, accuracy=0.5),
        }
    )

    behaviour._migrate_legacy_keys()
    behaviour._prune_accuracy_store_to_current_tools()

    assert set(behaviour.policy.accuracy_store) == {
        _valory("tool1"),
        _valory("retired"),
    }
