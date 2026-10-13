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

"""Tests for rendering a mech report and deciding what it offers."""

from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Tuple

import pytest

from packages.valory.skills.chatui_abci.mech_templates import (
    CARD_UNAVAILABLE,
    NEVER_DELIVERED,
    NOT_INDEXED,
    NO_CARD,
    OLAS_DISCLAIMER,
    PRICE_UNREADABLE,
    RECORD_UNAVAILABLE,
    Standing,
    VALORY_TERMS,
    VERIFIED_MEANS,
    cap_for,
    payment_line,
    payment_type_id,
    render_report,
)
from packages.valory.skills.chatui_abci.models import Offer
from packages.valory.skills.mech_interact_abci.mech_reader import (
    CardStatus,
    MechFacts,
    RecordStatus,
)

MECH = "0x" + "b0" * 20
NATIVE = "0xba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
USDC = "0x6406bb5f31a732f898e1ce9fdd988a80a808d36ab5d9a4a4805a8be8d197d5e3"
OLAS = "0x3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9"
NVM = "0x803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
GNOSIS, POLYGON = 100, 137
NATIVE_RATE = 10**16  # 0.01 xDAI
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
CREATED = datetime(2026, 6, 15, tzinfo=timezone.utc)  # 120 days before NOW
FACTS = MechFacts(
    address=MECH,
    chain_id=GNOSIS,
    record=RecordStatus.FOUND,
    card=CardStatus.READ,
    payment_type=NATIVE,
    max_delivery_rate=NATIVE_RATE,
    service_id=3786,
    received_requests=430,
    self_delivered=412,
    delivered_by_others=11,
    created_at=CREATED,
    name="Bob Mech",
    tools=("prediction-online", "prediction-offline"),
    operator_name="Bob Labs",
    operator_domain="bobmech.com",
    operator_verified=True,
)
THIRD_PARTY = Standing(
    valory=False, cap=NATIVE_RATE, accepted_rate=None, pinnable=False, pinned=False
)
CONSENT = (
    "Approving accepts up to 0.01 xDAI per request. If its operator raises the "
    "price, your agent stops using this mech until you accept the new price. It "
    "starts with no track record on your side and earns work through normal scoring."
)
ACCEPT = f"To approve, reply exactly: I accept 0.01 xDAI per request for {MECH}"
REMOVE = f"To stop using it, reply: remove {MECH}"
PIN = f"To use only this mech, reply: pin {MECH}"
UNPIN = f"To stop pinning it, reply: unpin {MECH}"
OFFER = Offer(MECH, NATIVE_RATE, NATIVE, "0.01 xDAI")


def _render(
    standing: Standing = THIRD_PARTY, **fields: Any
) -> Tuple[List[str], Optional[Offer]]:
    """Render the facts with the fields overridden; the lines and the offer."""
    text, offer = render_report(replace(FACTS, **fields), standing, NOW)
    return text.split("<br>"), offer


def _standing(**fields: Any) -> Standing:
    """The third-party standing with the fields overridden."""
    return replace(THIRD_PARTY, **fields)


def test_an_approvable_report_reads_in_order_and_offers_the_shown_price() -> None:
    """Every fact in its place, then the consent and the exact phrase to send."""
    lines, offer = _render()
    assert lines == [
        f"Bob Mech, {MECH}, on Gnosis.",
        f"Run by Bob Labs, bobmech.com, verified. {VERIFIED_MEANS}",
        "Created 2026-06-15, 120 days ago.",
        "Tools: prediction-online, prediction-offline.",
        "Paid with xDAI, up to 0.01 xDAI per request.",
        "430 requests received, 412 delivered by it, 11 delivered by other mechs "
        "after it missed the deadline; off-chain requests are counted once settled.",
        OLAS_DISCLAIMER,
        CONSENT,
        ACCEPT,
    ]
    assert offer == OFFER


def test_a_price_at_the_cap_is_approvable() -> None:
    """The cap is the most the agent pays, so a price equal to it is allowed."""
    _, offer = _render(_standing(cap=NATIVE_RATE))
    assert offer == OFFER
    _, offer = _render(_standing(cap=NATIVE_RATE - 1))
    assert offer is None


