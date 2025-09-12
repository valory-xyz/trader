# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the handlers for the skill of ChatAbciApp."""

import copy
import json
from enum import Enum
from http import HTTPStatus
from typing import Any, Callable, Dict, List, Optional, Union, cast
from urllib.parse import urlparse

from aea.configurations.data_types import PublicId
from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue

from packages.dvilela.connections.genai.connection import (
    PUBLIC_ID as GENAI_CONNECTION_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import AbstractResponseHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
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
from packages.valory.skills.chatui_abci.dialogues import HttpDialogue
from packages.valory.skills.chatui_abci.models import SharedState, TradingStrategyUI
from packages.valory.skills.chatui_abci.prompts import (
    CHATUI_PROMPT,
    FieldsThatCanBeRemoved,
    TradingStrategy,
    build_chatui_llm_response_schema,
)


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


ChatuiABCIHandler = BaseABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler


# Content type constants
class HttpContentType(Enum):
    """Enum for HTTP content types."""

    HTML = "text/html"
    JS = "application/javascript"
    JSON = "application/json"
    CSS = "text/css"
    PNG = "image/png"
    JPG = "image/jpeg"
    JPEG = "image/jpeg"

    @property
    def header(self) -> str:
        return f"Content-Type: {self.value}\n"


DEFAULT_HEADER = HttpContentType.HTML.header

HTTP_CONTENT_TYPE_MAP = {
    ".js": HttpContentType.JS.header,
    ".html": HttpContentType.HTML.header,
    ".json": HttpContentType.JSON.header,
    ".css": HttpContentType.CSS.header,
    ".png": HttpContentType.PNG.header,
    ".jpg": HttpContentType.JPG.header,
    ".jpeg": HttpContentType.JPEG.header,
}


# ChatUI constants
PROMPT_FIELD = "prompt"
RESPONSE_FIELD = "response"
MESSAGE_FIELD = "message"
UPDATED_CONFIG_FIELD = "updated_agent_config"
UPDATED_PARAMS_FIELD = "updated_params"
LLM_MESSAGE_FIELD = "reasoning"
TRADING_STRATEGY_FIELD = "trading_strategy"
MECH_TOOL_FIELD = "mech_tool"
REMOVED_CONFIG_FIELDS_FIELD = "removed_config_fields"
GENAI_API_KEY_NOT_SET_ERROR = "No API_KEY or ADC found."
GENAI_RATE_LIMIT_ERROR = "429"
TRADING_TYPE_FIELD = "trading_type"
PREVIOUS_TRADING_TYPE_FIELD = "previous_trading_type"

AVAILABLE_TRADING_STRATEGIES = frozenset(strategy.value for strategy in TradingStrategy)


class HttpHandler(BaseHttpHandler):
    """This implements the trader handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}

    def setup(self) -> None:
        """Setup the handler."""
        super().setup()
        config_uri_base_hostname = urlparse(
            self.context.params.service_endpoint
        ).hostname

        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        local_ip_regex = r"192\.168(\.\d{1,3}){2}"

        # Route regexes
        hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"

        chatui_prompt_url = rf"{hostname_regex}\/chatui-prompt"
        configure_strategies_url = rf"{hostname_regex}\/configure_strategies"
        is_enabled_url = rf"{hostname_regex}\/features"


        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value): [
                *(self.routes.get((HttpMethod.GET.value), [])),
                (is_enabled_url, self._handle_get_features),
            ],
            (HttpMethod.HEAD.value): [
                *(self.routes.get((HttpMethod.HEAD.value), [])), 
                (is_enabled_url, self._handle_get_features),
            ],
            (HttpMethod.POST.value,): [
                # not used yet
                (chatui_prompt_url, self._handle_chatui_prompt),
                # correct name according to fe spec
                (configure_strategies_url, self._handle_chatui_prompt),
            ],
        }

    def _handle_get_features(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a GET request to check if chat feature is enabled.

        :param http_msg: the HTTP message
        :param http_dialogue: the HTTP dialogue
        """
        api_key = self.context.params.genai_api_key

        is_chat_enabled = (
            api_key is not None
            and isinstance(api_key, str)
            and api_key.strip() != ""
            and api_key != "${str:}"
            and api_key != '""'
        )

        data = {"isChatEnabled": is_chat_enabled}
        self._send_ok_response(http_msg, http_dialogue, data)    

    @property
    def shared_state(self) -> SharedState:
        """Return the shared state."""
        return cast(SharedState, self.context.state)

    def _send_http_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        status_code: int,
        status_text: str,
        content_type: Optional[str] = None,
    ) -> None:
        """Generic method to send HTTP responses."""
        headers = content_type or (
            HttpContentType.JSON.header
            if isinstance(data, (dict, list))
            else DEFAULT_HEADER
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        try:
            http_response = http_dialogue.reply(
                performative=HttpMessage.Performative.RESPONSE,
                target_message=http_msg,
                version=http_msg.version,
                status_code=status_code,
                status_text=status_text,
                headers=headers,
                body=data.encode("utf-8") if isinstance(data, str) else data,
            )

            self.context.logger.info("Responding with: {}".format(http_response))
            self.context.outbox.put_message(message=http_response)
        except KeyError as e:
            self.context.logger.error(f"KeyError: {e}")
        except Exception as e:
            self.context.logger.error(f"Error: {e}")

    def _send_too_early_request_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP too early request response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.TOO_EARLY.value,
            HTTPStatus.TOO_EARLY.phrase,
            content_type,
        )

    def _send_too_many_requests_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP too many requests response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.TOO_MANY_REQUESTS.value,
            HTTPStatus.TOO_MANY_REQUESTS.phrase,
            content_type,
        )

    def _send_internal_server_error_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a Http internal server error response."""
        headers = content_type or (
            HttpContentType.JSON.header
            if isinstance(data, (dict, list))
            else DEFAULT_HEADER
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
            status_text=HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
            headers=headers,
            body=data.encode("utf-8") if isinstance(data, str) else data,
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_bad_request_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP bad request."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.BAD_REQUEST.value,
            HTTPStatus.BAD_REQUEST.phrase,
            content_type,
        )

    def _send_ok_request_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Send an OK response with the provided data."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.OK.value,
            "Success",
            content_type,
        )

    def _send_message(
        self,
        message: Message,
        dialogue: Dialogue,
        callback: Callable,
        callback_kwargs: Optional[Dict] = None,
    ) -> None:
        """
        Send a message and set up a callback for the response.

        :param message: the Message to send
        :param dialogue: the Dialogue context
        :param callback: the callback function upon response
        :param callback_kwargs: optional kwargs for the callback
        """
        self.context.outbox.put_message(message=message)
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        self.context.state.req_to_callback[nonce] = (callback, callback_kwargs or {})

    def _handle_chatui_prompt(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle POST requests to process user prompts.

        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        self.context.logger.info("Handling chatui prompt")
        # Parse incoming data
        data = json.loads(http_msg.body.decode("utf-8"))
        user_prompt = data.get(PROMPT_FIELD, "")

        if not user_prompt:
            self._send_bad_request_response(
                http_msg,
                http_dialogue,
                {"error": "User prompt is required."},
                content_type=HttpContentType.JSON.header,
            )
            return

        available_tools = self._get_available_tools(http_msg, http_dialogue)
        if available_tools is None:
            return
        current_trading_strategy = self.shared_state.chatui_config.trading_strategy
        current_mech_tool = (
            self.shared_state.chatui_config.mech_tool
            or "Automatic tool selection based on policy"
        )

        prompt = CHATUI_PROMPT.format(
            user_prompt=user_prompt,
            current_trading_strategy=current_trading_strategy,
            current_mech_tool=current_mech_tool,
            available_tools=available_tools,
        )
        self._send_chatui_llm_request(
            prompt=prompt,
            http_msg=http_msg,
            http_dialogue=http_dialogue,
        )

    def _send_chatui_llm_request(
        self, prompt: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        # Prepare payload data
        payload_data = {
            "prompt": prompt,
            "schema": build_chatui_llm_response_schema(),
        }

        self.context.logger.info(f"Payload data: {payload_data}")

        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)
        request_srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(GENAI_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(payload_data),
        )

        callback_kwargs = {"http_msg": http_msg, "http_dialogue": http_dialogue}
        self._send_message(
            request_srr_message,
            srr_dialogue,
            self._handle_chatui_llm_response,
            callback_kwargs,
        )

    def _get_available_tools(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> Optional[List[str]]:
        """Get available mech tools, handle errors if not available."""
        try:
            return self.synchronized_data.available_mech_tools
        except TypeError as e:
            self.context.logger.error(
                f"Error retrieving data: {e}. Mostly due to the skill not being started yet."
            )
            self._send_too_early_request_response(
                http_msg,
                http_dialogue,
                {
                    "error": "Skill not started yet or data not available. Please try again later."
                },
                content_type=HttpContentType.JSON.header,
            )
            return None

    def _get_ui_trading_strategy(self, selected_value: Optional[str]) -> TradingStrategyUI:
        """Get the UI trading strategy."""
        if selected_value is None:
            return TradingStrategyUI.BALANCED

        if selected_value == TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value:
            return TradingStrategyUI.BALANCED
        elif selected_value == TradingStrategy.KELLY_CRITERION_NO_CONF.value:
            return TradingStrategyUI.RISKY
        else:
            return TradingStrategyUI.RISKY

    def _handle_chatui_llm_response(
        self,
        llm_response_message: SrrMessage,
        dialogue: Dialogue,  # pylint: disable=unused-argument
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """
        Handle the response from the LLM.

        :param llm_response_message: the SrrMessage with the LLM output
        :param dialogue: the Dialogue
        :param http_msg: the original HttpMessage
        :param http_dialogue: the original HttpDialogue
        """
        self.context.logger.info(
            f"LLM response payload: {llm_response_message.payload}"
        )

        # Store the current trading strategy before any updates
        previous_trading_strategy = copy.deepcopy(self.shared_state.chatui_config.trading_strategy)

        genai_response: dict = json.loads(llm_response_message.payload)

        if "error" in genai_response:
            self._handle_chatui_llm_error(
                genai_response["error"], http_msg, http_dialogue
            )
            return

        llm_response = genai_response.get(RESPONSE_FIELD, "{}")
        llm_response_json = json.loads(llm_response)

        llm_message = llm_response_json.get(MESSAGE_FIELD, "")
        updated_agent_config = llm_response_json.get(UPDATED_CONFIG_FIELD, {})

        if not updated_agent_config:
            self.context.logger.warning(
                "No agent configuration update provided by the LLM."
            )
            self._send_ok_request_response(
                http_msg,
                http_dialogue,
                {
                    UPDATED_PARAMS_FIELD: {},
                    LLM_MESSAGE_FIELD: llm_message,
                },
            )
            return

        updated_params, issues = self._process_updated_agent_config(
            updated_agent_config
        )
        selected_trading_strategy = updated_params.get(
            TRADING_STRATEGY_FIELD, previous_trading_strategy
        )

        selected_ui_strategy = self._get_ui_trading_strategy(
            selected_trading_strategy
        ).value
        previous_ui_strategy = self._get_ui_trading_strategy(
            previous_trading_strategy
        ).value

        response_body = {
            TRADING_TYPE_FIELD: selected_ui_strategy,
            LLM_MESSAGE_FIELD: "\n".join(issues) if issues else llm_message,
        }
        if selected_trading_strategy != previous_trading_strategy:
            # In case of update, reflect the previous value in the response. Needed for frontend
            response_body[PREVIOUS_TRADING_TYPE_FIELD] = previous_ui_strategy

        self._send_ok_request_response(
            http_msg,
            http_dialogue,
            response_body,
        )

    def _process_updated_agent_config(self, updated_agent_config: dict) -> tuple:
        """
        Process the updated agent config from the LLM response.

        :param updated_agent_config: dict containing updated config
        :return: tuple of (updated_params, issues)
        """
        updated_params: Dict = {}
        issues: List[str] = []

        updated_trading_strategy: Optional[str] = updated_agent_config.get(
            TRADING_STRATEGY_FIELD, None
        )
        if updated_trading_strategy:
            if updated_trading_strategy in AVAILABLE_TRADING_STRATEGIES:
                updated_params.update({"trading_strategy": updated_trading_strategy})
                self._store_trading_strategy(updated_trading_strategy)
            else:
                issue_message = f"Unsupported trading strategy: {updated_trading_strategy!r}. Available strategies are: {', '.join(AVAILABLE_TRADING_STRATEGIES)}."
                self.context.logger.warning(issue_message)
                issues.append(issue_message)

        updated_mech_tool: Optional[str] = updated_agent_config.get(
            MECH_TOOL_FIELD, None
        )
        mech_tool_is_removed: bool = (
            FieldsThatCanBeRemoved.MECH_TOOL.value
            in updated_agent_config.get(REMOVED_CONFIG_FIELDS_FIELD, [])
        )

        if mech_tool_is_removed:
            updated_params.update({MECH_TOOL_FIELD: None})
            self._store_selected_tool(None)

        elif updated_mech_tool:
            if updated_mech_tool in self.synchronized_data.available_mech_tools:
                updated_params.update({MECH_TOOL_FIELD: updated_mech_tool})
                self._store_selected_tool(updated_mech_tool)
            else:
                issue_message = f"Unsupported mech tool: {updated_mech_tool!r}. Available tools are: {', '.join(self.synchronized_data.available_mech_tools)}."
                self.context.logger.warning(issue_message)
                issues.append(issue_message)

        return updated_params, issues

    def _handle_chatui_llm_error(
        self, error_message: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        self.context.logger.error(f"LLM error response: {error_message}")
        if GENAI_API_KEY_NOT_SET_ERROR in error_message:
            self._send_internal_server_error_response(
                http_msg,
                http_dialogue,
                {"error": "No GENAI_API_KEY set."},
                content_type=HttpContentType.JSON.header,
            )
            return
        if GENAI_RATE_LIMIT_ERROR in error_message:
            self._send_too_many_requests_response(
                http_msg,
                http_dialogue,
                {"error": "Too many requests to the LLM."},
                content_type=HttpContentType.JSON.header,
            )
            return
        self._send_internal_server_error_response(
            http_msg,
            http_dialogue,
            {"error": "An error occurred while processing the request."},
            content_type=HttpContentType.JSON.header,
        )

    def _store_chatui_param_to_json(self, param_name: str, value: Any) -> None:
        """Store chatui param to json."""

        current_store: dict = self.shared_state._get_current_json_store()
        current_store.update({param_name: value})
        self.shared_state._set_json_store(current_store)

    def _store_trading_strategy(self, trading_strategy: str) -> None:
        """Store the trading strategy."""
        self.shared_state.chatui_config.trading_strategy = trading_strategy
        self._store_chatui_param_to_json(TRADING_STRATEGY_FIELD, trading_strategy)

    def _store_selected_tool(self, selected_tool: Optional[str] = None) -> None:
        """Store the selected tool."""
        self.shared_state.chatui_config.mech_tool = selected_tool
        self._store_chatui_param_to_json(MECH_TOOL_FIELD, selected_tool)


class SrrHandler(AbstractResponseHandler):
    """A class for handling SRR messages."""

    SUPPORTED_PROTOCOL: Optional[PublicId] = SrrMessage.protocol_id
    allowed_response_performatives = frozenset(
        {
            SrrMessage.Performative.REQUEST,
            SrrMessage.Performative.RESPONSE,
        }
    )

    def handle(self, message: Message) -> None:
        """
        React to an SRR message.

        :param message: the SrrMessage instance
        """
        self.context.logger.info(f"Received Srr message: {message}")
        srr_msg = cast(SrrMessage, message)

        if srr_msg.performative not in self.allowed_response_performatives:
            self.context.logger.warning(
                f"SRR performative not recognized: {srr_msg.performative}"
            )
            return

        nonce = srr_msg.dialogue_reference[
            0
        ]  # Assuming dialogue_reference is accessible
        callback, kwargs = self.context.state.req_to_callback.pop(nonce, (None, {}))

        if callback is None:
            super().handle(message)
            return

        dialogue = self.context.srr_dialogues.update(srr_msg)
        callback(srr_msg, dialogue, **kwargs)
