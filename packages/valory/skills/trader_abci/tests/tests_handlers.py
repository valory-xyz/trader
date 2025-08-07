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
"""This module contains the tests for the handlers for the trader abci."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from aea.configurations.data_types import PublicId
from aea.skills.base import Handler

from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import ABCIRoundHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
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
from packages.valory.skills.chatui_abci.handlers import HttpContentType
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import HttpMethod
from packages.valory.skills.decision_maker_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.decision_maker_abci.tests.test_handlers import (
    GetHandlerTestCase,
    HandleTestCase,
)
from packages.valory.skills.trader_abci.handlers import (
    ContractApiHandler,
    DEFAULT_HEADER,
    HttpHandler,
    IpfsHandler,
    LedgerApiHandler,
    SigningHandler,
    TendermintHandler,
    TraderHandler,
)


@pytest.mark.parametrize(
    "handler, base_handler",
    [
        (TraderHandler, ABCIRoundHandler),
        (SigningHandler, BaseSigningHandler),
        (LedgerApiHandler, BaseLedgerApiHandler),
        (ContractApiHandler, BaseContractApiHandler),
        (TendermintHandler, BaseTendermintHandler),
        (IpfsHandler, BaseIpfsHandler),
    ],
)
def test_handler(handler: Handler, base_handler: Handler) -> None:
    """Test that the 'handlers.py' of the TraderAbci can be imported."""
    handler = handler(
        name="dummy_handler",
        skill_context=MagicMock(skill_id=PublicId.from_str("dummy/skill:0.1.0")),
    )

    assert isinstance(handler, base_handler)


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
        agent_info_url_regex = rf"{hostname_regex}\/agent-info"
        assert self.handler.handler_url_regex == rf"{hostname_regex}\/.*"
        assert self.handler.routes == {
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                (agent_info_url_regex, self.handler._handle_get_agent_info),
            ],
        }

    def test_get_content_type(self) -> None:
        """Test _get_content_type method."""
        # Test known extensions
        assert (
            self.handler._get_content_type(Path("test.js")) == HttpContentType.JS.header
        )
        assert (
            self.handler._get_content_type(Path("test.html"))
            == HttpContentType.HTML.header
        )
        assert (
            self.handler._get_content_type(Path("test.json"))
            == HttpContentType.JSON.header
        )
        assert (
            self.handler._get_content_type(Path("test.css"))
            == HttpContentType.CSS.header
        )
        assert (
            self.handler._get_content_type(Path("test.png"))
            == HttpContentType.PNG.header
        )
        assert (
            self.handler._get_content_type(Path("test.jpg"))
            == HttpContentType.JPG.header
        )
        assert (
            self.handler._get_content_type(Path("test.jpeg"))
            == HttpContentType.JPEG.header
        )

        # Test unknown extension
        assert self.handler._get_content_type(Path("test.xyz")) == DEFAULT_HEADER

    @pytest.mark.parametrize(
        "test_case",
        [
            GetHandlerTestCase(
                name="Happy Path",
                url="http://localhost:8080/agent-info",
                method=HttpMethod.GET.value,
                expected_handler="_handle_get_agent_info",
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
            headers=f"{HttpContentType.JSON.header}{http_msg.headers}",
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
