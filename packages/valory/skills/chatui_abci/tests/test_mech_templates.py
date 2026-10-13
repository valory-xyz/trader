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

"""Tests for rendering mech reports and consent cards."""

from typing import Any, Optional

import pytest

from packages.valory.skills.chatui_abci.mech_report import (
    MechReport,
    Refusal,
    VALORY_TERMS,
)
from packages.valory.skills.chatui_abci.mech_templates import (
    ASK_ALONE,
    OLAS_DISCLAIMER,
    VERIFIED_MEANS,
    offers_consent,
    render_consent,
    render_report,
)

MECH = "0x" + "b0" * 20
NATIVE_TYPE_ID = "ba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
NATIVE_RATE = 10**16  # 0.01 xDAI
CAP = NATIVE_RATE
CONSENT = (
    f"Approving accepts up to 0.01 xDAI per request for {MECH}. If its operator "
    "raises the price, your agent stops using this mech until you approve the "
    "new price. It starts with no track record on your side and earns work "
    "through normal scoring. Reply to confirm."
)


def _report(**fields: Any) -> MechReport:
    """A full, approvable third-party report priced at 0.01 xDAI unless said otherwise."""
    facts: Any = dict(
        name="Bob Mech",
        operator_name="Bob Labs",
        domain="bobmech.com",
        domain_verified=True,
        created_at="2025-06-15",
        age_days=120,
        same_creator_mechs=2,
        tools=["prediction-online", "prediction-offline"],
        payment_method="xDAI",
        payment_ceiling="0.01 xDAI",
        max_delivery_rate=NATIVE_RATE,
        payment_type_id=NATIVE_TYPE_ID,
        received_requests=430,
        self_delivered=412,
        delivered_by_others=11,
    )
    facts.update(fields)
    return MechReport(address=MECH, chain_id=100, fetched_at=1, **facts)


def _lines(report: MechReport, cap: Optional[int] = CAP, offer: bool = True) -> list:
    """The rendered report, split into its lines."""
    return render_report(report, cap, offer).split("<br>")


def test_consent_card_is_exact() -> None:
    """The card names the price and the address and nothing a model wrote."""
    assert render_consent(_report()) == CONSENT


def test_a_full_report_reads_in_order_and_ends_with_the_card() -> None:
    """Name, operator, age, tools, payment, record, the disclaimer, then the consent card."""
    assert _lines(_report()) == [
        f"Bob Mech, {MECH}, on Gnosis.",
        f"Run by Bob Labs, bobmech.com, verified. {VERIFIED_MEANS}",
        "Created 2025-06-15, 120 days ago, created by the same address as 2 other mechs.",
        "Tools: prediction-online, prediction-offline.",
        "Paid with xDAI, up to 0.01 xDAI per request.",
        "430 requests received, 412 delivered by it, 11 delivered by other mechs "
        "after it missed the deadline; off-chain requests are counted once settled.",
        OLAS_DISCLAIMER,
        CONSENT,
    ]
    assert offers_consent(_report(), CAP) is True


def test_an_unverified_operator_is_said_so_without_a_name() -> None:
    """No provider means no operator line beyond the verdict."""
    lines = _lines(_report(operator_name=None, domain=None, domain_verified=False))
    assert lines[1] == "Its operator is not verified."
    assert VERIFIED_MEANS not in lines


def test_unknown_facts_are_left_out() -> None:
    """Lines whose data is missing are skipped rather than rendered as None."""
    lines = _lines(
        _report(
            name=None,
            created_at=None,
            age_days=None,
            same_creator_mechs=None,
            tools=[],
            payment_ceiling=None,
            received_requests=None,
        )
    )
    assert lines[0] == f"Unnamed mech, {MECH}, on Gnosis."
    assert "Paid with xDAI." in lines
    assert not any(
        "Created" in line or "Tools" in line or "received" in line for line in lines
    )
    assert "None" not in "".join(lines)


