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

"""Tests for the chat on the agent's main page: ``POST /api/v1/chat``."""

import json
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.feed import (
    EventType,
    FEED_FILE,
    append_event,
    append_message,
    field,
)
from packages.valory.skills.chatui_abci import handlers as handlers_module
from packages.valory.skills.chatui_abci.handlers import (
    CHANGE_NOT_APPLIED,
    CHAT_SAVE_FAILED,
    GENAI_RATE_LIMIT_ERROR,
    HttpHandler,
    INVALID_CHAT_REQUEST,
    MECH_DEPOSIT_REQUIRED_CODE,
    MECH_PRE_DEPOSIT_EOA_SHORT,
    STILL_ANSWERING,
)
from packages.valory.skills.chatui_abci.models import (
    ChatTurn,
    ChatuiConfig,
    ConfigChange,
    ConfigProposal,
    SharedState,
)

DECIMALS = 18
ABS_MIN = 10**16  # 0.01 xDAI
ABS_MAX = 2 * 10**18  # 2 xDAI
CLIENT_ID = "c-1"


class _TestableHttpHandler(HttpHandler):
    """Shadows read-only AEA properties with plain attributes; responses stay real."""

    context: Any = None  # type: ignore[assignment]
    shared_state: Any = None  # type: ignore[assignment]
    synchronized_data: Any = None  # type: ignore[assignment]


class _Chat:
    """A handler wired to a feed under ``store_path`` and a scripted model."""

    def __init__(self, store_path: Path, config: Optional[ChatuiConfig] = None):
        """Build the handler."""
        handler = object.__new__(_TestableHttpHandler)
        context = MagicMock()
        context.params.store_path = store_path
        context.params.is_running_on_polymarket = False
        context.params.valid_mechs = frozenset({"0x" + "a" * 40})
        context.params.default_activity_goal = 10
        context.params.strategies_kwargs = {
            "absolute_min_bet_size": ABS_MIN,
            "absolute_max_bet_size": ABS_MAX,
        }
        context.shared_state = {}
        handler.context = context
        handler._chat_turns = {}

        state = MagicMock()
        state.chatui_config = config or ChatuiConfig(
            trading_strategy="kelly_criterion", max_bet_size=10**18
        )
        state._answering_since = {}
        state.config_proposal = None
        state.approved_mechs = []
        state.approved_mech_rates = {}
        state.available_prediction_tools = frozenset({"tool-a", "tool-b"})
        state.read_activity_goal_from_disk.return_value = None
        for name in (
            "is_answering",
            "start_answering",
            "finish_answering",
            "take_config_proposal",
        ):
            setattr(state, name, MethodType(getattr(SharedState, name), state))
        handler.shared_state = state

        sync = MagicMock()
        sync.available_valid_mechs = {"0x" + "a" * 40}
        handler.synchronized_data = sync

        self.handler = handler
        self.store_path = store_path
        self.llm_calls: List[Tuple[str, Any, Dict[str, Any]]] = []
        handler._send_llm_request = self._capture  # type: ignore[method-assign, assignment]

    def _capture(self, prompt: str, _schema: Any, callback: Any, kwargs: Any) -> None:
        """Keep the model request; the test answers it."""
        self.llm_calls.append((prompt, callback, kwargs))

    def send(self, text: Any = "hello", client_id: Any = CLIENT_ID) -> MagicMock:
        """POST a chat message and return its dialogue."""
        http_msg = MagicMock(headers="", version="")
        http_msg.body = json.dumps({"text": text, "client_id": client_id}).encode()
        return self.post(http_msg)

    def post(self, http_msg: MagicMock) -> MagicMock:
        """POST a raw request and return its dialogue."""
        http_dialogue = MagicMock()
        http_dialogue.dialogue_label = object()
        self.handler._handle_chat(http_msg, http_dialogue)
        return http_dialogue

    def answer(self, payload: Dict[str, Any], call: int = -1) -> None:
        """Answer a pending model request with the connection's payload."""
        _, callback, kwargs = self.llm_calls[call]
        callback(SimpleNamespace(payload=json.dumps(payload)), MagicMock(), **kwargs)

    def reply(
        self, message: str, config: Optional[Dict[str, Any]] = None, call: int = -1
    ) -> None:
        """Answer a pending model request with a chat reply."""
        body = {"message": message, "updated_agent_config": config or {}}
        self.answer({"response": json.dumps(body)}, call)

    def confirm(self, confirmed: bool, call: int = -1) -> None:
        """Answer a pending confirmation request."""
        self.answer({"response": json.dumps({"confirmed": confirmed})}, call)

    @staticmethod
    def response(http_dialogue: MagicMock) -> Tuple[int, Any]:
        """Return the status and body sent on a dialogue."""
        kwargs = http_dialogue.reply.call_args.kwargs
        return kwargs["status_code"], json.loads(kwargs["body"])

    def feed(self) -> List[Dict[str, Any]]:
        """Return the feed's lines."""
        path = self.store_path / FEED_FILE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def chat(tmp_path: Path) -> _Chat:
    """A chat with an empty feed."""
    return _Chat(tmp_path)


