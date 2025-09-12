# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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
from typing import Any, Dict, Union
from unittest import mock
from unittest.mock import MagicMock, patch

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

    def setup(self) -> None:
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

    def setup(self) -> None:
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
        http_dialogue = MagicMock()
        data = {"key": "value"}

        mock_response = MagicMock()
        http_dialogue.reply.return_value = mock_response

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
