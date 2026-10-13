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

"""Tests for the mech report rules."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

import pytest

from packages.valory.skills.chatui_abci.mech_report import (
    MAX_TOOLS,
    MechReport,
    Refusal,
    age_days,
    cap_for,
    card_names_mech,
    clean_text,
    created_at_utc,
    https_url,
    payment_line,
    payment_type_id,
    read_card,
    refusal_for,
    url_host,
)

NATIVE = "0xba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
USDC = "0x6406bb5f31a732f898e1ce9fdd988a80a808d36ab5d9a4a4805a8be8d197d5e3"
OLAS = "0x3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9"
NVM = "0x803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
GNOSIS, POLYGON = 100, 137
MECH = "0x" + "b0" * 20
PROVIDER = {"organization": " Bob Labs ", "url": "https://BobMech.com/about"}


def _card(**overrides: Any) -> Dict[str, Any]:
    """A marketplace agent card naming `MECH`."""
    card: Dict[str, Any] = {
        "name": " Bob's mech ",
        "description": "predictions",
        "metadata": {"network": "gnosis", "mechAddress": f"eip155:100:{MECH}"},
        "skills": [{"id": "1", "name": "prediction-online"}, {"name": " p-offline "}],
        "provider": None,
    }
    card.update(overrides)
    return card


@pytest.mark.parametrize(
    "value, expected",
    [
        ("  Bob Labs ", "Bob Labs"),
        ("", None),
        ("   ", None),
        ("bad\x00name", None),
        ("a" * 2049, None),
        (42, None),
    ],
)
def test_clean_text(value: Any, expected: Optional[str]) -> None:
    """Only printable, non-empty text of at most 2048 characters is kept."""
    assert clean_text(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://bobmech.com/terms", "https://bobmech.com/terms"),
        ("http://bobmech.com/terms", None),
        ("https:///terms", None),
        ("https://bob mech.com", None),
        ("https://[bobmech.com/terms", None),
        (None, None),
    ],
)
def test_https_url(value: Any, expected: Optional[str]) -> None:
    """Links must be https with a host and no whitespace; a malformed host is unusable, not an error."""
    assert https_url(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://BobMech.com/about", "bobmech.com"),
        ("http://bobmech.com", "bobmech.com"),
        ("bobmech.com", None),
        ("https://[bobmech.com", None),
        ("", None),
        (None, None),
    ],
)
def test_url_host(value: Any, expected: Optional[str]) -> None:
    """The host is read lowercase from a URL; a malformed one reads as none."""
    assert url_host(value) == expected


@pytest.mark.parametrize(
    "metadata, expected",
    [
        ({"mechAddress": f"eip155:100:{MECH}"}, True),
        ({"mechAddress": f"eip155:100:{MECH.upper().replace('0X', '0x')}"}, True),
        ({"mechAddress": MECH}, True),
        ({"mechAddress": "eip155:100:0x" + "c0" * 20}, False),
        ({"mechAddress": None}, False),
        ({}, False),
        ("eip155:100:" + MECH, False),
    ],
)
def test_card_names_mech(metadata: Any, expected: bool) -> None:
    """The card is about the mech only when its address ends the metadata's mechAddress."""
    assert card_names_mech({"metadata": metadata}, MECH) is expected


@pytest.mark.parametrize(
    "card",
    [
        "not an object",
        ["list"],
        None,
        _card(metadata={"mechAddress": "eip155:100:0x" + "c0" * 20}),
        _card(metadata={}),
    ],
)
def test_a_card_that_is_not_an_object_about_the_mech_is_unreadable(card: Any) -> None:
    """Nothing is read from a card for another mech or from a non-object body."""
    assert read_card(card, MECH) is None


def test_read_card_cleans_the_name_and_tools() -> None:
    """Name and tool names are stripped; non-text and blank tool entries are dropped."""
    facts = read_card(
        _card(skills=[{"name": "prediction-online"}, {"name": ""}, 3, {"name": 7}]),
        MECH,
    )
    assert facts is not None
    assert facts.name == "Bob's mech"
    assert facts.tools == ["prediction-online"]


@pytest.mark.parametrize(
    "name, skills",
    [(None, "prediction-online"), ("", None), ("bad\x00name", [])],
)
def test_read_card_without_a_usable_name_or_skills(name: Any, skills: Any) -> None:
    """A missing or unusable name reads as none, and skills that are not a list as no tools."""
    facts = read_card(_card(name=name, skills=skills), MECH)
    assert facts is not None
    assert facts.name is None
    assert facts.tools == []


def test_read_card_caps_the_tools() -> None:
    """At most MAX_TOOLS names are kept, in card order."""
    facts = read_card(
        _card(skills=[{"name": f"tool-{index}"} for index in range(MAX_TOOLS + 5)]),
        MECH,
    )
    assert facts is not None
    assert facts.tools == [f"tool-{index}" for index in range(MAX_TOOLS)]


