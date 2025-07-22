# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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


"""This module contains the handlers for the 'trader_abci' skill."""

import json
from http import HTTPStatus
from pathlib import Path
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
    ABCIRoundHandler,
    AbstractResponseHandler,
)
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
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import HttpMethod
from packages.valory.skills.decision_maker_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.mech_interact_abci.handlers import (
    AcnHandler as BaseAcnHandler,
)
from packages.valory.skills.staking_abci.rounds import SynchronizedData
from packages.valory.skills.trader_abci.dialogues import HttpDialogue
from packages.valory.skills.trader_abci.prompts import (
    AUTOMATIC_SELECTION_VALUE,
    CHATUI_PROMPT,
    TradingStrategy,
    build_chatui_llm_response_schema,
)


TraderHandler = ABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler
AcnHandler = BaseAcnHandler


PREDICT_AGENT_PROFILE_PATH = "predict-ui-build"
CHATUI_PARAM_STORE = "chatui_param_store.json"

# Content type constants
DEFAULT_HEADER = HTML_HEADER = "Content-Type: text/html\n"
CONTENT_TYPES = {
    ".js": "Content-Type: application/javascript\n",
    ".html": HTML_HEADER,
    ".json": "Content-Type: application/json\n",
    ".css": "Content-Type: text/css\n",
    ".png": "Content-Type: image/png\n",
    ".jpg": "Content-Type: image/jpeg\n",
    ".jpeg": "Content-Type: image/jpeg\n",
}


# ChatUI constants
CHATUI_PROMPT_FIELD = "prompt"
CHATUI_RESPONSE_FIELD = "response"
CHATUI_MESSAGE_FIELD = "message"
CHATUI_UPDATED_CONFIG_FIELD = "updated_agent_config"
CHATUI_UPDATED_PARAMS_FIELD = "updated_params"
CHATUI_LLM_MESSAGE_FIELD = "llm_message"
CHATUI_TRADING_STRATEGY_FIELD = "trading_strategy"
CHATUI_RESPONSE_ISSUES_FIELD = "issues"
CHATUI_MECH_TOOL_FIELD = "mech_tool"

AVAILABLE_TRADING_STRATEGIES = frozenset(strategy.value for strategy in TradingStrategy)