@pytest.mark.parametrize(
    "operator_name, tools, forbidden",
    [
        ("<script>alert(1)</script>", ["<b>x</b>"], ("<script>", "<b>")),
        ("<div style='display:none'", [], ("<div",)),
        ("Bob & Co", ["a<b"], ("a<b", "Bob & Co")),
        ('Bob\'s "mech"', [], ("'", '"')),
    ],
)
def test_operator_text_is_escaped(
    operator_name: str, tools: list, forbidden: tuple
) -> None:
    """Operator-written strings cannot inject markup into the UI."""
    text = render_report(
        _report(
            name=operator_name,
            operator_name=operator_name,
            domain=operator_name,
            tools=tools,
        ),
        CAP,
    )
    for raw in forbidden:
        assert raw not in text
    assert "&lt;" in text or "&amp;" in text or "&#x27;" in text


def test_the_valory_ending_links_our_figures_and_offers_nothing() -> None:
    """Our own mech gets the analytics link and terms; no consent card."""
    report = _report(is_valory=True, analytics_url="https://analytics/100/" + MECH)
    lines = _lines(report)
    assert lines[-1] == (
        "This is a Valory mech the agent already uses; its accuracy is at "
        f"https://analytics/100/{MECH}. {VALORY_TERMS}"
    )
    assert "Approving accepts" not in "".join(lines)
    assert offers_consent(report, CAP) is False


def test_a_valory_report_carries_no_third_party_verdict_or_disclaimer() -> None:
    """The operator verdict and the third-party disclaimer describe other people's mechs."""
    report = _report(
        is_valory=True,
        domain_verified=False,
        analytics_url="https://analytics/100/" + MECH,
    )
    text = render_report(report, CAP)
    assert OLAS_DISCLAIMER not in text
    assert "verified" not in text


@pytest.mark.parametrize(
    "refusal, disclaimer_shown",
    [
        (Refusal.NEVER_DELIVERED, True),
        (Refusal.MANIFEST_UNREADABLE, False),
        (Refusal.NOT_INDEXED, False),
        (Refusal.RECORD_UNAVAILABLE, False),
    ],
)
def test_the_disclaimer_appears_only_when_a_card_was_read(
    refusal: Refusal, disclaimer_shown: bool
) -> None:
    """Without a card there is no third-party claim to disclaim."""
    text = render_report(_report(refusal=refusal), CAP)
    assert (OLAS_DISCLAIMER in text) is disclaimer_shown


@pytest.mark.parametrize(
    "refusal, sentence",
    [
        (
            Refusal.NEVER_DELIVERED,
            "It has never delivered an on-chain request, so it cannot be approved.",
        ),
        (Refusal.NOT_INDEXED, "No such mech is found on this chain."),
        (
            Refusal.RECORD_UNAVAILABLE,
            "Its record cannot be read right now; try again later.",
        ),
        (
            Refusal.MANIFEST_UNREADABLE,
            "I can't read this mech's description, so I can't approve it. Try again later.",
        ),
    ],
)
def test_a_refusal_ends_the_report_without_a_card(
    refusal: Refusal, sentence: str
) -> None:
    """Each refusal has its own sentence and no consent card."""
    report = _report(refusal=refusal)
    lines = _lines(report)
    assert lines[-1] == sentence
    assert "Approving accepts" not in "".join(lines)
    assert offers_consent(report, CAP) is False


@pytest.mark.parametrize(
    "refusal, operator_line_shown",
    [
        (Refusal.NEVER_DELIVERED, True),
        (Refusal.MANIFEST_UNREADABLE, False),
        (Refusal.NOT_INDEXED, False),
        (Refusal.RECORD_UNAVAILABLE, False),
    ],
)
def test_the_operator_verdict_appears_only_when_a_card_was_read(
    refusal: Refusal, operator_line_shown: bool
) -> None:
    """Without a card there is no operator to call verified or not."""
    text = render_report(_report(refusal=refusal), CAP)
    assert ("verified" in text) is operator_line_shown