class TestRoute:
    """The chat request and its replies."""

    def test_a_new_handler_answers_no_chat_yet(self) -> None:
        """The chat requests in flight are the handler's own, and start empty."""
        handler = HttpHandler(name="http", skill_context=MagicMock())
        assert handler._chat_turns == {}

    def test_answer_writes_both_lines_and_returns_them(self, chat: _Chat) -> None:
        """The message is written on arrival and the reply with its client id."""
        dialogue = chat.send("What can you do?")
        assert [line["role"] for line in chat.feed()] == ["user"]

        chat.reply("I trade for you.")

        status, body = chat.response(dialogue)
        message, reply = chat.feed()
        assert status == 200
        assert body == {"message": message, "reply": reply}
        assert message["text"] == "What can you do?"
        assert message["client_id"] == CLIENT_ID
        assert reply["role"] == "agent"
        assert reply["text"] == "I trade for you."
        assert reply["client_id"] == CLIENT_ID
        assert not chat.handler.shared_state.is_answering(CLIENT_ID)

    def test_prompt_includes_recent_activity(self, chat: _Chat) -> None:
        """The chat prompt lists the latest feed entries but not the message itself."""
        append_event(
            chat.store_path,
            EventType.TRADE_PLACED,
            [field("Market", "Will it rain?"), field("Amount", "1.00 xDAI")],
            ts=1791763200,
        )
        chat.send("Why did you place your last trade?")

        prompt = chat.llm_calls[0][0]
        assert (
            "- 2026-10-12 00:00 UTC Placed a trade: Market: Will it rain?; "
            "Amount: 1.00 xDAI"
        ) in prompt
        assert "User: Why did you place" not in prompt
        assert 'User prompt: "Why did you place your last trade?"' in prompt
        assert "describe any change as a proposal" in prompt

    def test_answered_resend_replays_the_lines(self, chat: _Chat) -> None:
        """A resend of an answered message gets its lines, with no new answer."""
        first = chat.send()
        chat.reply("Hi.")
        _, answered = chat.response(first)

        resend = chat.send()

        assert chat.response(resend) == (200, answered)
        assert len(chat.llm_calls) == 1
        assert len(chat.feed()) == 2

    def test_resend_while_answering_is_409(self, chat: _Chat) -> None:
        """A resend of a message still being answered is refused, and not written."""
        chat.send()

        resend = chat.send()

        assert chat.response(resend) == (409, {"error": STILL_ANSWERING})
        assert len(chat.feed()) == 1
        assert len(chat.llm_calls) == 1

    def test_a_stuck_answer_stops_blocking_the_resend(self, chat: _Chat) -> None:
        """An answer that never came back does not block its resend forever."""
        chat.send()
        chat.handler.shared_state._answering_since[CLIENT_ID] -= 10_000

        chat.send()

        assert len(chat.llm_calls) == 2

    def test_a_stuck_answer_and_its_resend_write_one_reply(self, chat: _Chat) -> None:
        """When both answers come back, the second returns the reply already written."""
        first = chat.send()
        chat.handler.shared_state._answering_since[CLIENT_ID] -= 10_000
        resend = chat.send()

        chat.reply("First.", call=0)
        chat.reply("Second.", call=1)

        message, reply = chat.feed()
        assert reply["text"] == "First."
        assert chat.response(first) == (200, {"message": message, "reply": reply})
        assert chat.response(resend) == (200, {"message": message, "reply": reply})

    def test_resend_after_a_failure_is_answered_without_a_second_line(
        self, chat: _Chat
    ) -> None:
        """A failed answer is not written; its resend is answered as new, written once."""
        failed = chat.send()
        chat.answer({"error": "boom"})
        assert chat.response(failed)[0] == 500
        assert [line["role"] for line in chat.feed()] == ["user"]

        resend = chat.send()
        chat.reply("Second try.")

        assert chat.response(resend)[0] == 200
        assert [line["role"] for line in chat.feed()] == ["user", "agent"]

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"\xff",
            b"[]",
            json.dumps({"client_id": CLIENT_ID}).encode(),
            json.dumps({"text": "  ", "client_id": CLIENT_ID}).encode(),
            json.dumps({"text": "hi"}).encode(),
            json.dumps({"text": "hi", "client_id": 7}).encode(),
        ],
    )
    def test_a_malformed_request_is_400(self, chat: _Chat, body: bytes) -> None:
        """A body without both a text and a client id is refused and not written."""
        http_msg = MagicMock(headers="", version="", body=body)

        dialogue = chat.post(http_msg)

        assert chat.response(dialogue) == (400, {"error": INVALID_CHAT_REQUEST})
        assert chat.feed() == []

    def test_unwritable_feed_is_500(self, tmp_path: Path) -> None:
        """A message that cannot be written is not answered."""
        chat = _Chat(tmp_path / "missing")

        dialogue = chat.send()

        assert chat.response(dialogue) == (500, {"error": CHAT_SAVE_FAILED})
        assert chat.llm_calls == []

    def test_unwritable_reply_is_500(self, chat: _Chat) -> None:
        """A reply that cannot be written is a failed answer."""
        dialogue = chat.send()
        with patch.object(handlers_module, "append_message", side_effect=OSError):
            chat.reply("Hi.")

        assert chat.response(dialogue) == (500, {"error": CHAT_SAVE_FAILED})
        assert not chat.handler.shared_state.is_answering(CLIENT_ID)


