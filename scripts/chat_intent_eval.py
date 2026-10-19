#!/usr/bin/env python3
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

"""Check which mech intent the real chat model reads from sample messages.

Run by hand, not in CI: every case is one paid call to the Gemini API.

Each case fills ``CHATUI_PROMPT`` the way the chat handler fills it, with a
fixed sample config, and sends it to the model and response schema the genai
connection uses. It prints, per case, the expected and the returned
``mech_intent``, the mech the handler resolves it to, and what the handler
would do with the reply.

The call is the REST ``generateContent`` request of the connection's paid
path; the connection's direct path sends the same prompt and schema through
the ``google-generativeai`` SDK.

Usage, from the repository root::

    GENAI_API_KEY=<key> uv run python scripts/chat_intent_eval.py
    GENAI_API_KEY=<key> uv run python scripts/chat_intent_eval.py \
        --case yes_after_report --repeat 5 --model gemini-2.5-pro

It exits with 1 when any returned intent is not one the case expects.
"""

import argparse
import json
import os
import re
import pickle  # nosec
import sys
import time
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

import requests

# The chat skill is imported from this checkout, ahead of any installed copy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# pylint: disable=wrong-import-position
from packages.valory.connections.genai.connection import (  # noqa: E402
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
)
from packages.valory.connections.genai.utils import (  # noqa: E402
    pydantic_to_gemini_schema,
)
from packages.valory.skills.chatui_abci.handlers import HttpHandler  # noqa: E402
from packages.valory.skills.chatui_abci.mech_commands import (  # noqa: E402
    resolve_intent,
)
from packages.valory.skills.chatui_abci.models import ChatuiConfig  # noqa: E402
from packages.valory.skills.chatui_abci.prompts import (  # noqa: E402
    CHATUI_PROMPT,
    MechIntent,
    build_chatui_llm_response_schema,
)

API_KEY_ENV = "GENAI_API_KEY"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# A busy or rate-limited model is retried this many times, waiting longer each time.
RETRY_STATUSES = frozenset({429, 500, 503})
MAX_ATTEMPTS = 6
TIMEOUT_SECONDS = 60
MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")

MECH = "0x77af31de935740567cf4ff1986d04b2c964a786a"
VALORY_MECHS = (
    "0x601024e27f1c67b28209e24272ced8a31fc8151f",
    "0xc05e7412439bd7e91730a6880e18d5d5873f632c",
)
TOOLS = ("claude-prediction-online", "prediction-offline", "prediction-online")
DECIMALS = 18
DEFAULT_ACTIVITY_GOAL = 10
CONFIG = ChatuiConfig(trading_strategy="kelly_criterion", max_bet_size=5 * 10**17)

Outcome = Tuple[str, Optional[str]]


@dataclass(frozen=True)
class Case:
    """A chat message, what the chat showed right before it, and the readings that are right."""

    name: str
    message: str
    expected: FrozenSet[Outcome]
    last_shown: Optional[str] = None


def _outcomes(*outcomes: Outcome) -> FrozenSet[Outcome]:
    """The (intent, mech) pairs a case accepts."""
    return frozenset(outcomes)


CASES = (
    Case("yes_after_report", "yes", _outcomes(("approve", MECH)), last_shown=MECH),
    Case("yes_nothing_shown", "yes", _outcomes(("none", None), ("approve", None))),
    Case(
        "ok_after_report",
        "ok",
        _outcomes(("approve", MECH), ("none", None)),
        last_shown=MECH,
    ),
    Case(
        "no_thanks_after_report",
        "no thanks",
        _outcomes(("none", None)),
        last_shown=MECH,
    ),
    Case(
        "should_i_approve",
        f"should I approve {MECH}?",
        _outcomes(("approve", MECH), ("ask", MECH), ("none", None)),
    ),
    Case("tell_me_about", f"tell me about {MECH}", _outcomes(("ask", MECH))),
    Case(
        "approve_by_name",
        "approve the Bob Labs one",
        _outcomes(("approve", None), ("ask", None), ("none", None)),
        last_shown=MECH,
    ),
    Case(
        "stop_using_it",
        "stop using it",
        _outcomes(("remove", MECH)),
        last_shown=MECH,
    ),
    Case(
        "only_use_this_one",
        "only use this one from now on",
        _outcomes(("pin", MECH)),
        last_shown=MECH,
    ),
    Case("how_do_pins_work", "how do pins work?", _outcomes(("none", None))),
    Case(
        "what_if_i_remove_it",
        "what happens if I remove it?",
        _outcomes(("none", None), ("ask", MECH)),
        last_shown=MECH,
    ),
    Case(
        "should_i_approve_it",
        "should I approve it?",
        _outcomes(("none", None), ("ask", MECH)),
        last_shown=MECH,
    ),
    Case(
        "should_i_pin_it",
        "should I pin it?",
        _outcomes(("none", None), ("ask", MECH)),
        last_shown=MECH,
    ),
    Case(
        "can_i_remove_later",
        f"can I remove {MECH} later if it does badly?",
        _outcomes(("none", None), ("ask", MECH)),
    ),
    Case(
        "what_does_unpin_do",
        "what does unpinning a mech do?",
        _outcomes(("none", None)),
    ),
    Case("trading_off_today", "turn trading off for today", _outcomes(("none", None))),
    Case(
        "approve_and_set_bets",
        "approve it and set bets to 5",
        _outcomes(("approve", MECH)),
        last_shown=MECH,
    ),
)


