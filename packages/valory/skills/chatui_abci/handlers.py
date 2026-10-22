# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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
import math
import re
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial
from html import escape
from http import HTTPStatus
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)

from aea.configurations.data_types import PublicId
from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue

from packages.valory.connections.genai.connection import (
    PUBLIC_ID as GENAI_CONNECTION_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.base import RoundSequence
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    AbstractResponseHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
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
from packages.valory.skills.agent_performance_summary_abci.activity_goal import (
    effective_activity_goal,
    is_valid_activity_goal,
    retarget_activity_goal,
)
from packages.valory.skills.agent_performance_summary_abci.feed import (
    EventType,
    FeedEntry,
    KIND_EVENT,
    ROLE_AGENT,
    ROLE_USER,
    append_message,
    field,
    find_exchange,
    format_amount,
    read_recent,
    record_event,
)
from packages.valory.skills.agent_performance_summary_abci.handlers import (
    HttpContentType,
)
from packages.valory.skills.agent_performance_summary_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.agent_performance_summary_abci.handlers import (
    HttpMethod,
)
from packages.valory.skills.chatui_abci.dialogues import HttpDialogue
from packages.valory.skills.chatui_abci.mech_commands import (
    Accept,
    addresses_in,
    normalise,
    parse_accept,
    parse_remove,
    parse_undo,
    resolve_intent,
)
from packages.valory.skills.chatui_abci.mech_templates import (
    PARAGRAPH_BREAK,
    Standing,
    payment_line,
    render_report,
    verdict,
)
from packages.valory.skills.chatui_abci.models import (
    ACTIVITY_GOAL_FIELD,
    ChatTurn,
    ConfigChange,
    ConfigProposal,
    Offer,
    RemovedMech,
    SharedState,
    TradingStrategyUI,
    WITHDRAWAL_STATE_ARMED,
    WITHDRAWAL_STATE_IDLE,
)
from packages.valory.skills.chatui_abci.prompts import (
    CHATUI_PROMPT,
    CHAT_PROMPT,
    CONFIRM_PROMPT,
    FieldsThatCanBeRemoved,
    MechIntent,
    TradingStrategy,
    build_chatui_llm_response_schema,
    build_confirmation_schema,
)
from packages.valory.skills.chatui_abci.rounds import SynchronizedData
from packages.valory.skills.chatui_abci.tool_keys import (
    VALORY_LABEL,
    split_tool_key,
    tool_names,
)
from packages.valory.skills.mech_interact_abci.mech_reader import (
    MechFacts,
    RecordStatus,
    chain_id_of,
    read_live_rate,
    read_mech,
)
from packages.valory.skills.mech_interact_abci.models import delivery_rate_bound


def _tools_for_prompt(tools: Any, valory_tools: Set[str]) -> str:
    """The tool names a Valory mech serves, with a count of the others, which are not listed."""
    shown = sorted(str(tool) for tool in tools if tool in valory_tools)
    hidden = sum(1 for tool in tools if tool not in valory_tools)
    text = ", ".join(shown) or "none"
    if hidden:
        text += f" (and {hidden} other tool(s), not listed)"
    return text


def _typed_names(text: str) -> Set[str]:
    """The words of a message, split on spaces and punctuation that a tool name does not use."""
    return {word.strip(".") for word in TYPED_NAME_SEPARATORS.split(text)}


def _list_number(
    reading: Any, address: Optional[str], last_list: Sequence[str]
) -> Optional[int]:
    """The list number a resolved mech came from; `resolve_intent` already matched it to the mech."""
    if not isinstance(reading, dict) or address is None or not last_list:
        return None
    position = reading.get("position")
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        return None
    return position


ChatuiABCIHandler = BaseABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler


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
ALLOWED_TOOLS_FIELD = "allowed_tools"
TYPED_NAME_SEPARATORS = re.compile(r"[\s,;:!?\"'`()\[\]{}]+")
SELECTED_MECHS_FIELD = "selected_mechs"
REMOVED_CONFIG_FIELDS_FIELD = "removed_config_fields"
MECH_INTENT_FIELD = "mech_intent"
GENAI_API_KEY_NOT_SET_ERROR = "No API_KEY or ADC found."
GENAI_RATE_LIMIT_ERROR = "429"
MECH_DEPOSIT_REQUIRED_CODE = "mech_deposit_required"
# Set by trader_abci's funding check.
MECH_PRE_DEPOSIT_EOA_SHORT = "mech_pre_deposit_eoa_short"
TRADING_TYPE_FIELD = "trading_type"
PREVIOUS_TRADING_TYPE_FIELD = "previous_trading_type"

ASK_ONE_AT_A_TIME = "Ask about one mech at a time."
ONE_REQUEST_AT_A_TIME = (
    "I can either act on a mech or change your settings in one message, so I "
    "did neither. Please ask for them separately."
)
ACCEPT_UNREADABLE = (
    "I couldn't read that. To approve a mech, copy the line from its report "
    "exactly: I accept <price> per request for <address>"
)
WHICH_MECH = (
    "I couldn't tell which mech you mean. If you meant something else, ask again "
    "in other words."
)
VALORY_NOT_REMOVABLE = (
    "{address} is a Valory mech your agent uses by default, so there is no "
    "approval to remove. To keep requests off it, pin the mechs you want; mech "
    "requests then go only to your pinned mechs."
)
NEXT_STEP = (
    "Send a mech's address to see its report, or ask which mechs your agent can use."
)

AVAILABLE_TRADING_STRATEGIES = frozenset(strategy.value for strategy in TradingStrategy)
# The settings a config reply can set, compared with the current config.
_SETTINGS = (
    TRADING_STRATEGY_FIELD,
    ALLOWED_TOOLS_FIELD,
    SELECTED_MECHS_FIELD,
    "fixed_bet_size",
    "max_bet_size",
    ACTIVITY_GOAL_FIELD,
)

CHAT_TEXT_FIELD = "text"
CHAT_CLIENT_ID_FIELD = "client_id"
CHAT_MESSAGE_FIELD = "message"
CHAT_REPLY_FIELD = "reply"
INVALID_CHAT_REQUEST = "A chat message needs a non-empty text and client_id."
CHAT_SAVE_FAILED = "The message could not be saved. Please try again."
STILL_ANSWERING = "Your agent is still answering this message."
CHANGE_NOT_APPLIED = (
    "I couldn't apply that change, so your settings are unchanged. Please try again."
)
CHANGE_REFUSED = "Nothing was changed."
RECENT_FEED_ENTRIES = 20
# Keeps a long earlier reply or market title from crowding the prompt.
RECENT_TEXT_LIMIT = 300
FEED_TIME_FORMAT = "%Y-%m-%d %H:%M UTC"
CHAT_STATUS_OVERRIDES = {HTTPStatus.TOO_EARLY: HTTPStatus.SERVICE_UNAVAILABLE}

SETTING_LABELS = {
    TRADING_STRATEGY_FIELD: "Trading strategy",
    ALLOWED_TOOLS_FIELD: "Allowed tools",
    SELECTED_MECHS_FIELD: "Pinned mechs",
    "fixed_bet_size": "Fixed trade size",
    "max_bet_size": "Max trade size",
    ACTIVITY_GOAL_FIELD: "Daily activity target",
}
ALL_TOOLS = "All tools"
ALL_MECHS = "All mechs"
DEFAULT_VALUE = "Default"
AMOUNT_SETTINGS = ("fixed_bet_size", "max_bet_size")
# Enough to tell apart the trade sizes the bounds allow, without showing float noise.
SETTING_AMOUNT_DECIMALS = 6


# What parsing a model reply can raise. ``JSONDecodeError`` is a ``ValueError``
# but not the only one: an integer literal over the digit limit raises a plain
# ``ValueError``, and about a thousand nested brackets raises ``RecursionError``,
# which does not derive from either.
_UNPARSEABLE_REPLY = (ValueError, TypeError, RecursionError)


class HttpHandler(BaseHttpHandler):
    """This implements the trader handler."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        # The chat requests being answered, by HTTP dialogue.
        self._chat_turns: Dict[Any, ChatTurn] = {}

    def setup(self) -> None:
        """Setup the handler."""
        super().setup()

        # Use hostname_regex from parent's setup
        chatui_prompt_url = rf"{self.hostname_regex}\/chatui-prompt"
        configure_strategies_url = rf"{self.hostname_regex}\/configure_strategies"
        is_enabled_url = rf"{self.hostname_regex}\/features"
        withdrawal_url = rf"{self.hostname_regex}\/api\/v1\/withdrawal"
        chat_url = rf"{self.hostname_regex}\/api\/v1\/chat$"

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value,): [
                *(self.routes.get((HttpMethod.GET.value,), [])),
                (is_enabled_url, self._handle_get_features),
                (withdrawal_url, self._handle_get_withdrawal),
            ],
            (HttpMethod.HEAD.value,): [
                *(self.routes.get((HttpMethod.HEAD.value,), [])),
                (is_enabled_url, self._handle_get_features),
            ],
            (HttpMethod.POST.value,): [
                # not used yet
                (chatui_prompt_url, self._handle_chatui_prompt),
                # correct name according to fe spec
                (configure_strategies_url, self._handle_chatui_prompt),
                (withdrawal_url, self._handle_post_withdrawal),
                (chat_url, self._handle_chat),
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
        # Check if using X402 or if GENAI_API_KEY is set
        use_x402 = getattr(self.context.params, "use_x402", False)

        if use_x402:
            # If using X402, chat is enabled without API key check
            is_chat_enabled = True
        else:
            # Otherwise, check if GENAI_API_KEY is set
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

    @property
    def round_sequence(self) -> RoundSequence:
        """Return the round sequence."""
        return self.shared_state.round_sequence

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(db=self.round_sequence.latest_synchronized_data.db)

    def get_units_and_decimals(self) -> tuple:
        """Get the units and decimals based on the environment."""
        is_polymarket = self.context.params.is_running_on_polymarket
        units = "USDC" if is_polymarket else "wxDAI"
        decimals = 6 if is_polymarket else 18
        return units, decimals

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
        try:
            data = json.loads(http_msg.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.context.logger.error(f"Invalid request body: {e}")
            self._send_bad_request_response(
                http_msg,
                http_dialogue,
                {"error": "Invalid JSON in request body."},
                content_type=HttpContentType.JSON.header,
            )
            return
        user_prompt = data.get(PROMPT_FIELD, "")

        if not user_prompt:
            self._send_bad_request_response(
                http_msg,
                http_dialogue,
                {"error": "User prompt is required."},
                content_type=HttpContentType.JSON.header,
            )
            return

        self._answer_prompt(user_prompt, http_msg, http_dialogue)

    def _answer_prompt(
        self, user_prompt: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Answer a user message: a mech command or report, else the model.

        :param user_prompt: the user's message.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        # "The mech just shown" and the list's numbers mean the reply right before this message.
        last_shown = self.shared_state.last_shown_mech
        self.shared_state.last_shown_mech = None
        last_list = list(self.shared_state.last_mech_list)
        self.shared_state.last_mech_list = []
        last_removed = self.shared_state.last_removed
        self.shared_state.last_removed = None
        accept = parse_accept(user_prompt)
        if accept is not None:
            self._accept_offer(accept, http_msg, http_dialogue)
            return
        removed = parse_remove(user_prompt)
        if removed is not None:
            self._send_mech_reply(http_msg, http_dialogue, self._remove_mech(removed))
            return
        if parse_undo(user_prompt):
            undone = None if last_removed is None else last_removed.address
            self._send_mech_reply(
                http_msg, http_dialogue, self._undo_removal(last_removed, undone)
            )
            return
        # A typed price is consent to that price, so a line that does not
        # parse is never read as an approval at the price shown.
        if normalise(user_prompt).startswith("i accept"):
            self._send_mech_reply(http_msg, http_dialogue, ACCEPT_UNREADABLE)
            return
        if len(addresses_in(user_prompt)) > 1:
            self._send_mech_reply(http_msg, http_dialogue, ASK_ONE_AT_A_TIME)
            return

        tools = self._get_available_tools(http_msg, http_dialogue)
        if tools is None:
            # Nothing was answered, so a retry still refers to the reply before.
            self.shared_state.last_shown_mech = last_shown
            self.shared_state.last_mech_list = last_list
            self.shared_state.last_removed = last_removed
            return
        available_tools, valory_tools = tools
        self._send_chatui_prompt(
            user_prompt,
            available_tools,
            valory_tools,
            http_msg,
            http_dialogue,
            last_shown,
            last_list,
            last_removed,
        )

    def _run_mech_intent(
        self,
        intent: MechIntent,
        address: Optional[str],
        last_shown: Optional[str],
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        number: Optional[int] = None,
        last_removed: Optional[RemovedMech] = None,
    ) -> None:
        """Carry out a mech intent in code; without the mech it needs, ask which one."""
        self.context.logger.info(f"Mech intent: {intent.value}, mech: {address}")
        if intent is MechIntent.UNDO:
            self._send_mech_reply(
                http_msg, http_dialogue, self._undo_removal(last_removed, address)
            )
        elif intent is MechIntent.LIST:
            self._send_mech_reply(http_msg, http_dialogue, self._mech_list())
        elif address is None:
            self._send_mech_reply(http_msg, http_dialogue, self._which_mech())
        elif intent is MechIntent.ASK:
            self._report_mech(address, http_msg, http_dialogue)
        elif intent is MechIntent.APPROVE:
            self._approve_mech(address, last_shown, http_msg, http_dialogue)
        else:
            act = {
                MechIntent.REMOVE: self._remove_mech,
                MechIntent.PIN: self._pin_mech,
                MechIntent.UNPIN: self._unpin_mech,
            }[intent]
            reply = act(address)
            if number is not None:
                reply = f"Number {number} on the list just shown is {address}. {reply}"
            self._send_mech_reply(http_msg, http_dialogue, reply)

    def _report_mech(
        self, address: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Read the mech and answer with its report."""
        read_mech(
            self.context,
            address,
            partial(self._price_at_live_rate, http_msg, http_dialogue),
        )

    def _handle_chat(self, http_msg: HttpMessage, http_dialogue: HttpDialogue) -> None:
        """Answer a chat message, writing it and its reply to the feed.

        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        request = self._read_chat_request(http_msg)
        if request is None:
            self._send_bad_request_response(
                http_msg, http_dialogue, {"error": INVALID_CHAT_REQUEST}
            )
            return
        text, client_id = request
        if self.shared_state.is_answering(client_id):
            self._send_http_response(
                http_msg,
                http_dialogue,
                {"error": STILL_ANSWERING},
                HTTPStatus.CONFLICT.value,
                HTTPStatus.CONFLICT.phrase,
            )
            return

        store_path = self.context.params.store_path
        try:
            message, reply = find_exchange(store_path, client_id)
            if message is not None and reply is not None:
                self._send_ok_response(
                    http_msg,
                    http_dialogue,
                    {CHAT_MESSAGE_FIELD: message, CHAT_REPLY_FIELD: reply},
                )
                return
            if message is None:
                message = append_message(store_path, ROLE_USER, text, client_id)
        except OSError as e:
            self.context.logger.error(f"Could not write the chat message: {e}")
            self._send_internal_server_error_response(
                http_msg, http_dialogue, {"error": CHAT_SAVE_FAILED}
            )
            return

        unsaved_reply = self.shared_state.unsaved_replies.pop(client_id, None)
        turn = ChatTurn(client_id, message, applied_change=unsaved_reply is not None)
        self.shared_state.start_answering(turn)
        self._chat_turns[http_dialogue.dialogue_label] = turn
        if unsaved_reply is not None:
            self._send_chat_text(unsaved_reply, http_msg, http_dialogue)
            return
        proposal = self.shared_state.take_config_proposal()
        if proposal is not None:
            self._check_confirmation(proposal, text, http_msg, http_dialogue)
            return
        self._answer_prompt(text, http_msg, http_dialogue)

    @staticmethod
    def _read_chat_request(http_msg: HttpMessage) -> Optional[Tuple[str, str]]:
        """Return the message's text and client id, or ``None`` if the body lacks either.

        :param http_msg: the HttpMessage instance
        :return: the text and the client id.
        """
        try:
            data = json.loads(http_msg.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        text = data.get(CHAT_TEXT_FIELD)
        client_id = data.get(CHAT_CLIENT_ID_FIELD)
        if not isinstance(text, str) or not text.strip():
            return None
        if not isinstance(client_id, str) or not client_id:
            return None
        return text, client_id

    def _chat_turn(self, http_dialogue: HttpDialogue) -> Optional[ChatTurn]:
        """Return the chat message this request answers, if it is a chat request."""
        return self._chat_turns.get(http_dialogue.dialogue_label)

    def _send_http_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Any,
        status_code: int,
        status_text: str,
        content_type: Optional[str] = None,
    ) -> None:
        """Send a response; a chat request's answer is turned into the chat's reply.

        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        :param data: the response body
        :param status_code: the HTTP status
        :param status_text: the HTTP status text
        :param content_type: the content type header
        """
        turn = self._chat_turns.pop(http_dialogue.dialogue_label, None)
        if turn is None:
            super()._send_http_response(
                http_msg, http_dialogue, data, status_code, status_text, content_type
            )
            return
        self._end_chat_turn(turn, http_msg, http_dialogue, status_code, data)

    def _send_internal_server_error_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Any,
        content_type: Optional[str] = None,
    ) -> None:
        """Send a 500 response; through the chat's reply for a chat request.

        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        :param data: the response body
        :param content_type: the content type header
        """
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.INTERNAL_SERVER_ERROR.value,
            HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
            content_type,
        )

    def _end_chat_turn(
        self,
        turn: ChatTurn,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        status_code: int,
        data: Any,
    ) -> None:
        """Answer a chat request: the written lines on success, else the error.

        :param turn: the chat message being answered.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        :param status_code: the status the shared prompt path answered with.
        :param data: the body the shared prompt path answered with.
        """
        self.shared_state.finish_answering(turn)
        body = data if isinstance(data, dict) else {}
        if status_code == HTTPStatus.OK:
            store_path = self.context.params.store_path
            reply_text = str(body.get(LLM_MESSAGE_FIELD, ""))
            try:
                # A resend let through by the answering timeout can finish second.
                _, reply = find_exchange(store_path, turn.client_id)
                if reply is None:
                    reply = append_message(
                        store_path, ROLE_AGENT, reply_text, turn.client_id
                    )
                    if turn.proposal is not None:
                        self.shared_state.config_proposal = turn.proposal
            except OSError as e:
                self.context.logger.error(f"Could not write the chat reply: {e}")
                if turn.applied_change:
                    # The settings changed already, so the resend must not lose that.
                    self.shared_state.unsaved_replies[turn.client_id] = reply_text
                status_code = HTTPStatus.INTERNAL_SERVER_ERROR
                body = {"error": CHAT_SAVE_FAILED}
            else:
                super()._send_http_response(
                    http_msg,
                    http_dialogue,
                    {CHAT_MESSAGE_FIELD: turn.message, CHAT_REPLY_FIELD: reply},
                    HTTPStatus.OK.value,
                    HTTPStatus.OK.phrase,
                )
                return
        status = HTTPStatus(status_code)
        # The chat asks for funds only when the user must add them.
        if status == HTTPStatus.PAYMENT_REQUIRED and not self.context.shared_state.get(
            MECH_PRE_DEPOSIT_EOA_SHORT, False
        ):
            status = HTTPStatus.SERVICE_UNAVAILABLE
        status = CHAT_STATUS_OVERRIDES.get(status, status)
        super()._send_http_response(
            http_msg,
            http_dialogue,
            {"error": body.get("error") or status.phrase},
            status.value,
            status.phrase,
        )

    def _recent_activity(self, turn: ChatTurn) -> str:
        """Describe the latest feed entries for the chat prompt, oldest first.

        :param turn: the chat message being answered, left out as the prompt quotes it.
        :return: one line per entry.
        """
        try:
            entries = read_recent(
                self.context.params.store_path, RECENT_FEED_ENTRIES + 1
            )
        except OSError as e:
            self.context.logger.error(f"Could not read the feed for the chat: {e}")
            return "(not available)"
        lines = [
            self._describe_feed_entry(entry)
            for entry in entries
            if entry.get("id") != turn.message.get("id")
        ][-RECENT_FEED_ENTRIES:]
        return "\n".join(lines) if lines else "(no activity yet)"

    @staticmethod
    def _describe_feed_entry(entry: FeedEntry) -> str:
        """Describe one feed entry on one line.

        :param entry: the entry.
        :return: the line.
        """
        try:
            when = datetime.fromtimestamp(int(entry["ts"]), tz=timezone.utc).strftime(
                FEED_TIME_FORMAT
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            when = "unknown time"
        if entry.get("kind") == KIND_EVENT:
            fields = entry.get("fields")
            details = "; ".join(
                f"{item.get('label')}: {str(item.get('value'))[:RECENT_TEXT_LIMIT]}"
                for item in (fields if isinstance(fields, list) else [])
                if isinstance(item, dict)
            )
            return f"- {when} {entry.get('title')}: {details}"
        speaker = "User" if entry.get("role") == ROLE_USER else "Agent"
        text = str(entry.get("text", ""))[:RECENT_TEXT_LIMIT]
        return f"- {when} {speaker}: {text}"

    def _propose_config_update(
        self,
        updated_agent_config: dict,
        llm_message: str,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """Keep a chat config change for the user to confirm instead of applying it.

        A value the update would refuse is refused now, before any confirm.

        :param updated_agent_config: the change the model set.
        :param llm_message: the model's message to the user.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        plan = self._plan_or_none(updated_agent_config)
        if plan is None:
            self._handle_unreadable_llm_reply(
                updated_agent_config, http_msg, http_dialogue
            )
            return
        updated_params, issues, _ = plan
        if issues:
            self._refuse_change(issues, http_msg, http_dialogue)
            return
        changes = self._describe_changes(updated_params)
        if not changes:
            self._send_chat_text(llm_message, http_msg, http_dialogue)
            return
        label = http_dialogue.dialogue_label
        self._chat_turns[label] = replace(
            self._chat_turns[label],
            proposal=ConfigProposal(config=updated_agent_config, changes=changes),
        )
        question = (
            f"<b>To confirm:</b> change {self._changes_text(changes)}. Reply yes to "
            "apply it, or anything else to keep your settings."
        )
        text = f"{llm_message}<br><br>{question}" if llm_message else question
        self._send_chat_text(text, http_msg, http_dialogue)

    def _check_confirmation(
        self,
        proposal: ConfigProposal,
        text: str,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """Ask the model whether the user's message confirms the pending change.

        :param proposal: the change waiting for confirmation.
        :param text: the user's message.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        prompt = CONFIRM_PROMPT.format(
            proposal=f"Change {self._changes_text(proposal.changes)}.",
            user_reply=text,
        )
        self._send_llm_request(
            prompt,
            build_confirmation_schema(),
            self._handle_confirmation_response,
            {
                "http_msg": http_msg,
                "http_dialogue": http_dialogue,
                "proposal": proposal,
                "text": text,
            },
        )

    def _handle_confirmation_response(
        self,
        llm_response_message: SrrMessage,
        dialogue: Dialogue,  # pylint: disable=unused-argument
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        proposal: ConfigProposal,
        text: str,
    ) -> None:
        """Apply the pending change if the message confirms it; else answer it normally.

        :param llm_response_message: the SrrMessage with the model's answer
        :param dialogue: the Dialogue
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        :param proposal: the change waiting for confirmation.
        :param text: the user's message.
        """
        try:
            genai_response: Any = json.loads(llm_response_message.payload)
        except _UNPARSEABLE_REPLY:
            genai_response = None
        if self._answer_llm_error(genai_response, http_msg, http_dialogue):
            # Nothing was answered, so the resend of this message decides it.
            self.shared_state.restore_config_proposal(proposal)
            return
        confirmed = self._read_confirmation(genai_response)
        if confirmed is None:
            self.shared_state.restore_config_proposal(proposal)
            self._handle_unreadable_llm_reply(
                llm_response_message.payload, http_msg, http_dialogue
            )
            return
        if confirmed:
            self._apply_proposal(proposal, http_msg, http_dialogue)
            return
        self._answer_prompt(text, http_msg, http_dialogue)

    @staticmethod
    def _read_confirmation(genai_response: Any) -> Optional[bool]:
        """Return whether the model read the user's message as a confirmation.

        :param genai_response: the model connection's reply.
        :return: the model's ``confirmed`` answer, or ``None`` if it gave none.
        """
        if not isinstance(genai_response, dict):
            return None
        try:
            answer = json.loads(genai_response.get(RESPONSE_FIELD, "{}"))
        except _UNPARSEABLE_REPLY:
            return None
        if not isinstance(answer, dict):
            return None
        confirmed = answer.get("confirmed")
        return confirmed if isinstance(confirmed, bool) else None

    def _apply_proposal(
        self,
        proposal: ConfigProposal,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """Apply a confirmed change, record it in the feed and acknowledge it.

        :param proposal: the confirmed change.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        """
        plan = self._plan_or_none(proposal.config)
        if plan is None:
            self._send_chat_text(CHANGE_NOT_APPLIED, http_msg, http_dialogue)
            return
        updated_params, issues, writes = plan
        if issues:
            self._refuse_change(issues, http_msg, http_dialogue)
            return
        changes = self._describe_changes(updated_params)
        written, issues = self._apply_config_writes(writes)
        if written:
            label = http_dialogue.dialogue_label
            self._chat_turns[label] = replace(
                self._chat_turns[label], applied_change=True
            )
        written_labels = {SETTING_LABELS.get(setting) for setting in written}
        saved = [change for change in changes if change.setting in written_labels]
        for change in saved:
            self._record_config_changed(change)
        if issues:
            if saved:
                issues.append(f"I did change {self._changes_text(saved)}.")
            self._send_chat_text("\n".join(issues), http_msg, http_dialogue)
            return
        acknowledgement = (
            f"Done. I changed {self._changes_text(changes)}."
            if changes
            else "Done. Your settings already had that value."
        )
        self._send_chat_text(acknowledgement, http_msg, http_dialogue)

    def _send_chat_text(
        self, text: str, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Answer a chat request with the agent's text."""
        self._send_ok_response(http_msg, http_dialogue, {LLM_MESSAGE_FIELD: text})

    def _refuse_change(
        self, issues: List[str], http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Answer that a chat change was refused as a whole, giving the reasons."""
        # The issues are worded for ``/configure_strategies``, which applies the
        # valid part, so on their own they read as if the rest went through.
        self._send_chat_text(
            "\n".join([CHANGE_REFUSED, *issues]), http_msg, http_dialogue
        )

    @staticmethod
    def _changes_text(changes: List[ConfigChange]) -> str:
        """Describe the changes in one sentence fragment, escaped for the chat's HTML."""
        return "; ".join(
            f"{escape(change.setting)} from {escape(change.before)} "
            f"to {escape(change.after)}"
            for change in changes
        )

    def _record_config_changed(self, change: ConfigChange) -> None:
        """Append a ``Changed the configuration`` card to the feed."""
        record_event(
            self.context.params.store_path,
            EventType.CONFIG_CHANGED,
            [
                field("Setting", change.setting),
                field("Before", change.before),
                field("After", change.after),
            ],
            self.context.logger,
        )

    def _describe_changes(self, updated_params: Dict[str, Any]) -> List[ConfigChange]:
        """Describe each setting the update changes, against the current config.

        :param updated_params: the settings the update sets, as the plan returns them.
        :return: the changes, leaving out settings set to their current value.
        """
        config = self.shared_state.chatui_config
        _, decimals = self.get_units_and_decimals()
        default_goal = self.context.params.default_activity_goal

        def amount(base_units: Optional[int]) -> str:
            if base_units is None:
                return DEFAULT_VALUE
            return format_amount(
                base_units / 10**decimals,
                self.context.params.is_running_on_polymarket,
                SETTING_AMOUNT_DECIMALS,
            )

        def base_units(value: Optional[float]) -> Optional[int]:
            return None if value is None else int(value * 10**decimals)

        def goal(value: Optional[int]) -> str:
            goal_in_force = effective_activity_goal(value, default_goal)
            suffix = " (default)" if value is None else ""
            return f"{goal_in_force} trades per day{suffix}"

        def strategy(value: Any) -> str:
            return self._get_ui_trading_strategy(value).value.capitalize()

        def tools(value: Optional[List[str]]) -> str:
            return ", ".join(value or []) or ALL_TOOLS

        def mechs(value: Optional[List[str]]) -> str:
            return ", ".join(value or []) or ALL_MECHS

        current: Dict[str, Any] = {
            TRADING_STRATEGY_FIELD: strategy(config.trading_strategy),
            ALLOWED_TOOLS_FIELD: tools(config.allowed_tools),
            SELECTED_MECHS_FIELD: mechs(config.selected_mechs),
            "fixed_bet_size": config.fixed_bet_size,
            "max_bet_size": config.max_bet_size,
            ACTIVITY_GOAL_FIELD: goal(config.activity_goal),
        }
        new: Dict[str, Callable[[Any], Any]] = {
            TRADING_STRATEGY_FIELD: strategy,
            ALLOWED_TOOLS_FIELD: tools,
            SELECTED_MECHS_FIELD: mechs,
            "fixed_bet_size": base_units,
            "max_bet_size": base_units,
            ACTIVITY_GOAL_FIELD: goal,
        }
        changes = []
        for setting, value in updated_params.items():
            before, after = current[setting], new[setting](value)
            if before == after:
                continue
            # Amounts are compared in base units: two sizes can share a display.
            if setting in AMOUNT_SETTINGS:
                before, after = amount(before), amount(after)
            changes.append(ConfigChange(SETTING_LABELS[setting], before, after))
        return changes

    def _send_mech_reply(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue, text: str
    ) -> None:
        """Answer a mech turn with text written by the handler and no config update."""
        self._send_ok_response(
            http_msg,
            http_dialogue,
            {UPDATED_PARAMS_FIELD: {}, LLM_MESSAGE_FIELD: text},
        )

    def _price_at_live_rate(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue, facts: MechFacts
    ) -> None:
        """Report a third-party mech at the higher of its listed and live rates; one with no listing is unpriced, as discovery skips it."""
        listed = facts.max_delivery_rate
        if (
            facts.record is not RecordStatus.FOUND
            or facts.address in self.context.params.valid_mechs
            or listed is None
        ):
            self._send_mech_report(http_msg, http_dialogue, facts)
            return

        def on_rate(live: Optional[int]) -> None:
            rate = listed if live is None else max(listed, live)
            self._send_mech_report(
                http_msg, http_dialogue, replace(facts, max_delivery_rate=rate)
            )

        read_live_rate(self.context, facts.address, on_rate)

    def _send_mech_report(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue, facts: MechFacts
    ) -> None:
        """Answer with the mech's report; the offer it ends with, or none, replaces the one kept."""
        address = facts.address
        standing = Standing(
            valory=address in self.context.params.valid_mechs,
            cap=delivery_rate_bound(
                address,
                str(facts.payment_type),
                self.context.params.delivery_rate_caps,
                {},
            ),
            accepted_rate=self.shared_state.approved_mech_rates.get(address),
            pinnable=address in self._get_available_valid_mechs(),
            pinned=address in self._pinned_mechs(),
        )
        text, offer = render_report(facts, standing, datetime.now(timezone.utc))
        self.shared_state.last_shown_mech = address
        if offer is not None:
            self.shared_state.record_mech_offer(offer)
        else:
            self.shared_state.record_mech_refusal(address, verdict(facts, standing))
        self._send_mech_reply(http_msg, http_dialogue, text)

    def _rate_text(self, payment_type: str, rate: int) -> Optional[str]:
        """A rate in its payment asset on this chain, or `None` when no figure can be named."""
        chain_id = chain_id_of(str(self.context.params.mech_chain_id))
        return payment_line(payment_type, rate, chain_id)[1]

    def _price_text(self, offer: Offer, rate: int) -> str:
        """Render a rate in the offer's asset."""
        text = self._rate_text(offer.payment_type, rate)
        return text if text is not None else str(rate)

    def _refusal_reply(self, address: str) -> Optional[str]:
        """Why there is nothing to accept, when the last report for the mech made no offer."""
        refusal = self.shared_state.mech_refusals.get(address)
        if refusal is None:
            return None
        return f"There is nothing to accept for {address}. {refusal}"

    def _accept_offer(
        self, accept: Accept, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Approve when the typed price is the one the last report showed."""
        address = accept.address
        refusal = self._refusal_reply(address)
        if refusal is not None:
            self._send_mech_reply(http_msg, http_dialogue, refusal)
            return
        offer = self.shared_state.mech_offers.get(address)
        if offer is None or normalise(offer.price_text) != accept.price_text:
            self._send_mech_reply(
                http_msg,
                http_dialogue,
                f"There is no offer at that price for {address}. "
                "Ask about the mech to see its current terms.",
            )
            return
        self._take_offer(offer, http_msg, http_dialogue)

    def _approve_mech(
        self,
        address: str,
        last_shown: Optional[str],
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """Take the offer, or repeat why there is none, only when the mech's report was the reply right before; otherwise show the report."""
        if address == last_shown:
            offer = self.shared_state.mech_offers.get(address)
            if offer is not None:
                self._take_offer(offer, http_msg, http_dialogue)
                return
            refusal = self._refusal_reply(address)
            if refusal is not None:
                self._send_mech_reply(http_msg, http_dialogue, refusal)
                return
        self._report_mech(address, http_msg, http_dialogue)

    def _take_offer(
        self, offer: Offer, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Approve at the shown rate once the live rate is read and is no higher."""

        def on_rate(live: Optional[int]) -> None:
            self._send_mech_reply(http_msg, http_dialogue, self._settle(offer, live))

        read_live_rate(self.context, offer.address, on_rate)

    def _settle(self, offer: Offer, live: Optional[int]) -> str:
        """Record the approval when the live rate is readable and within the offer, and say what happened."""
        address = offer.address
        if live is None:
            return (
                f"I can't read what {address} charges right now, so nothing was "
                "approved. Try again later."
            )
        self.shared_state.drop_mech_offer(offer)
        if live > offer.rate:
            return (
                f"The listing is out of date: {address} now charges "
                f"{self._price_text(offer, live)} per request. Ask about this mech "
                "again to see the new terms."
            )
        again = " again" if address in self.shared_state.approved_mech_rates else ""
        self.shared_state.approve_mech(address, offer.rate, offer.payment_type)
        when = (
            "Your agent has met its activity goal for this staking epoch, so it "
            "can use it from the next epoch."
            if self._trading_paused()
            else "Your agent can use it for its next mech requests."
        )
        return (
            f"Approved {address}{again} at up to {offer.price_text} per request. {when}"
        )

    def _trading_paused(self) -> bool:
        """Whether the agent skips trading for the rest of this epoch, by the stop-trading vote's conditions."""
        goal = self.shared_state.read_activity_goal_from_disk()
        db = self.synchronized_data.db
        return bool(
            self.context.params.stop_trading_if_staking_kpi_met
            and db.get("is_activity_target_met", False)
            and goal is not None
            and goal.is_met
            and goal.period_start == db.get("previous_checkpoint", None)
        )

    def _approved_price(self, address: str, rate: int) -> Optional[str]:
        """An approved mech's accepted price, when its payment type names an asset."""
        kind = self.shared_state.approved_mech_payment_types.get(address)
        if kind is None:
            return None
        return self._rate_text(kind, rate)

    def _approved_entry(self, address: str, rate: int) -> str:
        """One approved mech with its accepted price, when the payment type is known."""
        price = self._approved_price(address, rate)
        if price is not None:
            return f"{address}, up to {price} per request"
        return f"{address} (send its address to see its price)"

    def _list_entry(self, address: str, payment_types: Dict[str, str]) -> str:
        """One listed mech: approved at its accepted price, or Valory with its payment method."""
        rate = self.shared_state.approved_mech_rates.get(address)
        if rate is not None:
            price = self._approved_price(address, rate)
            terms = (
                f"approved, up to {price} per request"
                if price is not None
                else "approved; ask about it to see its price"
            )
        else:
            kind = payment_types.get(address)
            chain_id = chain_id_of(str(self.context.params.mech_chain_id))
            terms = (
                "Valory"
                if kind is None
                else f"Valory, paid with {payment_line(kind, None, chain_id)[0]}"
            )
        pinned = ", pinned" if address in self._pinned_mechs() else ""
        return f"{address}, {terms}{pinned}"

    def _mech_list(self) -> str:
        """Number the mechs the agent may use, Valory then approved, and keep the list."""
        approved = self.shared_state.approved_mechs
        discovered, payment_types = self._discovered_mechs()
        valid_mechs = self.context.params.valid_mechs
        valory = sorted(
            mech for mech in discovered if mech in valid_mechs and mech not in approved
        )
        mechs = [*valory, *approved]
        self.shared_state.last_mech_list = mechs
        if not mechs:
            return (
                "Your agent has no mechs to list yet. Send a mech's address to see "
                "its report."
            )
        entries = "<br>".join(
            f"{number}. {self._list_entry(address, payment_types)}"
            for number, address in enumerate(mechs, start=1)
        )
        return PARAGRAPH_BREAK.join(
            [
                f"Mechs your agent can use:<br>{entries}",
                "Refer to one by its number or its address.",
            ]
        )

    def _which_mech(self) -> str:
        """Ask which mech a message meant, with the list to pick from."""
        return PARAGRAPH_BREAK.join([WHICH_MECH, self._mech_list()])

    def _remove_mech(self, address: str) -> str:
        """Remove an approved mech, or say there is nothing to remove."""
        if address not in self.shared_state.approved_mech_rates:
            if address in self.context.params.valid_mechs:
                return VALORY_NOT_REMOVABLE.format(address=address)
            return (
                f"{address} is not approved, so there is nothing to remove. {NEXT_STEP}"
            )
        removed = RemovedMech(
            address,
            self.shared_state.approved_mech_rates[address],
            self.shared_state.approved_mech_payment_types.get(address),
            address in self._pinned_mechs(),
        )
        notes = self._remove_approved_mechs([address])
        self.shared_state.last_removed = removed
        return " ".join(
            [
                *notes,
                "To undo, reply undo. After another message, send its address to see "
                "its report and approve it again.",
            ]
        )

    def _undo_removal(
        self, removed: Optional[RemovedMech], address: Optional[str]
    ) -> str:
        """Put back the approval the reply before this message removed, at the ceiling the user had accepted.

        :param removed: the approval the reply before this message removed, if any.
        :param address: the mech the message refers to; anything but the removed
            mech puts nothing back and keeps the undo open for the next message.
        :return: the reply.
        """
        if removed is None:
            return "There is no removal to undo."
        if address != removed.address:
            self.shared_state.last_removed = removed
            return (
                f"Your message names another mech, not {removed.address}, the one "
                "just removed, so nothing was put back. To put it back, reply undo."
            )
        self.shared_state.approve_mech(
            removed.address, removed.rate, removed.payment_type
        )
        again = ""
        if removed.pinned:
            pins = self._pinned_mechs()
            if removed.address not in pins:
                repinned = [*pins, removed.address]
                self._store_selected_mechs(repinned)
                self._record_pins_changed(pins, repinned)
            again = " and pinned it again"
        price = self._approved_price(removed.address, removed.rate)
        ceiling = f"up to {price} per request" if price else "the price you accepted"
        return (
            f"Put back {removed.address} at {ceiling}{again}. If it now charges more, "
            "your agent won't use it until you approve the new price."
        )

    def _pinned_mechs(self) -> List[str]:
        """The pinned mech addresses, lowercase."""
        pins = self.shared_state.chatui_config.selected_mechs or []
        return [str(mech).lower() for mech in pins]

    def _pin_mech(self, address: str) -> str:
        """Pin a mech the agent may use: a discovered Valory mech or an approved one."""
        if address not in self._get_available_valid_mechs():
            return "I can only pin a Valory mech the agent uses or a mech you approved."
        pins = self._pinned_mechs()
        if address in pins:
            return (
                f"{address} is already pinned. Mech requests go only to your pinned "
                f"mechs: {', '.join(pins)}."
            )
        before = pins
        pins = [*pins, address]
        self._store_selected_mechs(pins)
        self._record_pins_changed(before, pins)
        return (
            f"Pinned {address}. Mech requests now go only to your pinned mechs: "
            f"{', '.join(pins)}. To undo, tell me to unpin {address}."
        )

    def _record_pins_changed(self, before: List[str], after: List[str]) -> None:
        """Record a typed pin or unpin, which applies at once, in the feed."""
        self._record_config_changed(
            ConfigChange(
                SETTING_LABELS[SELECTED_MECHS_FIELD],
                ", ".join(before) or ALL_MECHS,
                ", ".join(after) or ALL_MECHS,
            )
        )

    def _unpin_mech(self, address: str) -> str:
        """Unpin a mech; an empty pin list means normal mech selection."""
        pins = self._pinned_mechs()
        if address not in pins:
            return f"{address} is not pinned. {NEXT_STEP}"
        remaining = [mech for mech in pins if mech != address]
        self._store_selected_mechs(remaining or None)
        self._record_pins_changed(pins, remaining)
        undo = f"To undo, tell me to pin {address}."
        if remaining:
            return f"Unpinned {address}. Still pinned: {', '.join(remaining)}. {undo}"
        return f"Unpinned {address}. Mech selection is back to normal. {undo}"

    def _send_chatui_prompt(
        self,
        user_prompt: str,
        available_tools: Any,
        valory_tools: Set[str],
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        last_shown: Optional[str] = None,
        last_list: Sequence[str] = (),
        last_removed: Optional[RemovedMech] = None,
    ) -> None:
        """Fill the config prompt and ask the LLM.

        :param user_prompt: the user's message.
        :param available_tools: the tools the user may pin.
        :param valory_tools: the tool names a Valory mech serves, the only ones listed.
        :param http_msg: the HttpMessage instance
        :param http_dialogue: the HttpDialogue instance
        :param last_shown: the mech whose report was the reply before this message
        :param last_list: the numbered list that was the reply before this message
        :param last_removed: the approval the reply before this message removed
        """
        available_mechs = self._get_available_valid_mechs()
        current_trading_strategy = self.shared_state.chatui_config.trading_strategy
        current_allowed_tools_raw = self.shared_state.chatui_config.allowed_tools
        current_allowed_tools = (
            _tools_for_prompt(current_allowed_tools_raw, valory_tools)
            if current_allowed_tools_raw
            else "Automatic tool selection based on policy (all available tools)"
        )
        current_selected_mechs_raw = self.shared_state.chatui_config.selected_mechs
        current_selected_mechs = (
            ", ".join(current_selected_mechs_raw)
            if current_selected_mechs_raw
            else "All configured valid mechs"
        )
        current_fixed_bet_size = self.shared_state.chatui_config.fixed_bet_size
        current_max_bet_size = self.shared_state.chatui_config.max_bet_size
        absolute_max_bet_size = self.context.params.strategies_kwargs[
            "absolute_max_bet_size"
        ]
        absolute_min_bet_size = self.context.params.strategies_kwargs[
            "absolute_min_bet_size"
        ]

        units, decimals = self.get_units_and_decimals()

        default_activity_goal = self.context.params.default_activity_goal
        current_activity_goal = self.shared_state.chatui_config.activity_goal
        published_goal = self.shared_state.read_activity_goal_from_disk()

        chat_turn = self._chat_turn(http_dialogue)
        template = CHATUI_PROMPT if chat_turn is None else CHAT_PROMPT
        prompt = template.format(
            user_prompt=user_prompt,
            recent_activity=(
                "" if chat_turn is None else self._recent_activity(chat_turn)
            ),
            current_trading_strategy=current_trading_strategy,
            current_allowed_tools=current_allowed_tools,
            available_tools=_tools_for_prompt(available_tools, valory_tools),
            current_selected_mechs=current_selected_mechs,
            current_approved_mechs=(
                "; ".join(
                    self._approved_entry(address, rate)
                    for address, rate in self.shared_state.approved_mech_rates.items()
                )
                or "None"
            ),
            available_mechs=(
                ", ".join(sorted(available_mechs))
                if available_mechs
                else "(none discovered yet)"
            ),
            current_fixed_bet_size=(
                current_fixed_bet_size / (10**decimals)
                if current_fixed_bet_size is not None
                else None
            ),
            current_max_bet_size=(
                current_max_bet_size / (10**decimals)
                if current_max_bet_size is not None
                else None
            ),
            absolute_min_bet_size=absolute_min_bet_size / (10**decimals),
            absolute_max_bet_size=absolute_max_bet_size / (10**decimals),
            units=units,
            decimals=decimals,
            current_activity_goal=effective_activity_goal(
                current_activity_goal, default_activity_goal
            ),
            activity_goal_source=(
                "the default" if current_activity_goal is None else "set by the user"
            ),
            default_activity_goal=default_activity_goal,
            activity_goal_progress=(
                "not counted yet" if published_goal is None else published_goal.progress
            ),
        )
        self._send_chatui_llm_request(
            prompt=prompt,
            http_msg=http_msg,
            http_dialogue=http_dialogue,
            user_prompt=user_prompt,
            last_shown=last_shown,
            last_list=last_list,
            last_removed=last_removed,
        )

    def _send_chatui_llm_request(
        self,
        prompt: str,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        user_prompt: str,
        last_shown: Optional[str] = None,
        last_list: Sequence[str] = (),
        last_removed: Optional[RemovedMech] = None,
    ) -> None:
        """Ask the model for a config update or a mech intent; `_handle_chatui_llm_response` gets the reply."""
        self._send_llm_request(
            prompt,
            build_chatui_llm_response_schema(),
            self._handle_chatui_llm_response,
            {
                "http_msg": http_msg,
                "http_dialogue": http_dialogue,
                "user_prompt": user_prompt,
                "last_shown": last_shown,
                "last_list": last_list,
                "last_removed": last_removed,
            },
        )

    def _send_llm_request(
        self,
        prompt: str,
        schema: Dict[str, Any],
        callback: Callable[..., None],
        callback_kwargs: Dict[str, Any],
    ) -> None:
        """Send a prompt to the model connection; `callback` gets the reply with the kwargs."""
        payload_data = {"prompt": prompt, "schema": schema}

        self.context.logger.info(f"Payload data: {payload_data}")

        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)
        request_srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(GENAI_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(payload_data),
        )
        self._send_message(request_srr_message, srr_dialogue, callback, callback_kwargs)

    def _discovered_mechs(self) -> Tuple[FrozenSet[str], Dict[str, str]]:
        """The discovered mechs and their payment types, kept from the last period until a new one writes them."""
        data = self.synchronized_data
        if data.mechs_info_loaded:
            self.shared_state.discovered_mechs = (
                frozenset(data.available_valid_mechs),
                data.mech_payment_types,
            )
        mechs, payment_types = self.shared_state.discovered_mechs
        return mechs, dict(payment_types)

    def _get_available_valid_mechs(self) -> Set[str]:
        """Return the mechs the user may pin: discovered Valory mechs and approved mechs."""
        valid_mechs = self.context.params.valid_mechs
        discovered = {
            mech for mech in self._discovered_mechs()[0] if mech in valid_mechs
        }
        return discovered | set(self.shared_state.approved_mechs)

    def _available_tools(self) -> Set[str]:
        """Resolve the user-selectable mech tool set.

        Prefers the suitability-filtered set the decision-maker's
        ToolSelectionBehaviour publishes on shared state
        (``available_prediction_tools``) so the ChatUI displays and validates
        tool pins against the same universe the policy can actually select
        from. Falls back to the raw ``available_mech_tools`` synced-data set
        when the filtered set has not been published *or is empty*: cold start
        before the first ``ToolSelectionRound``, a round where every manifest
        fetch failed, or the V1 marketplace path (which has no classifier and
        already filters at the feed point). The empty-set case falls back too —
        an empty ``frozenset`` ("nothing selectable") must not be read as a hard
        "reject every pin", which would brick ``configure_strategies``.

        :return: the set of tool names the user may pin / that are advertised.
        """
        prediction_tools = self.shared_state.available_prediction_tools
        if prediction_tools:
            # Materialise to a plain ``set``: this value is str-formatted into
            # the LLM prompt ("Available tools: {available_tools}"), where a
            # ``frozenset`` renders as "frozenset({...})". The copy keeps the
            # rendering consistent with the ``available_mech_tools`` fallback.
            return set(prediction_tools)
        return tool_names(self.synchronized_data.available_mech_tools)

    def _valory_tool_names(self) -> Set[str]:
        """Names of tools a Valory mech serves, the only tool names the prompt lists."""
        keys: Iterable[str] = self.synchronized_data.available_mech_tools or []
        return {
            tool
            for identity, tool in map(split_tool_key, keys)
            if identity in (None, VALORY_LABEL)
        }

    def _get_available_tools(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> Optional[Tuple[Set[str], Set[str]]]:
        """Get the available mech tools and the tool names a Valory mech serves; answer 425 while either is not loaded."""
        try:
            return self._available_tools(), self._valory_tool_names()
        except (TypeError, AttributeError) as e:
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

    def _get_ui_trading_strategy(
        self, selected_value: Optional[str]
    ) -> TradingStrategyUI:
        """Get the UI trading strategy."""
        if selected_value is None:
            return TradingStrategyUI.BALANCED

        if selected_value in (
            TradingStrategy.KELLY_CRITERION.value,
            "kelly_criterion_no_conf",
        ):
            return TradingStrategyUI.RISKY
        if selected_value in (
            TradingStrategy.FIXED_BET.value,
            "bet_amount_per_threshold",
        ):
            return TradingStrategyUI.BALANCED
        return TradingStrategyUI.RISKY

    def _handle_chatui_llm_response(
        self,
        llm_response_message: SrrMessage,
        dialogue: Dialogue,  # pylint: disable=unused-argument
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        user_prompt: str = "",
        last_shown: Optional[str] = None,
        last_list: Sequence[str] = (),
        last_removed: Optional[RemovedMech] = None,
    ) -> None:
        """
        Handle the response from the LLM.

        A reply with a known mech intent is carried out in code, and its
        message and config update are not used.

        :param llm_response_message: the SrrMessage with the LLM output
        :param dialogue: the Dialogue
        :param http_msg: the original HttpMessage
        :param http_dialogue: the original HttpDialogue
        :param user_prompt: the user's message, the only text an intent's address may come from
        :param last_shown: the mech whose report was the reply before this message
        :param last_list: the numbered list that was the reply before this message
        :param last_removed: the approval the reply before this message removed
        """
        self.context.logger.info(
            f"LLM response payload: {llm_response_message.payload}"
        )

        # Store the current trading strategy before any updates
        previous_trading_strategy = copy.deepcopy(
            self.shared_state.chatui_config.trading_strategy
        )

        try:
            genai_response: dict = json.loads(llm_response_message.payload)
        except _UNPARSEABLE_REPLY:
            self._handle_unreadable_llm_reply(
                llm_response_message.payload, http_msg, http_dialogue
            )
            return

        if self._answer_llm_error(genai_response, http_msg, http_dialogue):
            return

        llm_response = genai_response.get(RESPONSE_FIELD, "{}")
        try:
            llm_response_json = json.loads(llm_response)
        except _UNPARSEABLE_REPLY:
            self._handle_unreadable_llm_reply(llm_response, http_msg, http_dialogue)
            return
        if not isinstance(llm_response_json, dict):
            self._handle_unreadable_llm_reply(llm_response, http_msg, http_dialogue)
            return

        reading = llm_response_json.get(MECH_INTENT_FIELD)
        intent, address = resolve_intent(
            reading,
            user_prompt,
            last_shown,
            last_list,
            None if last_removed is None else last_removed.address,
        )
        if intent is not MechIntent.NONE:
            if self._changes_config(llm_response_json.get(UPDATED_CONFIG_FIELD)):
                self.context.logger.warning(
                    "The reply asked for a mech action and a config change; "
                    "neither was done."
                )
                self._send_mech_reply(http_msg, http_dialogue, ONE_REQUEST_AT_A_TIME)
                return
            number = _list_number(reading, address, last_list)
            self._run_mech_intent(
                intent,
                address,
                last_shown,
                http_msg,
                http_dialogue,
                number,
                last_removed,
            )
            return
        if reading is not None and (
            not isinstance(reading, dict)
            or reading.get("intent") not in (None, MechIntent.NONE.value)
        ):
            self.context.logger.warning(
                f"Ignoring an unreadable mech intent: {reading}"
            )

        llm_message = llm_response_json.get(MESSAGE_FIELD, "")
        updated_agent_config = llm_response_json.get(UPDATED_CONFIG_FIELD, {})

        if not updated_agent_config:
            self.context.logger.warning(
                "No agent configuration update provided by the LLM."
            )
            self._send_ok_response(
                http_msg,
                http_dialogue,
                {
                    UPDATED_PARAMS_FIELD: {},
                    LLM_MESSAGE_FIELD: llm_message,
                },
            )
            return

        if not self._config_update_is_readable(updated_agent_config):
            self._handle_unreadable_llm_reply(llm_response, http_msg, http_dialogue)
            return
        updated_agent_config, pin_note = self._keep_named_or_pinned_mechs(
            updated_agent_config, user_prompt
        )

        if self._chat_turn(http_dialogue) is not None:
            self._propose_config_update(
                updated_agent_config, llm_message, http_msg, http_dialogue
            )
            return

        try:
            updated_agent_config, tools_note = self._keep_unlisted_allowed_tools(
                updated_agent_config, user_prompt
            )
            updated_params, issues = self._process_updated_agent_config(
                updated_agent_config
            )
            issues = [note for note in (pin_note, tools_note) if note] + issues
        except Exception as exc:  # pylint: disable=broad-except
            # The update reads this object field by field and expects a
            # shape the model is under no obligation to produce. Any wrong
            # type raises somewhere in there, and enumerating them cannot
            # be complete: a list of the right type can still hold items
            # that are unhashable or unformattable. So the answer is the
            # same as for a reply that was never JSON.
            self.context.logger.error(
                f"LLM reply was JSON but not usable as a config update: {exc}"
            )
            self._handle_unreadable_llm_reply(llm_response, http_msg, http_dialogue)
            return
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

        self._send_ok_response(
            http_msg,
            http_dialogue,
            response_body,
        )

    def _changes_config(self, update: Any) -> bool:
        """Whether a reply's config update removes a setting or sets one to a value other than the current one; `behavior` never counts."""
        if not isinstance(update, dict):
            return False
        if update.get(REMOVED_CONFIG_FIELDS_FIELD):
            return True
        return any(
            update.get(name) is not None and not self._is_current(name, update[name])
            for name in _SETTINGS
        )

    def _is_current(self, name: str, value: Any) -> bool:
        """Whether a reply's value for a setting is the agent's current one; a value that cannot be compared is not."""
        config = self.shared_state.chatui_config
        if name == ALLOWED_TOOLS_FIELD:
            return isinstance(value, list) and set(map(str, value)) == set(
                config.allowed_tools or []
            )
        if name == SELECTED_MECHS_FIELD:
            return isinstance(value, list) and {
                str(mech).lower() for mech in value
            } == set(self._pinned_mechs())
        if name in self._LLM_CONFIG_NUMERIC_FIELDS:
            # The reply is in display units; the config keeps the smallest unit.
            if not self._is_finite_number(value):
                return False
            _, decimals = self.get_units_and_decimals()
            scaled = value * (10**decimals)
            if isinstance(scaled, float) and not math.isfinite(scaled):
                return False
            return int(scaled) == getattr(config, name)
        if name == ACTIVITY_GOAL_FIELD:
            return value == effective_activity_goal(
                config.activity_goal, self.context.params.default_activity_goal
            )
        return value == config.trading_strategy

    def _keep_named_or_pinned_mechs(
        self, update: Dict[str, Any], user_prompt: str
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """The update with its pin list cut to mechs named in the user's message or already pinned, and a note when any were left out."""
        mechs = update.get(SELECTED_MECHS_FIELD)
        if not mechs:
            return update, None
        allowed = set(addresses_in(user_prompt)) | set(self._pinned_mechs())
        kept = [mech for mech in mechs if str(mech).lower() in allowed]
        dropped = [
            str(mech).lower() for mech in mechs if str(mech).lower() not in allowed
        ]
        if not dropped:
            return update, None
        note = (
            f"Not pinned, since your message didn't name them: {', '.join(dropped)}. "
            "Send the address of a mech you want to pin."
        )
        self.context.logger.warning(note)
        return {**update, SELECTED_MECHS_FIELD: kept or None}, note

    def _keep_unlisted_allowed_tools(
        self, update: Dict[str, Any], user_prompt: str
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """The update with the allowed tools the prompt did not list put back, unless the user's message names them.

        The model sends the whole allowed list but sees only tool names a Valory
        mech serves, so an edit it makes cannot drop a tool it was not shown.
        Clearing the field through the removed fields still clears every tool.

        :param update: the config update the model returned.
        :param user_prompt: the user's message.
        :return: the update, and a note giving the new list when a tool was kept,
            or `None`.
        """
        tools = update.get(ALLOWED_TOOLS_FIELD)
        if not isinstance(tools, list):
            return update, None
        typed = _typed_names(user_prompt)
        listed = self._valory_tool_names()
        available = self._available_tools()
        current = self.shared_state.chatui_config.allowed_tools or []
        kept = [
            tool
            for tool in current
            if tool not in listed
            and tool not in tools
            and tool not in typed
            and tool in available
        ]
        if not kept:
            return update, None
        now = [tool for tool in tools if tool in available] + kept
        note = (
            f"Allowed tools are now: {escape(', '.join(map(str, now)))}. Kept "
            f"{escape(', '.join(kept))}, since your message didn't name it. To drop "
            "a tool, send its exact name."
        )
        self.context.logger.info(note)
        return {**update, ALLOWED_TOOLS_FIELD: [*tools, *kept]}, note

    def _answer_llm_error(
        self, genai_response: Any, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> bool:
        """Answer the caller when the model connection reported an error; `True` when it did."""
        if not isinstance(genai_response, dict) or "error" not in genai_response:
            return False
        if genai_response.get("code") == MECH_DEPOSIT_REQUIRED_CODE:
            self._handle_mech_deposit_required(genai_response, http_msg, http_dialogue)
        else:
            self._handle_chatui_llm_error(
                genai_response["error"], http_msg, http_dialogue
            )
        return True

    def _remove_approved_mechs(self, addresses: List[str]) -> List[str]:
        """Remove approved mechs, unpinning any that were pinned."""
        approved = self.shared_state.approved_mechs
        removed = [address for address in addresses if address in approved]
        unknown = [address for address in addresses if address not in approved]
        notes = (
            [f"Not approved, so nothing to remove: {', '.join(unknown)}."]
            if unknown
            else []
        )
        if not removed:
            return notes
        self.shared_state.set_approved_mech_rates(
            {
                address: rate
                for address, rate in self.shared_state.approved_mech_rates.items()
                if address not in removed
            }
        )
        notes.append(
            f"Removed {', '.join(removed)}. No new requests go to it from the next "
            "cycle; a request already sent to it can still be answered and bet on."
        )
        pin = self.shared_state.chatui_config.selected_mechs or []
        unpinned = [mech for mech in pin if mech.lower() in removed]
        if unpinned:
            remaining = [mech for mech in pin if mech.lower() not in removed]
            self._store_selected_mechs(remaining or None)
            self._record_pins_changed(
                [mech.lower() for mech in pin], [mech.lower() for mech in remaining]
            )
            notes.append(
                f"It was pinned, so {', '.join(unpinned)} is unpinned"
                + (
                    f"; still pinned: {', '.join(m.lower() for m in remaining)}."
                    if remaining
                    else " and mech selection is back to normal."
                )
            )
        return notes

    def _process_updated_agent_config(self, updated_agent_config: dict) -> tuple:
        """
        Process the updated agent config from the LLM response.

        :param updated_agent_config: dict containing updated config
        :return: tuple of (updated_params, issues)
        """
        updated_params, issues, writes = self._plan_config_update(updated_agent_config)
        _, write_issues = self._apply_config_writes(writes)
        issues.extend(write_issues)
        return updated_params, issues

    def _plan_or_none(
        self, updated_agent_config: dict
    ) -> Optional[Tuple[Dict, List[str], Dict[str, Callable[[], None]]]]:
        """Plan a config update; ``None`` when the model's object cannot be read as one.

        :param updated_agent_config: the change the model set.
        :return: the plan, or ``None``.
        """
        try:
            return self._plan_config_update(updated_agent_config)
        except Exception as exc:  # pylint: disable=broad-except
            # As in ``_handle_chatui_llm_response``: the model decides the
            # shape, so any field can fail and no list of types is complete.
            self.context.logger.error(
                f"LLM reply was JSON but not usable as a config update: {exc}"
            )
            return None

    def _plan_config_update(
        self, updated_agent_config: dict
    ) -> Tuple[Dict, List[str], Dict[str, Callable[[], None]]]:
        """Validate a config update and collect its writes, applying nothing.

        :param updated_agent_config: dict containing updated config
        :return: the settings it sets, the issues found and the writes to apply,
            by setting.
        """
        updated_params: Dict = {}
        issues: List[str] = []
        # Writes are collected and applied at the end rather than as each
        # field is read. The model decides the shape of this object, so any
        # field can fail part-way through, and writing as we go left the
        # earlier settings saved while the caller was told the update failed.
        writes: Dict[str, Callable[[], None]] = {}
        # A list, not a set: the guard ahead of this refuses a bare string,
        # on which ``in`` would match by substring.
        removed_fields: List[str] = (
            updated_agent_config.get(REMOVED_CONFIG_FIELDS_FIELD) or []
        )

        updated_trading_strategy: Optional[str] = updated_agent_config.get(
            TRADING_STRATEGY_FIELD, None
        )
        if updated_trading_strategy:
            if updated_trading_strategy in AVAILABLE_TRADING_STRATEGIES:
                updated_params.update({"trading_strategy": updated_trading_strategy})
                writes[TRADING_STRATEGY_FIELD] = partial(
                    self._store_trading_strategy, updated_trading_strategy
                )
            else:
                issue_message = f"Unsupported trading strategy: {updated_trading_strategy!r}. Available strategies are: {', '.join(AVAILABLE_TRADING_STRATEGIES)}."
                self.context.logger.warning(issue_message)
                issues.append(issue_message)

        updated_allowed_tools: Optional[List[str]] = updated_agent_config.get(
            ALLOWED_TOOLS_FIELD, None
        )
        allowed_tools_is_removed: bool = (
            FieldsThatCanBeRemoved.ALLOWED_TOOLS.value in removed_fields
        )

        if allowed_tools_is_removed:
            updated_params.update({ALLOWED_TOOLS_FIELD: None})
            writes[ALLOWED_TOOLS_FIELD] = partial(self._store_allowed_tools, None)

        elif updated_allowed_tools is not None:
            available = self._available_tools()
            unknown = [t for t in updated_allowed_tools if t not in available]
            valid = [t for t in updated_allowed_tools if t in available]
            if unknown:
                issue_message = (
                    f"Unknown tool(s) ignored: {escape(str(unknown))}. "
                    f"Available tools are: {escape(', '.join(available))}."
                )
                self.context.logger.warning(issue_message)
                issues.append(issue_message)
            if valid:
                updated_params.update({ALLOWED_TOOLS_FIELD: valid})
                writes[ALLOWED_TOOLS_FIELD] = partial(self._store_allowed_tools, valid)
            elif not unknown:
                # empty list explicitly passed — treat as clear
                updated_params.update({ALLOWED_TOOLS_FIELD: None})
                writes[ALLOWED_TOOLS_FIELD] = partial(self._store_allowed_tools, None)

        updated_selected_mechs: Optional[List[str]] = updated_agent_config.get(
            SELECTED_MECHS_FIELD, None
        )
        selected_mechs_is_removed: bool = (
            FieldsThatCanBeRemoved.SELECTED_MECHS.value in removed_fields
        )

        if selected_mechs_is_removed:
            updated_params.update({SELECTED_MECHS_FIELD: None})
            writes[SELECTED_MECHS_FIELD] = partial(self._store_selected_mechs, None)

        elif updated_selected_mechs is not None:
            # Address comparison is case-insensitive; the synced data stores
            # lowercase addresses to match the subgraph format.
            available_mechs = self._get_available_valid_mechs()
            normalized = [str(m).lower() for m in updated_selected_mechs]
            unknown_mechs = [m for m in normalized if m not in available_mechs]
            valid_mechs = [m for m in normalized if m in available_mechs]
            if unknown_mechs:
                issue_message = (
                    f"Unknown mech(s) ignored: {unknown_mechs}. "
                    f"Available mechs are: {', '.join(sorted(available_mechs)) or '(none discovered yet)'}."
                )
                self.context.logger.warning(issue_message)
                issues.append(issue_message)
            if valid_mechs:
                updated_params.update({SELECTED_MECHS_FIELD: valid_mechs})
                writes[SELECTED_MECHS_FIELD] = partial(
                    self._store_selected_mechs, valid_mechs
                )
            elif not unknown_mechs:
                updated_params.update({SELECTED_MECHS_FIELD: None})
                writes[SELECTED_MECHS_FIELD] = partial(self._store_selected_mechs, None)

        _, decimals = self.get_units_and_decimals()
        absolute_max_bet_size = self.context.params.strategies_kwargs[
            "absolute_max_bet_size"
        ]
        absolute_min_bet_size = self.context.params.strategies_kwargs[
            "absolute_min_bet_size"
        ]

        updated_fixed_bet_size: Optional[int] = updated_agent_config.get(
            "fixed_bet_size", None
        )
        fixed_bet_size_is_removed: bool = (
            FieldsThatCanBeRemoved.FIXED_BET_SIZE.value in removed_fields
        )
        if fixed_bet_size_is_removed:
            updated_params.update({"fixed_bet_size": None})
            writes["fixed_bet_size"] = partial(
                self._set_chatui_param, "fixed_bet_size", None
            )

        elif updated_fixed_bet_size is not None:
            updated_fixed_bet_size_in_base_units = int(
                updated_fixed_bet_size * (10**decimals)
            )
            if (
                updated_fixed_bet_size_in_base_units >= absolute_min_bet_size
                and updated_fixed_bet_size_in_base_units <= absolute_max_bet_size
            ):
                updated_params.update({"fixed_bet_size": updated_fixed_bet_size})
                writes["fixed_bet_size"] = partial(
                    self._set_chatui_param,
                    "fixed_bet_size",
                    updated_fixed_bet_size_in_base_units,
                )
            else:
                issue_message = f"Fixed bet size {updated_fixed_bet_size} is out of bounds. It must be between {absolute_min_bet_size / 10**decimals} and {absolute_max_bet_size / 10**decimals}."
                self.context.logger.warning(issue_message)
                issues.append(issue_message)

        updated_max_bet_size: Optional[int] = updated_agent_config.get(
            "max_bet_size", None
        )
        max_bet_size_is_removed: bool = (
            FieldsThatCanBeRemoved.MAX_BET_SIZE.value in removed_fields
        )
        if max_bet_size_is_removed:
            updated_params.update({"max_bet_size": None})
            writes["max_bet_size"] = partial(
                self._set_chatui_param, "max_bet_size", None
            )
        elif updated_max_bet_size is not None:
            updated_max_bet_size_in_base_units = int(
                updated_max_bet_size * (10**decimals)
            )
            if (
                updated_max_bet_size_in_base_units >= absolute_min_bet_size
                and updated_max_bet_size_in_base_units <= absolute_max_bet_size
            ):
                updated_params.update({"max_bet_size": updated_max_bet_size})
                writes["max_bet_size"] = partial(
                    self._set_chatui_param,
                    "max_bet_size",
                    updated_max_bet_size_in_base_units,
                )
            else:
                issue_message = f"Max bet size {updated_max_bet_size} is out of bounds. It must be between {absolute_min_bet_size / 10**decimals} and {absolute_max_bet_size / 10**decimals}."
                self.context.logger.warning(issue_message)
                issues.append(issue_message)

        behavior: Optional[str] = updated_agent_config.get("behavior", None)
        if behavior:
            writes["behavior"] = partial(
                self.shared_state.update_agent_behavior, behavior
            )

        updated_activity_goal: Any = updated_agent_config.get(ACTIVITY_GOAL_FIELD)
        if FieldsThatCanBeRemoved.ACTIVITY_GOAL.value in removed_fields:
            updated_params.update({ACTIVITY_GOAL_FIELD: None})
            writes[ACTIVITY_GOAL_FIELD] = partial(self._store_activity_goal, None)
        elif updated_activity_goal is not None:
            if not is_valid_activity_goal(updated_activity_goal):
                issue_message = (
                    f"Activity goal {updated_activity_goal!r} is not valid. It must "
                    "be a whole number of trades per staking epoch, 0 or more. "
                    "No changes were made."
                )
                self.context.logger.info(
                    f"Declined activity goal change: {issue_message}"
                )
                issues.append(issue_message)
                # The goal decides when the agent stops trading, so a reply that
                # misreads it is declined as a whole rather than half-applied.
                return {}, issues, {}
            updated_params.update({ACTIVITY_GOAL_FIELD: updated_activity_goal})
            writes[ACTIVITY_GOAL_FIELD] = partial(
                self._store_activity_goal, updated_activity_goal
            )

        # Nothing above wrote anything, so reaching here means every field
        # was readable and the update can be applied as a whole.
        return updated_params, issues, writes

    def _apply_config_writes(
        self, writes: Dict[str, Callable[[], None]]
    ) -> Tuple[List[str], List[str]]:
        """Apply a planned update's writes.

        :param writes: the writes by setting, in order.
        :return: the settings written, and the issue to tell the user if a
            write failed, else nothing.
        """
        written: List[str] = []
        try:
            for setting, write in writes.items():
                write()
                written.append(setting)
        except OSError as e:
            # Raised past here, the caller would report an unreadable reply
            # while the writes before this one stay applied.
            self.context.logger.error(f"Could not save the config update: {e}")
            return written, [
                "Some of your changes could not be saved. "
                "Please check your settings and try again."
            ]
        return written, []

    # Fields the update would misread rather than reject if the type is
    # wrong, so a broad guard around the update cannot see them. A string
    # in ``removed_config_fields`` satisfies the membership test by
    # substring and silently clears that setting; a string in the list
    # fields is iterated character by character. Both look like success.
    _LLM_CONFIG_FIELD_TYPES: Dict[str, type] = {
        TRADING_STRATEGY_FIELD: str,
        ALLOWED_TOOLS_FIELD: list,
        SELECTED_MECHS_FIELD: list,
        REMOVED_CONFIG_FIELDS_FIELD: list,
        "behavior": str,
    }
    # Scaled by the token decimals and then range-checked, so a bool passes
    # as one unit of the collateral and an infinity or a NaN passes the
    # comparison. Checked as finite numbers that are not bools.
    _LLM_CONFIG_NUMERIC_FIELDS = ("fixed_bet_size", "max_bet_size")

    @classmethod
    def _config_update_is_readable(cls, config: Any) -> bool:
        """Return whether a config update can be read as intended.

        :param config: the ``updated_agent_config`` value from the reply.
        :return: whether every field set is the type the update expects.

        Only the fields whose wrong type would pass silently. Everything
        else that a wrong shape can do raises, and is caught at the call.
        """
        if not isinstance(config, dict):
            return False
        if not all(
            isinstance(config[field], expected)
            for field, expected in cls._LLM_CONFIG_FIELD_TYPES.items()
            if config.get(field) is not None
        ):
            return False
        return all(
            cls._is_finite_number(config[field])
            for field in cls._LLM_CONFIG_NUMERIC_FIELDS
            if config.get(field) is not None
        )

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        """Return whether ``value`` is a real, finite number and not a bool.

        :param value: the value from the reply.
        :return: whether it can be scaled and compared as an amount.

        ``True`` is an ``int`` in Python, so a bool would otherwise read as
        one unit of the collateral, and an infinity or a NaN would pass a
        range check without ever being a meaningful amount.

        Every ``int`` is finite by construction. ``math.isfinite`` converts
        its argument to a float first, so an int of about 309 digits or more
        raises rather than answering, and this guard runs ahead of the
        handler's own catch.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return isinstance(value, int) or math.isfinite(value)

    def _handle_unreadable_llm_reply(
        self, reply: Any, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Answer the caller when the model did not reply with the JSON object asked for.

        :param reply: whatever the model sent back.
        :param http_msg: the original HttpMessage.
        :param http_dialogue: the original HttpDialogue.

        The prompt asks for a JSON object but nothing makes the model
        return one, so prose, a fenced block or an apology all land here.
        Left to raise this ends the agent, because the service runs under
        ``stop_and_exit``: one badly answered prompt would stop trading.
        """
        self.context.logger.error(
            f"Could not read the LLM reply as a JSON object: {reply!r}"
        )
        self._send_internal_server_error_response(
            http_msg,
            http_dialogue,
            {"error": "The model did not answer in the expected format."},
            content_type=HttpContentType.JSON.header,
        )

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

    def _handle_mech_deposit_required(
        self, genai_response: dict, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Explain an unfunded deposit; ask for funds only when the EOA is known short."""
        native_token = "POL" if self.context.params.is_running_on_polymarket else "xDAI"
        # The balances tell an empty deposit from one that is below what this
        # call needs, or held up by requests still in flight.
        self.context.logger.warning(
            f"Chat request refused for want of a mech pre-deposit: "
            f"{genai_response.get('error')} (context: {genai_response.get('context')})"
        )
        if self.context.shared_state.get(MECH_PRE_DEPOSIT_EOA_SHORT, False):
            message = (
                "Chat needs a small prepaid balance that your agent couldn't "
                f"fund. Add {native_token} to your agent in Pearl, then try "
                "again in a few minutes."
            )
        else:
            message = (
                "Chat is temporarily unavailable while your agent tops up its "
                "prepaid balance. Please try again in a minute."
            )
        self._send_http_response(
            http_msg,
            http_dialogue,
            {"error": message},
            HTTPStatus.PAYMENT_REQUIRED.value,
            HTTPStatus.PAYMENT_REQUIRED.phrase,
            HttpContentType.JSON.header,
        )

    def _set_chatui_param(self, param_name: str, value: Any) -> None:
        """Set one chat-ui config value and persist it.

        :param param_name: the config attribute to set.
        :param value: the value to store.
        """
        setattr(self.shared_state.chatui_config, param_name, value)
        self._store_chatui_param_to_json(param_name, value)

    def _store_chatui_param_to_json(self, param_name: str, value: Any) -> None:
        """Store chatui param to json."""

        current_store: dict = self.shared_state._get_current_json_store()
        current_store.update({param_name: value})
        self.shared_state._set_json_store(current_store)

    def _store_activity_goal(self, goal: Optional[int]) -> None:
        """Store the user's activity goal and show it to Pearl at once.

        :param goal: the new goal, or ``None`` to revert to the default.
        """
        previous = self.shared_state.chatui_config.activity_goal
        self._set_chatui_param(ACTIVITY_GOAL_FIELD, goal)
        default_goal = self.context.params.default_activity_goal
        self.context.logger.info(
            f"Activity goal changed from {previous} to {goal} "
            f"(None is the default, {default_goal})."
        )

        # Must not fail the reply; the next evaluation rebuilds the block.
        try:
            retarget_activity_goal(
                self.context.params.store_path,
                effective_activity_goal(goal, default_goal),
                self.shared_state.synced_timestamp,
            )
        except OSError as e:
            self.context.logger.error(
                f"Could not publish the new activity goal to Pearl: {e}"
            )

    def _store_trading_strategy(self, trading_strategy: str) -> None:
        """Store the trading strategy."""
        self.shared_state.chatui_config.trading_strategy = trading_strategy
        self._store_chatui_param_to_json(TRADING_STRATEGY_FIELD, trading_strategy)

    def _store_allowed_tools(self, tools: Optional[List[str]] = None) -> None:
        """Store the allowed tools list."""
        self.shared_state.chatui_config.allowed_tools = tools
        self._store_chatui_param_to_json(ALLOWED_TOOLS_FIELD, tools)

    def _store_selected_mechs(self, mechs: Optional[List[str]] = None) -> None:
        """Store the ChatUI-pinned mech addresses."""
        self.shared_state.chatui_config.selected_mechs = mechs
        self._store_chatui_param_to_json(SELECTED_MECHS_FIELD, mechs)

    def _build_withdrawal_status(self) -> Dict[str, Any]:
        """Return the GET payload describing current withdrawal state.

        Reads from disk rather than the in-memory ``chatui_config`` cache:
        the withdrawal fields are written by ``decision_maker_abci`` directly
        to ``chatui_param_store.json`` and never propagated back into this
        skill's in-memory cfg. Reading disk on every GET keeps the FE
        polling loop in lock-step with the behaviour-side state machine.

        :return: payload dict matching the documented withdrawal-status shape.
        """
        store = self.shared_state._get_current_json_store()
        fills = store.get("withdrawal_fills", []) or []
        errors = store.get("withdrawal_errors", []) or []
        venue = "polymarket" if self.context.params.is_running_on_polymarket else "omen"
        return {
            "mode": store.get("withdrawal_state", WITHDRAWAL_STATE_IDLE),
            "venue": venue,
            "positions_total": len(fills) + len(errors),
            "positions_sold": len(fills),
            "positions_stuck": len(errors),
            "fills": fills,
            "errors": errors,
        }

    def _handle_post_withdrawal(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle POST /api/v1/withdrawal — arm withdrawal mode (idempotent)."""
        cfg = self.shared_state.chatui_config
        if cfg.withdrawal_state == WITHDRAWAL_STATE_IDLE:
            cfg.withdrawal_mode = True
            cfg.withdrawal_state = WITHDRAWAL_STATE_ARMED
            cfg.withdrawal_fills = []
            cfg.withdrawal_errors = []
            self._store_chatui_param_to_json("withdrawal_mode", True)
            self._store_chatui_param_to_json("withdrawal_state", WITHDRAWAL_STATE_ARMED)
            self._store_chatui_param_to_json("withdrawal_fills", [])
            self._store_chatui_param_to_json("withdrawal_errors", [])
        self._send_ok_response(http_msg, http_dialogue, self._build_withdrawal_status())

    def _handle_get_withdrawal(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/withdrawal — return current status."""
        self._send_ok_response(http_msg, http_dialogue, self._build_withdrawal_status())


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