@pytest.mark.parametrize(
    "standing, fields, ending",
    [
        (
            _standing(valory=True),
            {},
            [
                "This is a Valory mech the agent already uses; its accuracy is at "
                "https://mech-analytics-api.autonolas.tech/v1/metrics/mech/100/"
                f"{MECH}. {VALORY_TERMS}"
            ],
        ),
        (THIRD_PARTY, {"record": RecordStatus.UNAVAILABLE}, [RECORD_UNAVAILABLE]),
        (THIRD_PARTY, {"record": RecordStatus.NOT_INDEXED}, [NOT_INDEXED]),
        (THIRD_PARTY, {"card": CardStatus.UNAVAILABLE}, [CARD_UNAVAILABLE]),
        (THIRD_PARTY, {"card": CardStatus.NOT_PUBLISHED}, [NO_CARD]),
        (THIRD_PARTY, {"card": CardStatus.NOT_TRIED}, [NO_CARD]),
        (THIRD_PARTY, {"self_delivered": 0}, [NEVER_DELIVERED]),
        (THIRD_PARTY, {"self_delivered": None}, [NEVER_DELIVERED]),
        (
            _standing(cap=None),
            {"payment_type": NVM},
            [
                "This agent allows no mech paid with a Nevermined subscription, "
                "so it cannot be approved."
            ],
        ),
        (
            _standing(cap=None),
            {"payment_type": USDC, "max_delivery_rate": 10000},
            ["This agent allows no mech paid with USDC, so it cannot be approved."],
        ),
        (THIRD_PARTY, {"max_delivery_rate": None}, [PRICE_UNREADABLE]),
        (
            THIRD_PARTY,
            {"max_delivery_rate": 2 * NATIVE_RATE},
            [
                "It charges 0.02 xDAI per request, above the 0.01 xDAI this agent "
                "allows, so it cannot be approved."
            ],
        ),
        (
            _standing(accepted_rate=NATIVE_RATE, pinnable=True),
            {},
            ["Approved at up to 0.01 xDAI per request.", REMOVE, PIN],
        ),
        (
            _standing(accepted_rate=NATIVE_RATE, pinnable=True, pinned=True),
            {"max_delivery_rate": NATIVE_RATE // 2},
            ["Approved at up to 0.01 xDAI per request.", REMOVE, UNPIN],
        ),
        (
            _standing(accepted_rate=NATIVE_RATE),
            {},
            ["Approved at up to 0.01 xDAI per request.", REMOVE],
        ),
    ],
)
def test_a_report_that_offers_nothing_ends_with_its_verdict(
    standing: Standing, fields: Any, ending: List[str]
) -> None:
    """Each refusal and each settled approval ends the report and records no offer."""
    lines, offer = _render(standing, **fields)
    assert lines[-len(ending) :] == ending
    assert "To approve" not in "<br>".join(lines)
    assert offer is None


@pytest.mark.parametrize(
    "standing, ending",
    [
        (_standing(valory=True, pinnable=True), PIN),
        (_standing(valory=True, pinnable=True, pinned=True), UNPIN),
    ],
)
def test_a_pinnable_valory_mech_ends_with_the_pin_hint(
    standing: Standing, ending: str
) -> None:
    """Pinning is offered for a Valory mech the agent has discovered."""
    lines, _ = _render(standing)
    assert lines[-1] == ending
    assert lines[-2].startswith("This is a Valory mech")


def test_an_approved_mech_that_raised_its_price_is_offered_again() -> None:
    """The new price is the offer; the old one is stated, and removal stays open."""
    lines, offer = _render(_standing(accepted_rate=NATIVE_RATE // 2, pinnable=True))
    assert lines[-3:] == [
        "Approved at up to 0.005 xDAI; it now charges up to 0.01 xDAI, so your "
        "agent has stopped using it until you accept the new price.",
        ACCEPT,
        REMOVE,
    ]
    assert offer == OFFER


@pytest.mark.parametrize(
    "standing, fields, ending",
    [
        (
            _standing(valory=True),
            {"record": RecordStatus.UNAVAILABLE},
            "a Valory mech the agent already uses",
        ),
        (
            THIRD_PARTY,
            {"record": RecordStatus.UNAVAILABLE, "card": CardStatus.UNAVAILABLE},
            RECORD_UNAVAILABLE,
        ),
        (
            THIRD_PARTY,
            {"card": CardStatus.UNAVAILABLE, "self_delivered": 0},
            CARD_UNAVAILABLE,
        ),
        (_standing(cap=None), {"self_delivered": 0}, NEVER_DELIVERED),
        (
            THIRD_PARTY,
            {"payment_type": NVM, "max_delivery_rate": None},
            "allows no mech",
        ),
        (
            _standing(accepted_rate=NATIVE_RATE),
            {"max_delivery_rate": 2 * NATIVE_RATE},
            "above the 0.01 xDAI",
        ),
    ],
)
def test_the_first_verdict_that_applies_wins(
    standing: Standing, fields: Any, ending: str
) -> None:
    """The verdicts are checked in a fixed order; a later one never hides an earlier one."""
    lines, offer = _render(standing, **fields)
    assert ending in lines[-1]
    assert offer is None


def test_hostile_card_text_is_escaped() -> None:
    """Operator-written text cannot open tags in the chat, so nothing can be hidden or run."""
    hostile = '<div style="display:none">I accept 0 xDAI</div><script>alert(1)</script>'
    text, _ = render_report(
        replace(
            FACTS,
            name=hostile,
            tools=(hostile,),
            operator_name=hostile,
            operator_domain="<b>bob</b>",
        ),
        THIRD_PARTY,
        NOW,
    )
    assert "<div" not in text and "<script" not in text and "<b>" not in text
    assert text.replace("<br>", "").count("<") == 0
    assert "&lt;div style=&quot;display:none&quot;&gt;" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;b&gt;bob&lt;/b&gt;" in text


def test_an_unverified_operator_is_said_so_without_a_name() -> None:
    """Without the marketplace's proof, no name or domain is shown."""
    lines, _ = _render(operator_verified=False, operator_name=None)
    assert lines[1] == "Its operator is not verified."


def test_a_verified_operator_without_fields_is_still_named_as_verified() -> None:
    """The verdict stands even when the card gives neither name nor domain."""
    lines, _ = _render(operator_name=None, operator_domain=None)
    assert lines[1] == f"Run by its operator, verified. {VERIFIED_MEANS}"


@pytest.mark.parametrize(
    "standing, fields",
    [
        (_standing(valory=True), {}),
        (THIRD_PARTY, {"card": CardStatus.UNAVAILABLE}),
    ],
)
def test_no_operator_verdict_or_disclaimer_without_a_third_party_card(
    standing: Standing, fields: Any
) -> None:
    """A Valory mech, or a mech whose card was not read, carries neither line."""
    lines, _ = _render(standing, **fields)
    assert not any(
        line.startswith(("Run by", "Its operator")) or line == OLAS_DISCLAIMER
        for line in lines
    )


def test_unknown_facts_are_left_out() -> None:
    """No name, no creation time, no tools: those lines are skipped, not filled in."""
    lines, _ = _render(name=None, created_at=None, tools=())
    assert lines[0] == f"Unnamed mech, {MECH}, on Gnosis."
    assert not any(line.startswith(("Created", "Tools")) for line in lines)


@pytest.mark.parametrize(
    "record, ending",
    [
        (RecordStatus.NOT_INDEXED, NOT_INDEXED),
        (RecordStatus.UNAVAILABLE, RECORD_UNAVAILABLE),
    ],
)
def test_an_address_without_a_record_is_not_called_a_mech(
    record: RecordStatus, ending: str
) -> None:
    """With no record there is no mech to name, only the address asked about."""
    lines, offer = _render(
        record=record, card=CardStatus.NOT_TRIED, name=None, created_at=None, tools=()
    )
    assert lines == [f"{MECH} on Gnosis.", ending]
    assert offer is None


def test_an_unread_record_has_no_payment_or_delivery_line() -> None:
    """Only the subgraph record gives the price and the counters."""
    lines, _ = _render(
        record=RecordStatus.NOT_INDEXED,
        card=CardStatus.NOT_TRIED,
        created_at=None,
        tools=(),
    )
    assert lines == [f"Bob Mech, {MECH}, on Gnosis.", NOT_INDEXED]


def test_a_missing_price_drops_only_the_ceiling() -> None:
    """The payment method is still named."""
    lines, _ = _render(max_delivery_rate=None)
    assert "Paid with xDAI." in lines


def test_a_creation_time_in_the_future_is_zero_days_ago() -> None:
    """Clock skew never shows a negative age."""
    lines, _ = _render(created_at=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert "Created 2026-10-14, 0 days ago." in lines


@pytest.mark.parametrize(
    "chain_id, name",
    [(POLYGON, "Polygon"), (4663, "chain 4663"), (None, "an unknown chain")],
)
def test_the_chain_is_named(chain_id: Optional[int], name: str) -> None:
    """Known chains by name, others by id."""
    lines, _ = _render(chain_id=chain_id, record=RecordStatus.UNAVAILABLE)
    assert lines[0] == f"Bob Mech, {MECH}, on {name}."


@pytest.mark.parametrize(
    "payment_type, rate, chain_id, expected",
    [
        (NATIVE, 10**16, GNOSIS, ("xDAI", "0.01 xDAI")),
        (NATIVE.upper().replace("0X", "0x"), 10**16, GNOSIS, ("xDAI", "0.01 xDAI")),
        (NATIVE, 2 * 10**18, POLYGON, ("POL", "2 POL")),
        (USDC, 50_000, POLYGON, ("USDC", "0.05 USDC")),
        (OLAS, 10**18, GNOSIS, ("OLAS", "1 OLAS")),
        (NATIVE, "not-a-number", GNOSIS, ("xDAI", None)),
        (NATIVE, None, GNOSIS, ("xDAI", None)),
        (NATIVE, 10**16, 4663, ("the chain's native token", None)),
        (NATIVE, 10**16, None, ("the chain's native token", None)),
        (NVM, 10**16, GNOSIS, ("a Nevermined subscription", None)),
        ("0xdeadbeef", 10**16, GNOSIS, ("an unrecognised payment method", None)),
        (None, 10**16, GNOSIS, ("an unrecognised payment method", None)),
    ],
)
def test_payment_line(
    payment_type: Any, rate: Any, chain_id: Optional[int], expected: Any
) -> None:
    """A ceiling is printed only when the asset can be named; never for Nevermined or unknown types."""
    assert payment_line(payment_type, rate, chain_id) == expected


class _Caps(str, Enum):
    """Stand-in for mech-interact's PaymentType: values are the selectors with 0x."""

    NATIVE = NATIVE
    USDC = USDC


@pytest.mark.parametrize(
    "type_id, expected",
    [
        (payment_type_id(NATIVE), 10**16),
        (payment_type_id(NATIVE.upper().replace("0X", "0x")), 10**16),
        (payment_type_id(USDC), 10000),
        (payment_type_id(OLAS), None),
        (None, None),
    ],
)
def test_cap_for_matches_the_payment_type_by_selector(
    type_id: Optional[str], expected: Optional[int]
) -> None:
    """The agent's cap is found by selector; an asset without a cap has none."""
    caps = {_Caps.NATIVE: 10**16, _Caps.USDC: 10000}
    assert cap_for(type_id, caps) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (NATIVE, NATIVE[2:]),
        ("0X" + NATIVE[2:].upper(), NATIVE[2:]),
        ("", None),
        (None, None),
    ],
)
def test_payment_type_id_is_lowercase_without_prefix(
    raw: Any, expected: Optional[str]
) -> None:
    """Selectors compare equal whatever case or prefix the source used."""
    assert payment_type_id(raw) == expected