class TestErrorStatuses:
    """The chat's statuses for a failed answer."""

    def test_no_funds_is_402_only_when_the_user_must_add_funds(
        self, chat: _Chat
    ) -> None:
        """The mech pre-deposit refusal asks for funds when the EOA is short."""
        chat.handler.context.shared_state = {MECH_PRE_DEPOSIT_EOA_SHORT: True}
        dialogue = chat.send()
        chat.answer({"error": "deposit", "code": MECH_DEPOSIT_REQUIRED_CODE})

        status, body = chat.response(dialogue)
        assert status == 402
        assert "Add xDAI to your agent" in body["error"]

    def test_topping_up_is_503(self, chat: _Chat) -> None:
        """While the agent tops up its own deposit the chat is temporarily unavailable."""
        dialogue = chat.send()
        chat.answer({"error": "deposit", "code": MECH_DEPOSIT_REQUIRED_CODE})

        status, body = chat.response(dialogue)
        assert status == 503
        assert "temporarily unavailable" in body["error"]

    def test_not_started_is_503(self, chat: _Chat) -> None:
        """Before the skill has its tools the chat is initializing."""
        chat.handler._available_tools = MagicMock(side_effect=TypeError)  # type: ignore[method-assign]

        dialogue = chat.send()

        assert chat.response(dialogue)[0] == 503

    def test_rate_limit_is_429(self, chat: _Chat) -> None:
        """The model's rate limit passes through."""
        dialogue = chat.send()
        chat.answer({"error": f"{GENAI_RATE_LIMIT_ERROR} slow down"})

        assert chat.response(dialogue) == (
            429,
            {"error": "Too many requests to the LLM."},
        )

    def test_unreadable_reply_is_500(self, chat: _Chat) -> None:
        """A reply that is not the JSON asked for is a server error."""
        dialogue = chat.send()
        chat.answer({"response": "not json"})

        assert chat.response(dialogue)[0] == 500

    def test_error_without_a_message_uses_the_status_text(self, chat: _Chat) -> None:
        """An error body without text still answers with an ``error``."""
        dialogue = MagicMock()
        dialogue.dialogue_label = "label"
        chat.handler._chat_turns["label"] = ChatTurn(CLIENT_ID, {"id": 1})

        chat.handler._send_http_response(
            MagicMock(headers="", version=""), dialogue, "oops", 400, "Bad Request"
        )

        assert chat.response(dialogue) == (400, {"error": "Bad Request"})