@pytest.mark.parametrize(
    "fields",
    [
        {"max_delivery_rate": None},
        {"payment_ceiling": None, "payment_method": "a Nevermined subscription"},
    ],
)
def test_an_unreadable_price_cannot_be_approved(fields: dict) -> None:
    """No price, no consent."""
    report = _report(**fields)
    assert _lines(report)[-1] == (
        "I can't read what this mech charges, so it cannot be approved."
    )
    assert offers_consent(report, CAP) is False


def test_a_price_above_the_cap_is_refused_with_both_prices() -> None:
    """The agent's cap, rendered in the same asset, bounds what can be approved."""
    report = _report(max_delivery_rate=NATIVE_RATE * 3, payment_ceiling="0.03 xDAI")
    assert _lines(report)[-1] == (
        "It charges 0.03 xDAI per request, above the 0.01 xDAI this agent allows, "
        "so it cannot be approved."
    )
    assert offers_consent(report, CAP) is False


def test_a_price_at_the_cap_is_approvable() -> None:
    """The cap is inclusive."""
    assert offers_consent(_report(max_delivery_rate=CAP), CAP) is True


def test_an_asset_without_a_cap_is_refused() -> None:
    """No cap for the asset means no mech paid in it can be approved."""
    report = _report()
    assert _lines(report, cap=None)[-1] == (
        "This agent allows no mech paid with xDAI, so it cannot be approved."
    )
    assert offers_consent(report, None) is False


def test_an_approved_mech_at_its_accepted_price_offers_removal() -> None:
    """Already approved and not raised: no card, a way out."""
    report = _report(
        is_approved=True, accepted_rate=NATIVE_RATE, accepted_ceiling="0.01 xDAI"
    )
    assert _lines(report)[-1] == (
        "Approved at up to 0.01 xDAI per request. Say remove to remove it."
    )
    assert offers_consent(report, CAP) is False


def test_an_approved_mech_that_raised_its_price_gets_a_new_card() -> None:
    """The raise is stated with both prices and the new price is offered."""
    report = _report(
        is_approved=True, accepted_rate=NATIVE_RATE // 2, accepted_ceiling="0.005 xDAI"
    )
    assert _lines(report)[-1] == (
        "Approved at up to 0.005 xDAI; it now charges up to 0.01 xDAI, so your "
        f"agent has stopped using it until you approve the new price. {CONSENT}"
    )
    assert offers_consent(report, CAP) is True


def test_an_approved_mech_that_cut_its_price_is_not_offered_again() -> None:
    """A cut is not a raise; the standing approval holds."""
    report = _report(
        is_approved=True, accepted_rate=NATIVE_RATE * 2, accepted_ceiling="0.02 xDAI"
    )
    assert _lines(report)[-1].startswith("Approved at up to 0.02 xDAI per request.")
    assert offers_consent(report, CAP) is False


def test_without_an_offer_an_approvable_mech_gets_no_card() -> None:
    """Shown among others, the mech is approvable but no consent is put up."""
    report = _report()
    lines = _lines(report, offer=False)
    assert lines[-1] == "It can be approved."
    assert "Approving accepts" not in "".join(lines)
    assert offers_consent(report, CAP) is True


def test_without_an_offer_a_raised_price_is_stated_without_a_card() -> None:
    """The raise and the pause are still reported; the card is not."""
    report = _report(
        is_approved=True, accepted_rate=NATIVE_RATE // 2, accepted_ceiling="0.005 xDAI"
    )
    assert _lines(report, offer=False)[-1] == (
        "Approved at up to 0.005 xDAI; it now charges up to 0.01 xDAI, so your "
        "agent has stopped using it until you approve the new price."
    )


def test_ask_alone_line_is_the_handlers_closing_sentence() -> None:
    """The line the handler appends when several mechs were named."""
    assert ASK_ALONE == "To approve one of these, ask about it on its own."


def test_an_unknown_chain_is_named_by_id() -> None:
    """A chain outside the table is still identified."""
    assert _lines(MechReport(address=MECH, chain_id=4663, fetched_at=1))[0] == (
        f"Unnamed mech, {MECH}, on chain 4663."
    )
