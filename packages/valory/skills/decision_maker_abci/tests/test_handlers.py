# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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
"""This module contains the tests for the handlers for the decision maker abci."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Union
from unittest import mock
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from aea.configurations.data_types import PublicId
from aea.skills.base import Handler

from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http import HttpMessage
from packages.valory.protocols.ipfs import IpfsMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import (
    ABCIHandler,
    ContractApiHandler,
    HttpHandler,
    HttpMethod,
    IpfsHandler,
    LedgerApiHandler,
    SigningHandler,
    TendermintHandler,
)


@dataclass
class GetHandlerTestCase:
    """Get Handler test case."""

    name: str
    url: str
    method: str
    expected_handler: Union[str, None]


@dataclass
class HandleTestCase:
    """Handle test case."""

    name: str
    message_performative: str
    message_sender: str
    get_handler_return_value: tuple
    message_url: Union[str, None] = None
    message_method: Union[str, None] = None
    update_return_value: Union[MagicMock, None] = None
    expected_logger_call: Union[str, None] = None
    expected_handler_call: bool = False


@pytest.mark.parametrize(
    "handler, base_handler",
    [
        (ABCIHandler, BaseABCIRoundHandler),
        (SigningHandler, BaseSigningHandler),
        (LedgerApiHandler, BaseLedgerApiHandler),
        (ContractApiHandler, BaseContractApiHandler),
        (TendermintHandler, BaseTendermintHandler),
    ],
)
def test_handler(handler: Handler, base_handler: Handler) -> None:
    """Test that the 'handlers.py' of the DecisionMakerAbci can be imported."""
    handler = handler(
        name="dummy_handler",
        skill_context=MagicMock(skill_id=PublicId.from_str("dummy/skill:0.1.0")),
    )

    assert isinstance(handler, base_handler)


class TestIpfsHandler:
    """Class for testing the IPFS Handler."""

    def setup_method(self) -> None:
        """Set up the tests."""
        self.context = MagicMock()
        self.handler = IpfsHandler(name="", skill_context=self.context)

    def test_handle(self) -> None:
        """Test the 'handle' method."""
        callback = MagicMock()
        request_reference = "reference"
        self.handler.shared_state.req_to_callback = {}
        self.handler.shared_state.req_to_callback[request_reference] = callback

        mock_dialogue = MagicMock()
        mock_dialogue.dialogue_label.dialogue_reference = [request_reference]

        with mock.patch.object(
            self.handler.context.ipfs_dialogues, "update", return_value=mock_dialogue
        ):
            mock_message = MagicMock(performative=IpfsMessage.Performative.FILES)
            self.handler.handle(mock_message)

        callback.assert_called_once_with(mock_message, mock_dialogue)

    def test_handle_negative_performative_not_allowed(self) -> None:
        """Test the 'handle' method, negative case (performative not allowed)."""
        self.handler.handle(MagicMock())


class TestHttpHandler:
    """Class for testing the Http Handler."""

    def setup_method(self) -> None:
        """Set up the tests."""
        self.context = MagicMock()
        self.context.logger = MagicMock()
        self.handler = HttpHandler(name="", skill_context=self.context)
        self.handler.context.params.service_endpoint = "http://localhost:8080/some/path"
        self.handler.setup()

    def test_setup(self) -> None:
        """Test the setup method of HttpHandler."""

        config_uri_base_hostname = "localhost"
        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )
        local_ip_regex = r"192\.168(\.\d{1,3}){2}"
        hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        health_url_regex = rf"{hostname_regex}\/healthcheck"
        assert self.handler.handler_url_regex == rf"{hostname_regex}\/.*"
        # Check that the health route is present in the handler's routes

        found = False
        for methods, routes in self.handler.routes.items():
            for regex, handler in routes:
                if (
                    methods == (HttpMethod.GET.value, HttpMethod.HEAD.value)
                    and regex == health_url_regex
                    and handler == self.handler._handle_get_health
                ):
                    found = True
                    break
        assert found, "Health route not found in handler.routes"
        assert self.handler.json_content_header == "Content-Type: application/json\n"

    @pytest.mark.parametrize(
        "test_case",
        [
            GetHandlerTestCase(
                name="Happy Path",
                url="http://localhost:8080/healthcheck",
                method=HttpMethod.GET.value,
                expected_handler="_handle_get_health",
            ),
            GetHandlerTestCase(
                name="No url match",
                url="http://invalid.url/not/matching",
                method=HttpMethod.GET.value,
                expected_handler=None,
            ),
            GetHandlerTestCase(
                name="No method match",
                url="http://localhost:8080/some/path",
                method=HttpMethod.POST.value,
                expected_handler="_handle_bad_request",
            ),
        ],
    )
    def test_get_handler(self, test_case: GetHandlerTestCase) -> None:
        """Test _get_handler."""
        url = test_case.url
        method = test_case.method

        if test_case.expected_handler is not None:
            expected_handler = getattr(self.handler, test_case.expected_handler)
        else:
            expected_handler = test_case.expected_handler
        expected_captures: Dict[Any, Any] = {}

        handler, captures = self.handler._get_handler(url, method)

        assert handler == expected_handler
        assert captures == expected_captures

    @pytest.mark.parametrize(
        "test_case",
        [
            HandleTestCase(
                name="Test Handle",
                message_performative=HttpMessage.Performative.RESPONSE,
                message_sender="incorrect sender",
                get_handler_return_value=(None, {}),
            ),
            HandleTestCase(
                name="Test Handle No Handler",
                message_performative=HttpMessage.Performative.REQUEST,
                message_sender=str(HTTP_SERVER_PUBLIC_ID.without_hash()),
                message_url="http://localhost/test",
                message_method="GET",
                get_handler_return_value=(None, {}),
            ),
            HandleTestCase(
                name="Test Handle Invalid Dialogue",
                message_performative=HttpMessage.Performative.REQUEST,
                message_sender=str(HTTP_SERVER_PUBLIC_ID.without_hash()),
                message_url="http://localhost/test",
                message_method="GET",
                get_handler_return_value=(lambda x, y: None, {}),
                update_return_value=None,
                expected_logger_call="Received invalid http message={}, unidentified dialogue.",
            ),
            HandleTestCase(
                name="Test Handle Valid Message",
                message_performative=HttpMessage.Performative.REQUEST,
                message_sender=str(HTTP_SERVER_PUBLIC_ID.without_hash()),
                message_url="http://localhost/test",
                message_method="GET",
                get_handler_return_value=(MagicMock(), {"key": "value"}),
                update_return_value=MagicMock(),
                expected_handler_call=True,
                expected_logger_call="Received http request with method={}, url={} and body={!r}",
            ),
        ],
    )
    def test_handle(self, test_case: HandleTestCase) -> None:
        """Parameterized test for 'handle' method."""

        self.message = MagicMock(performative=test_case.message_performative)
        self.message.sender = test_case.message_sender
        self.message.url = test_case.message_url
        self.message.method = test_case.message_method

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=test_case.get_handler_return_value,
        ), patch.object(
            BaseHttpHandler, "handle", return_value=None
        ) as mock_super_handle:
            if not test_case.expected_logger_call:
                self.handler.handle(self.message)
                mock_super_handle.assert_called_once_with(self.message)
            else:
                http_dialogues_mock = MagicMock()
                self.context.http_dialogues = http_dialogues_mock
                http_dialogues_mock.update.return_value = test_case.update_return_value
                self.handler.handle(self.message)

                if not test_case.expected_handler_call:
                    self.context.logger.info.assert_called_with(
                        test_case.expected_logger_call.format(self.message)
                    )
                else:
                    test_case.get_handler_return_value[0].assert_called_with(
                        self.message,
                        http_dialogues_mock.update.return_value,
                        key="value",
                    )
                    self.context.logger.info.assert_called_with(
                        test_case.expected_logger_call.format(
                            self.message.method, self.message.url, self.message.body
                        )
                    )

    def test_handle_exception_in_handler(self) -> None:
        """Test handle() recovers gracefully when handler raises an exception."""
        self.message = MagicMock(
            performative=HttpMessage.Performative.REQUEST,
        )
        self.message.sender = str(HTTP_SERVER_PUBLIC_ID.without_hash())
        self.message.url = "http://localhost:8080/healthcheck"
        self.message.method = "GET"
        self.message.version = "1.1"
        self.message.headers = "Content-Type: text/plain"
        self.message.body = b""

        handler_that_raises = MagicMock(side_effect=ValueError("boom"))

        http_dialogues_mock = MagicMock()
        http_dialogue_mock = MagicMock()
        http_response_mock = MagicMock()
        http_dialogues_mock.update.return_value = http_dialogue_mock
        http_dialogue_mock.reply.return_value = http_response_mock
        self.context.http_dialogues = http_dialogues_mock

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(handler_that_raises, {}),
        ), patch.object(BaseHttpHandler, "handle", return_value=None):
            self.handler.handle(self.message)

        # Verify error was logged
        self.context.logger.error.assert_called_once()
        assert "boom" in self.context.logger.error.call_args[0][0]

        # Verify 500 response was sent
        http_dialogue_mock.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=self.message,
            version=self.message.version,
            status_code=500,
            status_text="Internal Server Error",
            headers=self.message.headers,
            body=b"",
        )

        # Verify response was queued
        self.context.outbox.put_message.assert_called_once_with(
            message=http_response_mock
        )

    def test_handle_bad_request(self) -> None:
        """Test handle with a bad request."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        # Configure the mocks
        http_msg.version = "1.1"
        http_msg.headers = {"Content-Type": "application/json"}
        http_dialogue.reply.return_value = MagicMock()

        # Call the method
        self.handler._handle_bad_request(http_msg, http_dialogue)

        # Verify that the reply method was called with the correct arguments
        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=400,
            status_text="Bad request",
            headers=http_msg.headers,
            body=b"",
        )

        # Verify that the logger was called with the expected message
        http_response = http_dialogue.reply.return_value
        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(http_response)
        )

        # Verify that the message was put into the outbox
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=http_response
        )

    def test_send_ok_response(self) -> None:
        """Test send_ok_response function."""
        http_msg = MagicMock()
        http_msg.headers = ""

        http_dialogue = MagicMock()
        http_dialogue.reply.return_value = MagicMock()

        data = {"key": "value"}
        mock_response = http_dialogue.reply.return_value

        # Call the method
        self.handler._send_ok_response(http_msg, http_dialogue, data)

        # Verify that the reply method was called with the correct arguments
        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=200,
            status_text="Success",
            headers=f"{self.handler.json_content_header}{http_msg.headers}",
            body=json.dumps(data).encode("utf-8"),
        )

        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(mock_response)
        )
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=mock_response
        )

    def test_send_not_found_response(self) -> None:
        """Test _send_not_found_response."""

        http_msg = MagicMock()
        http_dialogue = MagicMock()

        # Create a mock response
        mock_response = MagicMock()
        http_dialogue.reply.return_value = mock_response

        self.handler._send_not_found_response(http_msg, http_dialogue)

        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=404,
            status_text="Not found",
            headers=http_msg.headers,
            body=b"",
        )

        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(mock_response)
        )
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=mock_response
        )

    def test_round_sequence_property(self) -> None:
        """Test the round_sequence property returns context.state.round_sequence."""
        mock_round_seq = MagicMock()
        self.handler.context.state.round_sequence = mock_round_seq
        result = self.handler.round_sequence
        assert result is mock_round_seq

    def test_synchronized_data_property(self) -> None:
        """Test the synchronized_data property returns a SynchronizedData instance."""
        mock_db = MagicMock()
        self.handler.context.state.round_sequence.latest_synchronized_data.db = mock_db
        result = self.handler.synchronized_data
        assert result.db is mock_db

    def test_has_transitioned_true(self) -> None:
        """Test _has_transitioned returns True when there is a transition height."""
        self.handler.context.state.round_sequence.last_round_transition_height = 10
        result = self.handler._has_transitioned()
        assert result is True

    def test_has_transitioned_false_zero(self) -> None:
        """Test _has_transitioned returns False when transition height is 0."""
        self.handler.context.state.round_sequence.last_round_transition_height = 0
        result = self.handler._has_transitioned()
        assert result is False

    def test_has_transitioned_value_error(self) -> None:
        """Test _has_transitioned returns False when ValueError is raised."""
        type(self.handler.context.state.round_sequence).last_round_transition_height = (
            PropertyMock(side_effect=ValueError("no height"))
        )
        result = self.handler._has_transitioned()
        assert result is False

    def test_handle_too_early(self) -> None:
        """Test _handle_too_early sends a 425 response."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        mock_response = MagicMock()
        http_dialogue.reply.return_value = mock_response

        self.handler._handle_too_early(http_msg, http_dialogue)

        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=425,
            status_text="The state machine has not started yet! Please try again later...",
            headers=http_msg.headers,
            body=b"",
        )
        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(mock_response)
        )
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=mock_response
        )

    def test_waiting_for_a_mech_response_true(self) -> None:
        """Test waiting_for_a_mech_response returns True when in relevant round."""
        from packages.valory.skills.decision_maker_abci.states.decision_receive import (
            DecisionReceiveRound,
        )

        self.handler.context.state.round_sequence.current_round_id = (
            DecisionReceiveRound.auto_round_id()
        )
        result = self.handler.waiting_for_a_mech_response
        assert result is True

    def test_waiting_for_a_mech_response_false(self) -> None:
        """Test waiting_for_a_mech_response returns False when not in relevant round."""
        self.handler.context.state.round_sequence.current_round_id = (
            "some_other_round_id"
        )
        result = self.handler.waiting_for_a_mech_response
        assert result is False

    def test_check_required_funds_true(self) -> None:
        """Test _check_required_funds returns True when balance exceeds threshold."""
        mock_db = MagicMock()
        self.handler.context.state.round_sequence.latest_synchronized_data.db = mock_db
        self.handler.context.params.agent_balance_threshold = 100
        # Mock synchronized_data.wallet_balance
        with patch.object(
            type(self.handler),
            "synchronized_data",
            new_callable=PropertyMock,
        ) as mock_sync:
            mock_sync_data = MagicMock()
            mock_sync_data.wallet_balance = 200
            mock_sync.return_value = mock_sync_data
            result = self.handler._check_required_funds()
            assert result is True

    def test_check_required_funds_false(self) -> None:
        """Test _check_required_funds returns False when balance is below threshold."""
        self.handler.context.params.agent_balance_threshold = 500
        with patch.object(
            type(self.handler),
            "synchronized_data",
            new_callable=PropertyMock,
        ) as mock_sync:
            mock_sync_data = MagicMock()
            mock_sync_data.wallet_balance = 100
            mock_sync.return_value = mock_sync_data
            result = self.handler._check_required_funds()
            assert result is False

    def test_is_mech_reliable(self) -> None:
        """Test _is_mech_reliable returns True when timestamp is old enough."""
        old_timestamp = 0  # Very old timestamp
        self.handler.context.params.expected_mech_response_time = 60
        with patch.object(
            type(self.handler),
            "synchronized_data",
            new_callable=PropertyMock,
        ) as mock_sync:
            mock_sync_data = MagicMock()
            mock_sync_data.decision_receive_timestamp = old_timestamp
            mock_sync.return_value = mock_sync_data
            result = self.handler._is_mech_reliable()
            assert result is True

    def test_is_mech_reliable_false(self) -> None:
        """Test _is_mech_reliable returns False when timestamp is recent."""
        future_timestamp = int(datetime.now(timezone.utc).timestamp()) + 10000
        self.handler.context.params.expected_mech_response_time = 60
        with patch.object(
            type(self.handler),
            "synchronized_data",
            new_callable=PropertyMock,
        ) as mock_sync:
            mock_sync_data = MagicMock()
            mock_sync_data.decision_receive_timestamp = future_timestamp
            mock_sync.return_value = mock_sync_data
            result = self.handler._is_mech_reliable()
            assert result is False

    def test_handle_get_health_not_transitioned(self) -> None:
        """Test _handle_get_health calls _handle_too_early when not transitioned."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        http_dialogue.reply.return_value = MagicMock()

        with patch.object(
            self.handler, "_has_transitioned", return_value=False
        ), patch.object(self.handler, "_handle_too_early") as mock_too_early:
            self.handler._handle_get_health(http_msg, http_dialogue)
            mock_too_early.assert_called_once_with(http_msg, http_dialogue)

    def test_handle_get_health_success(self) -> None:
        """Test _handle_get_health returns a full health response."""

        class MockStakingState(Enum):
            """Mock staking state."""

            STAKED = 1

        http_msg = MagicMock()
        http_msg.headers = ""
        http_dialogue = MagicMock()
        http_dialogue.reply.return_value = MagicMock()

        # Mock _has_transitioned
        with patch.object(
            self.handler, "_has_transitioned", return_value=True
        ), patch.object(
            self.handler, "_check_required_funds", return_value=True
        ), patch.object(
            self.handler, "_is_mech_reliable", return_value=True
        ), patch.object(
            type(self.handler),
            "synchronized_data",
            new_callable=PropertyMock,
        ) as mock_sync, patch.object(
            type(self.handler),
            "round_sequence",
            new_callable=PropertyMock,
        ) as mock_rs, patch.object(
            type(self.handler),
            "waiting_for_a_mech_response",
            new_callable=PropertyMock,
            return_value=False,
        ):
            # Configure synchronized_data mock
            mock_sync_data = MagicMock()
            mock_sync_data.is_staking_kpi_met = True
            mock_sync_data.service_staking_state = MockStakingState.STAKED
            mock_sync_data.period_count = 5
            mock_sync.return_value = mock_sync_data

            # Configure round_sequence mock
            mock_round_seq = MagicMock()
            mock_round_seq.block_stall_deadline_expired = False
            mock_round_seq.last_round_transition_timestamp = datetime.now()
            mock_round_seq.current_round_id = "some_round"

            # Configure abci_app mock
            mock_prev_round = MagicMock()
            mock_prev_round.round_id = "prev_round"
            mock_prev_round_cls = type(mock_prev_round)
            mock_round_seq.abci_app._previous_rounds = [mock_prev_round]

            mock_event = MagicMock()
            mock_round_seq.abci_app.transition_function = {
                mock_prev_round_cls: {mock_event: MagicMock()}
            }
            mock_round_seq.abci_app.event_to_timeout = {mock_event: 30}

            mock_rs.return_value = mock_round_seq

            # Set up params
            self.handler.context.params.reset_pause_duration = 10

            self.handler._handle_get_health(http_msg, http_dialogue)

            # Verify reply was called
            http_dialogue.reply.assert_called_once()
            call_kwargs = http_dialogue.reply.call_args[1]
            assert call_kwargs["status_code"] == 200