class TestMechCommands:
    """Typed mech commands answer in the chat and record what they change."""

    def test_pin_and_unpin_record_the_change(self, chat: _Chat) -> None:
        """Pinning and unpinning apply at once and each writes a card."""
        mech = "0x" + "a" * 40
        chat.handler._store_selected_mechs = MagicMock()  # type: ignore[method-assign]

        pinned = chat.send(f"pin {mech}", "c-pin")
        chat.handler.shared_state.chatui_config.selected_mechs = [mech]
        chat.send(f"unpin {mech}", "c-unpin")

        assert chat.response(pinned)[0] == 200
        events = [line for line in chat.feed() if line["kind"] == "event"]
        assert [event["fields"] for event in events] == [
            [
                {"label": "Setting", "value": "Pinned mechs"},
                {"label": "Before", "value": "All mechs"},
                {"label": "After", "value": mech},
            ],
            [
                {"label": "Setting", "value": "Pinned mechs"},
                {"label": "Before", "value": mech},
                {"label": "After", "value": "All mechs"},
            ],
        ]
        assert chat.llm_calls == []

    def test_removing_a_pinned_mech_records_the_unpin(self, chat: _Chat) -> None:
        """Removing an approved mech that is pinned writes the pin change."""
        mech = "0x" + "b" * 40
        chat.handler._store_selected_mechs = MagicMock()  # type: ignore[method-assign]
        chat.handler.shared_state.approved_mechs = [mech]
        chat.handler.shared_state.approved_mech_rates = {mech: 1}
        chat.handler.shared_state.chatui_config.selected_mechs = [mech.upper()]

        chat.send(f"remove {mech}", "c-remove")

        events = [line for line in chat.feed() if line["kind"] == "event"]
        assert [event["fields"] for event in events] == [
            [
                {"label": "Setting", "value": "Pinned mechs"},
                {"label": "Before", "value": mech},
                {"label": "After", "value": "All mechs"},
            ],
        ]