def test_a_provider_verifies_the_operator() -> None:
    """The marketplace sets provider only when the domain proof held, so it is the verdict."""
    facts = read_card(_card(provider=PROVIDER), MECH)
    assert facts is not None
    assert facts.domain_verified is True
    assert (facts.operator_name, facts.domain) == ("Bob Labs", "bobmech.com")


@pytest.mark.parametrize("provider", [None, "Bob Labs", ["bobmech.com"]])
def test_no_provider_means_not_verified(provider: Any) -> None:
    """Without a provider object, no operator is named and the domain is not verified."""
    facts = read_card(_card(provider=provider), MECH)
    assert facts is not None
    assert facts.domain_verified is False
    assert (facts.operator_name, facts.domain) == (None, None)


def test_a_provider_with_unusable_fields_is_still_verified() -> None:
    """The verdict is the provider's presence; its name and URL are read if usable."""
    facts = read_card(_card(provider={"organization": "", "url": "not a url"}), MECH)
    assert facts is not None
    assert facts.domain_verified is True
    assert (facts.operator_name, facts.domain) == (None, None)


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
        (NVM, 10**16, GNOSIS, ("a Nevermined subscription", None)),
        ("0xdeadbeef", 10**16, GNOSIS, ("an unrecognised payment method", None)),
        (None, 10**16, GNOSIS, ("an unrecognised payment method", None)),
    ],
)
def test_payment_line(
    payment_type: Any, rate: Any, chain_id: int, expected: Any
) -> None:
    """A ceiling is printed only when the asset can be named; never for Nevermined or unknown types."""
    assert payment_line(payment_type, rate, chain_id) == expected


@pytest.mark.parametrize(
    "record_found, card_read, self_delivered, expected",
    [
        (None, True, 5, Refusal.RECORD_UNAVAILABLE),
        (False, True, 5, Refusal.NOT_INDEXED),
        (True, False, 5, Refusal.MANIFEST_UNREADABLE),
        (True, True, 0, Refusal.NEVER_DELIVERED),
        (True, False, 0, Refusal.MANIFEST_UNREADABLE),
        (True, True, 1, None),
    ],
)
def test_refusal_for(
    record_found: Optional[bool],
    card_read: bool,
    self_delivered: int,
    expected: Optional[Refusal],
) -> None:
    """The first missing requirement decides the refusal."""
    assert refusal_for(record_found, card_read, self_delivered) is expected


def test_age_days_is_never_negative() -> None:
    """A creation time in the future reads as zero days."""
    created = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert age_days(created, datetime(2026, 10, 1, tzinfo=timezone.utc)) == 122
    assert age_days(created, datetime(2026, 5, 1, tzinfo=timezone.utc)) == 0


@pytest.mark.parametrize(
    "timestamp, expected",
    [
        ("1750000000", datetime(2025, 6, 15, 15, 6, 40, tzinfo=timezone.utc)),
        (1750000000, datetime(2025, 6, 15, 15, 6, 40, tzinfo=timezone.utc)),
        ("soon", None),
        (None, None),
        (10**20, None),
    ],
)
def test_created_at_utc(timestamp: Any, expected: Optional[datetime]) -> None:
    """Block timestamps read as UTC; anything unreadable or out of range reads as none."""
    assert created_at_utc(timestamp) == expected


@pytest.mark.parametrize(
    "is_valory, refusal, approvable",
    [(False, None, True), (True, None, False), (False, Refusal.NEVER_DELIVERED, False)],
)
def test_report_is_approvable_only_when_unrefused_and_third_party(
    is_valory: bool, refusal: Optional[Refusal], approvable: bool
) -> None:
    """Valory mechs and refused mechs are never offered for approval."""
    report = MechReport(
        address=MECH,
        chain_id=GNOSIS,
        fetched_at=1,
        is_valory=is_valory,
        refusal=refusal,
    )
    assert report.approvable is approvable


@pytest.mark.parametrize(
    "accepted, live, raised",
    [
        (None, 10**16, False),
        (10**16, 10**16, False),
        (10**16, 10**16 + 1, True),
        (10**16, 10**16 - 1, False),
        (10**16, None, False),
    ],
)
def test_price_raised_only_when_the_live_rate_is_above_the_accepted_one(
    accepted: Optional[int], live: Optional[int], raised: bool
) -> None:
    """An approved mech that now charges more than the user accepted is flagged; a cut is not."""
    report = MechReport(
        address=MECH,
        chain_id=GNOSIS,
        fetched_at=1,
        accepted_rate=accepted,
        max_delivery_rate=live,
    )
    assert report.price_raised is raised


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
        (NATIVE, payment_type_id(NATIVE)),
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