def fill_prompt(message: str) -> str:
    """The config prompt for the message, filled as the handler fills it for the sample config."""
    unit = 10**DECIMALS
    max_bet = CONFIG.max_bet_size
    return CHATUI_PROMPT.format(
        user_prompt=message,
        current_trading_strategy=CONFIG.trading_strategy,
        current_allowed_tools=(
            "Automatic tool selection based on policy (all available tools)"
        ),
        available_tools="{" + ", ".join(repr(tool) for tool in TOOLS) + "}",
        current_selected_mechs="All configured valid mechs",
        current_approved_mechs="None",
        available_mechs=", ".join(VALORY_MECHS),
        current_fixed_bet_size=None,
        current_max_bet_size=None if max_bet is None else max_bet / unit,
        absolute_min_bet_size=10**16 / unit,
        absolute_max_bet_size=2 * 10**18 / unit,
        units="wxDAI",
        decimals=DECIMALS,
        current_activity_goal=DEFAULT_ACTIVITY_GOAL,
        activity_goal_source="the default",
        default_activity_goal=DEFAULT_ACTIVITY_GOAL,
        activity_goal_progress="not counted yet",
    )


def response_json_schema() -> Dict[str, Any]:
    """The reply schema the handler sends, converted as the connection converts it."""
    schema = build_chatui_llm_response_schema()
    reply_class = pickle.loads(bytes.fromhex(schema["class"]))  # nosec
    return pydantic_to_gemini_schema(reply_class)


def ask_model(
    prompt: str, api_key: str, model: str, temperature: float
) -> Dict[str, Any]:
    """Send the prompt to the model and decode its JSON reply."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "response_mime_type": "application/json",
            "response_json_schema": response_json_schema(),
        },
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = requests.post(
            GEMINI_URL.format(model=quote(model_name(model), safe="")),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            data=json.dumps(body),
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
            break
        wait = 5 * attempt
        print(f"  model busy ({response.status_code}), retrying in {wait}s")
        time.sleep(wait)
    if not response.ok:
        sys.exit(
            f"The model call failed ({response.status_code}): {response.text[:500]}"
        )
    text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _sample_handler() -> HttpHandler:
    """A chat handler holding only the sample config, for its config-change check."""
    handler = HttpHandler.__new__(HttpHandler)
    handler._context = SimpleNamespace(  # pylint: disable=protected-access
        state=SimpleNamespace(chatui_config=CONFIG),
        params=SimpleNamespace(
            is_running_on_polymarket=False,
            default_activity_goal=DEFAULT_ACTIVITY_GOAL,
        ),
    )
    return handler


def handler_action(
    reply: Dict[str, Any], case: Case, handler: HttpHandler
) -> Tuple[Outcome, str]:
    """The intent and mech the handler resolves from the reply, and what it does next."""
    intent, mech = resolve_intent(
        reply.get("mech_intent"), case.message, case.last_shown
    )
    outcome = (intent.value, None if intent is MechIntent.NONE else mech)
    if intent is MechIntent.NONE:
        return outcome, "answers with the model's message and config update"
    if handler._changes_config(  # pylint: disable=protected-access
        reply.get("updated_agent_config")
    ):
        return outcome, "does neither: a mech action and a config change"
    if mech is None:
        return outcome, "asks which mech"
    if intent is MechIntent.APPROVE:
        if mech == case.last_shown:
            return outcome, "takes the offer the report just showed"
        return outcome, "shows the report, which asks for a yes"
    if intent is MechIntent.ASK:
        return outcome, "shows the report"
    return outcome, f"runs {intent.value} on the mech"


def run(
    cases: Sequence[Case], api_key: str, model: str, temperature: float, repeat: int
) -> int:
    """Run each case `repeat` times, print the readings, and return how many were not expected."""
    handler = _sample_handler()
    misses = 0
    for case in cases:
        for _ in range(repeat):
            reply = ask_model(fill_prompt(case.message), api_key, model, temperature)
            outcome, action = handler_action(reply, case, handler)
            hit = outcome in case.expected
            misses += not hit
            print(f"{'ok  ' if hit else 'MISS'} {case.name}: {case.message!r}")
            print(f"     expected: {sorted(case.expected, key=str)}")
            print(f"     returned: {json.dumps(reply.get('mech_intent'))}")
            print(f"     resolved: {outcome}; the handler {action}")
    return misses


def list_models(api_key: str) -> List[str]:
    """The models this key can call with generateContent."""
    response = requests.get(
        MODELS_URL,
        headers={"x-goog-api-key": api_key},
        params={"pageSize": 1000},
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        sys.exit(
            f"Listing models failed ({response.status_code}): {response.text[:500]}"
        )
    return sorted(
        model["name"].removeprefix("models/")
        for model in response.json().get("models", [])
        if "generateContent" in model.get("supportedGenerationMethods", [])
    )


def model_name(value: str) -> str:
    """A model name made only of the characters model ids use."""
    if not MODEL_NAME.fullmatch(value):
        raise argparse.ArgumentTypeError(f"not a model name: {value!r}")
    return value


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Read the command line."""
    names = [case.name for case in CASES]
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--model", default=DEFAULT_MODEL, type=model_name)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--repeat", type=int, default=1, help="calls per case")
    parser.add_argument(
        "--case", action="append", choices=names, help="run only this case"
    )
    parser.add_argument(
        "--list-models", action="store_true", help="list the models this key can use"
    )
    return parser.parse_args(argv)


def main() -> None:
    """Run the selected cases against the model."""
    args = parse_args()
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        sys.exit(f"Set {API_KEY_ENV} to a Gemini API key.")
    if args.list_models:
        print("\n".join(list_models(api_key)))
        return
    cases = [case for case in CASES if args.case is None or case.name in args.case]
    misses = run(cases, api_key, args.model, args.temperature, args.repeat)
    print(f"{misses} of {len(cases) * args.repeat} readings were not expected.")
    sys.exit(1 if misses else 0)


if __name__ == "__main__":
    main()