class TestConfirmFlow:
    """A config change from the chat is applied only after a typed confirm."""

    @staticmethod
    def _propose(chat: _Chat, config: Dict[str, Any]) -> MagicMock:
        """Ask for a change and let the model propose ``config``."""
        dialogue = chat.send("Set my max trade size to 1.5", "c-ask")
        chat.reply("I can raise your max trade size to 1.5 xDAI.", config)
        return dialogue

    def test_a_change_is_proposed_not_applied(self, chat: _Chat) -> None:
        """The proposal is stated in the reply and kept; nothing is applied or written."""
        dialogue = self._propose(chat, {"max_bet_size": 1.5})

        status, body = chat.response(dialogue)
        assert status == 200
        assert body["reply"]["text"] == (
            "I can raise your max trade size to 1.5 xDAI.<br><br><b>To confirm:</b> "
            "change Max trade size from 1.00 xDAI to 1.50 xDAI. Reply yes to apply "
            "it, or anything else to keep your settings."
        )
        assert chat.handler.shared_state.chatui_config.max_bet_size == 10**18
        assert chat.handler.shared_state.config_proposal == ConfigProposal(
            config={"max_bet_size": 1.5},
            changes=[ConfigChange("Max trade size", "1.00 xDAI", "1.50 xDAI")],
        )
        assert [line["kind"] for line in chat.feed()] == ["message", "message"]

    def test_yes_applies_records_and_acknowledges(self, chat: _Chat) -> None:
        """A confirming reply applies the change, writes its card and acknowledges."""
        self._propose(chat, {"max_bet_size": 1.5})

        dialogue = chat.send("Yes, please", "c-yes")
        prompt = chat.llm_calls[-1][0]
        assert "Change Max trade size from 1.00 xDAI to 1.50 xDAI." in prompt
        assert 'The user replied: "Yes, please"' in prompt
        chat.confirm(True)

        status, body = chat.response(dialogue)
        assert status == 200
        assert body["reply"]["text"] == (
            "Done. I changed Max trade size from 1.00 xDAI to 1.50 xDAI."
        )
        assert chat.handler.shared_state.chatui_config.max_bet_size == 15 * 10**17
        assert chat.handler.shared_state.config_proposal is None
        events = [line for line in chat.feed() if line["kind"] == "event"]
        assert len(events) == 1
        assert events[0]["type"] == "config_changed"
        assert events[0]["title"] == "Changed the configuration"
        assert events[0]["fields"] == [
            {"label": "Setting", "value": "Max trade size"},
            {"label": "Before", "value": "1.00 xDAI"},
            {"label": "After", "value": "1.50 xDAI"},
        ]
        # The card comes before the acknowledgement that says it was applied.
        assert [line["kind"] for line in chat.feed()][-2:] == ["event", "message"]

    @pytest.mark.parametrize("text", ["No, keep it", "How are my trades doing?"])
    def test_anything_else_drops_it_and_answers_normally(
        self, chat: _Chat, text: str
    ) -> None:
        """A refusal or another message drops the proposal and gets a normal answer."""
        self._propose(chat, {"max_bet_size": 1.5})

        dialogue = chat.send(text, "c-other")
        chat.confirm(False)
        assert chat.handler.shared_state.config_proposal is None
        chat.reply("Fine, nothing changed.")

        assert chat.response(dialogue)[1]["reply"]["text"] == "Fine, nothing changed."
        assert f'User prompt: "{text}"' in chat.llm_calls[-1][0]
        assert chat.handler.shared_state.chatui_config.max_bet_size == 10**18
        assert all(line["kind"] == "message" for line in chat.feed())

    def test_the_proposal_gets_only_the_next_message(self, chat: _Chat) -> None:
        """After one reply the proposal is gone, so a later yes is a new message."""
        self._propose(chat, {"max_bet_size": 1.5})
        chat.send("no", "c-no")
        chat.confirm(False)
        chat.reply("OK.")

        chat.send("yes", "c-late")

        assert "Decide whether the reply confirms" not in chat.llm_calls[-1][0]

    @pytest.mark.parametrize(
        "payload",
        [
            "garbage",
            json.dumps({"response": "not json"}),
            json.dumps({"response": json.dumps(["yes"])}),
            json.dumps({"response": json.dumps({"confirmed": "yes"})}),
        ],
    )
    def test_an_unreadable_confirmation_keeps_the_proposal_for_the_resend(
        self, chat: _Chat, payload: str
    ) -> None:
        """An unreadable confirmation is a 500, and the resend of the message decides."""
        self._propose(chat, {"max_bet_size": 1.5})
        failed = chat.send("yes", "c-yes")
        _, callback, kwargs = chat.llm_calls[-1]
        callback(SimpleNamespace(payload=payload), MagicMock(), **kwargs)

        assert chat.response(failed)[0] == 500
        assert chat.handler.shared_state.chatui_config.max_bet_size == 10**18

        chat.send("yes", "c-yes")
        assert "Decide whether the reply confirms" in chat.llm_calls[-1][0]
        chat.confirm(True)

        assert chat.handler.shared_state.chatui_config.max_bet_size == 15 * 10**17

    def test_a_failed_confirmation_keeps_the_proposal_for_the_resend(
        self, chat: _Chat
    ) -> None:
        """If the confirmation cannot be read, the resend of the same message decides."""
        self._propose(chat, {"max_bet_size": 1.5})
        failed = chat.send("yes", "c-yes")
        chat.answer({"error": f"{GENAI_RATE_LIMIT_ERROR}"})
        assert chat.response(failed)[0] == 429

        chat.send("yes", "c-yes")
        chat.confirm(True)

        assert chat.handler.shared_state.chatui_config.max_bet_size == 15 * 10**17
        assert [line["role"] for line in chat.feed() if line["kind"] == "message"] == [
            "user",
            "agent",
            "user",
            "agent",
        ]

    def test_an_out_of_range_value_is_refused_when_proposed(self, chat: _Chat) -> None:
        """A value outside the bounds is refused at once, with nothing to confirm."""
        dialogue = self._propose(chat, {"max_bet_size": 100})

        text = chat.response(dialogue)[1]["reply"]["text"]
        assert (
            text
            == "Max bet size 100 is out of bounds. It must be between 0.01 and 2.0."
        )
        assert chat.handler.shared_state.config_proposal is None

    def test_an_invalid_activity_target_is_refused_when_proposed(
        self, chat: _Chat
    ) -> None:
        """A goal that is not a whole number of trades is refused."""
        dialogue = self._propose(chat, {"activity_goal": -1})

        assert "is not valid" in chat.response(dialogue)[1]["reply"]["text"]
        assert chat.handler.shared_state.config_proposal is None

    def test_a_change_to_the_current_value_is_not_proposed(self, chat: _Chat) -> None:
        """Nothing changes, so there is nothing to confirm."""
        dialogue = self._propose(chat, {"max_bet_size": 1})

        assert chat.response(dialogue)[1]["reply"]["text"] == (
            "I can raise your max trade size to 1.5 xDAI."
        )
        assert chat.handler.shared_state.config_proposal is None

    def test_a_proposal_without_a_message_still_asks(self, chat: _Chat) -> None:
        """The confirm question stands on its own when the model wrote nothing."""
        dialogue = chat.send("Raise it", "c-ask")
        chat.reply("", {"max_bet_size": 1.5})

        assert chat.response(dialogue)[1]["reply"]["text"].startswith(
            "<b>To confirm:</b>"
        )

    def test_an_unusable_proposal_is_an_unreadable_reply(self, chat: _Chat) -> None:
        """A change the update cannot read is answered as an unreadable reply."""
        chat.handler._plan_config_update = MagicMock(side_effect=KeyError)  # type: ignore[method-assign]

        dialogue = self._propose(chat, {"max_bet_size": 1.5})

        assert chat.response(dialogue)[0] == 500

    def test_a_change_that_no_longer_plans_is_not_applied(self, chat: _Chat) -> None:
        """If the confirmed change now fails, the agent explains and writes no card."""
        self._propose(chat, {"allowed_tools": ["tool-a"]})
        chat.handler.shared_state.available_prediction_tools = frozenset({"tool-b"})

        dialogue = chat.send("yes", "c-yes")
        chat.confirm(True)

        assert "Unknown tool(s) ignored" in chat.response(dialogue)[1]["reply"]["text"]
        assert all(line["kind"] == "message" for line in chat.feed())

    def test_a_change_that_cannot_be_read_again_is_not_applied(
        self, chat: _Chat
    ) -> None:
        """A plan that raises on confirm is explained, not raised."""
        self._propose(chat, {"max_bet_size": 1.5})
        chat.handler._plan_config_update = MagicMock(side_effect=KeyError)  # type: ignore[method-assign]

        dialogue = chat.send("yes", "c-yes")
        chat.confirm(True)

        assert chat.response(dialogue)[1]["reply"]["text"] == CHANGE_NOT_APPLIED

    def test_a_change_that_cannot_be_saved_writes_no_card(self, chat: _Chat) -> None:
        """A failed write is explained instead of recorded."""
        self._propose(chat, {"max_bet_size": 1.5})
        chat.handler._store_chatui_param_to_json = MagicMock(side_effect=OSError)  # type: ignore[method-assign]

        dialogue = chat.send("yes", "c-yes")
        chat.confirm(True)

        assert "could not be saved" in chat.response(dialogue)[1]["reply"]["text"]
        assert all(line["kind"] == "message" for line in chat.feed())

    def test_a_confirmed_change_already_in_place_writes_no_card(
        self, chat: _Chat
    ) -> None:
        """A change applied meanwhile by other means is acknowledged without a card."""
        self._propose(chat, {"max_bet_size": 1.5})
        chat.handler.shared_state.chatui_config.max_bet_size = 15 * 10**17

        dialogue = chat.send("yes", "c-yes")
        chat.confirm(True)

        assert chat.response(dialogue)[1]["reply"]["text"] == (
            "Done. Your settings already had that value."
        )
        assert all(line["kind"] == "message" for line in chat.feed())