class HttpHandler(BaseHttpHandler):
    """This implements the trader handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}

    @property
    def staking_synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

    @property
    def agent_ids(self) -> List[int]:
        """Get the agent ids."""
        return json.loads(self.staking_synchronized_data.agent_ids)

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
        self.handler_url_regex = rf"{hostname_regex}\/.*"

        agent_info_url_regex = rf"{hostname_regex}\/agent-info"

        chatui_prompt_url = rf"{hostname_regex}\/chatui-prompt"

        static_files_regex = (
            rf"{hostname_regex}\/(.*)"  # New regex for serving static files
        )

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.POST.value,): [
                (chatui_prompt_url, self._handle_chatui_prompt),
            ],
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                *(self.routes[(HttpMethod.GET.value, HttpMethod.HEAD.value)] or []),
                (agent_info_url_regex, self._handle_get_agent_info),
                (
                    static_files_regex,
                    self._handle_get_static_file,
                ),
            ],
        }

        self.agent_profile_path = PREDICT_AGENT_PROFILE_PATH

    def _get_content_type(self, file_path: Path) -> str:
        """Get the appropriate content type header based on file extension."""
        return CONTENT_TYPES.get(file_path.suffix.lower(), DEFAULT_HEADER)

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
            CONTENT_TYPES[".json"] if isinstance(data, (dict, list)) else DEFAULT_HEADER
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

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
            CONTENT_TYPES[".json"] if isinstance(data, (dict, list)) else DEFAULT_HEADER
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

    def _send_ok_response(
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
        user_prompt = data.get(CHATUI_PROMPT_FIELD, "")

        if not user_prompt:
            self._send_bad_request_response(
                http_msg,
                http_dialogue,
                {"error": "User prompt is required."},
                content_type=CONTENT_TYPES[".json"],
            )
            return

        available_tools = self._get_available_tools(http_msg, http_dialogue)
        if available_tools is None:
            return
        current_trading_strategy = self.context.state.chat_ui_params.trading_strategy

        prompt = CHATUI_PROMPT.format(
            user_prompt=user_prompt,
            current_trading_strategy=current_trading_strategy,
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
                content_type=CONTENT_TYPES[".json"],
            )
            return None

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

        genai_response: dict = json.loads(llm_response_message.payload)

        if "error" in genai_response:
            self._handle_chatui_llm_error(
                genai_response["error"], http_msg, http_dialogue
            )
            return

        llm_response = genai_response.get(CHATUI_RESPONSE_FIELD, "{}")
        llm_response_json = json.loads(llm_response)

        llm_message = llm_response_json.get(CHATUI_MESSAGE_FIELD, "")
        updated_agent_config = llm_response_json.get(CHATUI_UPDATED_CONFIG_FIELD, {})

        if not updated_agent_config:
            self.context.logger.warning(
                "No agent configuration update provided by the LLM."
            )
            self._send_ok_response(
                http_msg,
                http_dialogue,
                {
                    CHATUI_UPDATED_PARAMS_FIELD: {},
                    CHATUI_LLM_MESSAGE_FIELD: llm_message,
                },
            )
            return

        updated_params, issues = self._process_updated_agent_config(
            updated_agent_config
        )

        self._send_ok_response(
            http_msg,
            http_dialogue,
            {
                CHATUI_UPDATED_PARAMS_FIELD: updated_params,
                CHATUI_LLM_MESSAGE_FIELD: llm_message,
                CHATUI_RESPONSE_ISSUES_FIELD: issues,
            },
        )

    def _process_updated_agent_config(self, updated_agent_config: dict) -> tuple:
        """
        Process the updated agent config from the LLM response.

        :param updated_agent_config: dict containing updated config
        :return: tuple of (updated_params, issues)
        """
        updated_params = {}
        issues: List[str] = []

        updated_trading_strategy: Optional[str] = updated_agent_config.get(
            CHATUI_TRADING_STRATEGY_FIELD, None
        )
        if updated_trading_strategy:
            if updated_trading_strategy in AVAILABLE_TRADING_STRATEGIES:
                updated_params.update({"trading_strategy": updated_trading_strategy})
                self._store_trading_strategy(updated_trading_strategy)
            else:
                issue_message = (
                    f"Unsupported trading strategy: {updated_trading_strategy}. "
                )
                self.context.logger.error(issue_message)
                issues.append(issue_message)

        updated_mech_tool: Optional[str] = updated_agent_config.get(
            CHATUI_MECH_TOOL_FIELD, None
        )
        if updated_mech_tool:
            if updated_mech_tool == AUTOMATIC_SELECTION_VALUE:
                updated_params.update({CHATUI_MECH_TOOL_FIELD: updated_mech_tool})
                self._store_selected_tool(None)
            elif updated_mech_tool in self.synchronized_data.available_mech_tools:
                updated_params.update({CHATUI_MECH_TOOL_FIELD: updated_mech_tool})
                self._store_selected_tool(updated_mech_tool)
            else:
                self.context.logger.error(f"Unsupported mech tool: {updated_mech_tool}")
                issues.append(f"Unsupported mech tool: {updated_mech_tool}")

        return updated_params, issues

    def _handle_chatui_llm_error(
        self, error_message: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        self.context.logger.error(f"LLM error response: {error_message}")
        if "No API_KEY or ADC found." in error_message:
            self._send_internal_server_error_response(
                http_msg,
                http_dialogue,
                {"error": "No GENAI_API_KEY set."},
                content_type=CONTENT_TYPES[".json"],
            )
            return
        if "429" in error_message:
            self._send_too_many_requests_response(
                http_msg,
                http_dialogue,
                {"error": "Too many requests to the LLM."},
                content_type=CONTENT_TYPES[".json"],
            )
            return
        self._send_internal_server_error_response(
            http_msg,
            http_dialogue,
            {"error": "An error occurred while processing the request."},
            content_type=CONTENT_TYPES[".json"],
        )

    def _store_chatui_param_to_json(self, param_name: str, value: Any) -> None:
        """Store chatui param to json."""

        current_store: dict = self.context.state._get_current_json_store()

        current_store.update({param_name: value})

        self.context.state._set_json_store(current_store)

    def _store_trading_strategy(self, trading_strategy: str) -> None:
        """Store the trading strategy."""
        self.context.state.chat_ui_params.trading_strategy = trading_strategy
        self._store_chatui_param_to_json(
            CHATUI_TRADING_STRATEGY_FIELD, trading_strategy
        )

    def _store_selected_tool(self, selected_tool: Optional[str] = None) -> None:
        """Store the selected tool."""
        self.context.state.chat_ui_params.mech_tool = selected_tool
        self._store_chatui_param_to_json(CHATUI_MECH_TOOL_FIELD, selected_tool)

    def _handle_get_agent_info(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle a Http request of verb GET."""
        data = {
            "address": self.context.agent_address,
            "safe_address": self.synchronized_data.safe_contract_address,
            "agent_ids": self.agent_ids,
            "service_id": self.staking_synchronized_data.service_id,
        }
        self.context.logger.info(f"Sending agent info: {data=}")
        self._send_ok_response(http_msg, http_dialogue, data)

    def _handle_get_static_file(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a HTTP GET request for a static file.

        Implementation borrowed from:
        https://github.com/valory-xyz/optimus/blob/262f14843f171942995acfae8bea85d76fa82926/packages/valory/skills/optimus_abci/handlers.py#L349-L385

        :param http_msg: the HTTP message
        :param http_dialogue: the HTTP dialogue
        """
        try:
            # Extract the requested path from the URL
            requested_path = urlparse(http_msg.url).path.lstrip("/")

            # Construct the file path
            file_path = Path(
                Path(__file__).parent, self.agent_profile_path, requested_path
            )
            # If the file exists and is a file, send it as a response
            if file_path.exists() and file_path.is_file():
                with open(file_path, "rb") as file:
                    file_content = file.read()

                # Get the appropriate content type
                content_type = self._get_content_type(file_path)

                # Send the file content as a response
                self._send_ok_response(
                    http_msg, http_dialogue, file_content, content_type
                )
            else:
                # If the file doesn't exist or is not a file, return the index.html file
                with open(
                    Path(Path(__file__).parent, self.agent_profile_path, "index.html"),
                    "r",
                    encoding="utf-8",
                ) as file:
                    index_html = file.read()

                # Send the HTML response
                self._send_ok_response(http_msg, http_dialogue, index_html)
        except FileNotFoundError:
            self._handle_not_found(http_msg, http_dialogue)


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