class TestDescribeChanges:
    """How each setting is shown before and after a change."""

    def test_every_setting(self, tmp_path: Path) -> None:
        """Each setting is named and its values shown as the user reads them."""
        chat = _Chat(
            tmp_path,
            ChatuiConfig(
                trading_strategy="fixed_bet",
                allowed_tools=None,
                selected_mechs=["0xm1"],
                fixed_bet_size=None,
                max_bet_size=2 * 10**17,
                activity_goal=None,
            ),
        )

        changes = chat.handler._describe_changes(
            {
                "trading_strategy": "kelly_criterion",
                "allowed_tools": ["tool-a", "tool-b"],
                "selected_mechs": None,
                "fixed_bet_size": 0.5,
                "max_bet_size": None,
                "activity_goal": 4,
            }
        )

        assert changes == [
            ConfigChange("Trading strategy", "Balanced", "Risky"),
            ConfigChange("Allowed tools", "All tools", "tool-a, tool-b"),
            ConfigChange("Pinned mechs", "0xm1", "All mechs"),
            ConfigChange("Fixed trade size", "Default", "0.50 xDAI"),
            ConfigChange("Max trade size", "0.20 xDAI", "Default"),
            ConfigChange(
                "Daily activity target",
                "10 trades per day (default)",
                "4 trades per day",
            ),
        ]


class TestRecentActivity:
    """The feed entries the chat prompt shows."""

    def test_entries_are_described_oldest_first(self, chat: _Chat) -> None:
        """Events list their fields; messages their speaker and text."""
        append_message(chat.store_path, "user", "hi", "c-0", ts=1791763200)
        append_message(chat.store_path, "agent", "x" * 400, "c-0", ts=1791763260)
        current = append_message(chat.store_path, "user", "now", CLIENT_ID)

        text = chat.handler._recent_activity(ChatTurn(CLIENT_ID, current))

        assert text.splitlines() == [
            "- 2026-10-12 00:00 UTC User: hi",
            "- 2026-10-12 00:01 UTC Agent: " + "x" * 300,
        ]

    def test_empty_feed(self, chat: _Chat) -> None:
        """Without entries the prompt says so."""
        text = chat.handler._recent_activity(ChatTurn(CLIENT_ID, {"id": 1}))
        assert text == "(no activity yet)"

    def test_unreadable_feed(self, chat: _Chat) -> None:
        """A feed that cannot be read does not stop the answer."""
        with patch.object(handlers_module, "read_recent", side_effect=OSError):
            text = chat.handler._recent_activity(ChatTurn(CLIENT_ID, {"id": 1}))
        assert text == "(not available)"

    @pytest.mark.parametrize(
        "entry, expected",
        [
            (
                {
                    "kind": "event",
                    "title": "T",
                    "fields": [{"label": "a", "value": "b"}, "x"],
                },
                "- unknown time T: a: b",
            ),
            (
                {"kind": "event", "ts": "bad", "title": "T", "fields": None},
                "- unknown time T: ",
            ),
            (
                {"kind": "message", "role": "agent", "ts": 10**20},
                "- unknown time Agent: ",
            ),
        ],
    )
    def test_malformed_entries_still_describe(
        self, entry: Dict[str, Any], expected: str
    ) -> None:
        """An entry with odd fields is described as far as it can be."""
        assert HttpHandler._describe_feed_entry(entry) == expected
