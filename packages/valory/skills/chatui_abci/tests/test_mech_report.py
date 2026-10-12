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

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from packages.valory.skills.chatui_abci.mech_report import (
    IDENTITY_REGISTRY,
    MechReport,
    PROOF_MAX_BYTES,
    ProofStatus,
    Refusal,
    age_days,
    cap_for,
    clean_text,
    fetch_proof,
    hostname,
    https_url,
    payment_line,
    payment_type_id,
    proof_matches,
    proof_url,
    read_benchmarks,
    read_operator,
    read_tools,
    refusal_for,
    verify_domain,
)

NATIVE = "0xba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
USDC = "0x6406bb5f31a732f898e1ce9fdd988a80a808d36ab5d9a4a4805a8be8d197d5e3"
OLAS = "0x3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9"
NVM = "0x803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
GNOSIS, POLYGON = 100, 137
AGENT_ID = 2182


def _registration(agent_id: Any, chain_id: int = GNOSIS) -> Dict[str, Any]:
    """A proof registration entry."""
    return {
        "agentId": agent_id,
        "agentRegistry": f"eip155:{chain_id}:{IDENTITY_REGISTRY}",
    }


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
        ("bobmech.com", "bobmech.com"),
        (" bobmech.com ", "bobmech.com"),
        ("xn--bcher-kva.example.xn--p1ai", "xn--bcher-kva.example.xn--p1ai"),
        ("BobMech.com", None),
        ("1.2.3.4", None),
        ("https://bobmech.com", None),
        ("bobmech.com:443", None),
        ("bobmech.com/path", None),
        ("bobmech.com.", None),
        ("localhost", None),
        ("-bob.com", None),
        (None, None),
    ],
)
def test_hostname(value: Any, expected: Optional[str]) -> None:
    """A domain must be a bare lowercase hostname whose last label is not numeric."""
    assert hostname(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://bobmech.com/terms", "https://bobmech.com/terms"),
        ("http://bobmech.com/terms", None),
        ("https:///terms", None),
        ("https://bob mech.com", None),
        (None, None),
    ],
)
def test_https_url(value: Any, expected: Optional[str]) -> None:
    """Links must be https with a host and no whitespace."""
    assert https_url(value) == expected


@pytest.mark.parametrize(
    "operator, expected",
    [
        ({"name": "Bob Labs", "domain": "bobmech.com"}, ("Bob Labs", "bobmech.com")),
        ({"name": "Bob Labs"}, None),
        ({"name": "", "domain": "bobmech.com"}, None),
        ({"name": "Bob Labs", "domain": "BobMech.com"}, None),
        ("Bob Labs", None),
    ],
)
def test_read_operator(operator: Any, expected: Any) -> None:
    """The operator is reported only with both a usable name and domain."""
    assert read_operator({"operator": operator}) == expected


def test_read_tools_keeps_usable_names() -> None:
    """Non-text and blank tool entries are dropped."""
    assert read_tools({"tools": ["prediction-online", "", 3, " p-offline "]}) == [
        "prediction-online",
        "p-offline",
    ]
    assert read_tools({"tools": "prediction-online"}) == []


def test_read_benchmarks_keeps_only_the_https_link() -> None:
    """A claim is its link; figures in the manifest are never read, and other links are dropped."""
    manifest = {
        "toolMetadata": {
            "b-tool": {
                "benchmark": {
                    "metric": "accuracy",
                    "value": 0.71,
                    "window": "30d",
                    "url": "https://bobmech.com/b",
                }
            },
            "a-tool": {"benchmark": {"url": "https://bobmech.com/a"}},
            "c-tool": {"benchmark": {"url": "http://bobmech.com/c"}},
            "d-tool": {"benchmark": "https://bobmech.com/d"},
            "e-tool": "not a dict",
        }
    }
    assert read_benchmarks(manifest) == {
        "a-tool": "https://bobmech.com/a",
        "b-tool": "https://bobmech.com/b",
    }
    assert read_benchmarks({"toolMetadata": []}) == {}


@pytest.mark.parametrize(
    "payment_type, rate, chain_id, expected",
    [
        (NATIVE, 10**16, GNOSIS, ("xDAI", "0.01 xDAI")),
        (NATIVE.upper().replace("0X", "0x"), 10**16, GNOSIS, ("xDAI", "0.01 xDAI")),
        (NATIVE, 2 * 10**18, POLYGON, ("POL", "2 POL")),
        (USDC, 50_000, POLYGON, ("USDC", "0.05 USDC")),
        (OLAS, 10**18, GNOSIS, ("OLAS", "1 OLAS")),
        (NATIVE, "not-a-number", GNOSIS, ("xDAI", None)),
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
    "record_found, manifest_read, self_delivered, expected",
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
    manifest_read: bool,
    self_delivered: int,
    expected: Optional[Refusal],
) -> None:
    """The first missing requirement decides the refusal."""
    assert refusal_for(record_found, manifest_read, self_delivered) is expected


@pytest.mark.parametrize(
    "registrations, expected",
    [
        ([_registration(AGENT_ID)], True),
        ([_registration(str(AGENT_ID))], True),
        (
            [
                {
                    "agentId": AGENT_ID,
                    "agentRegistry": f"EIP155:100:{IDENTITY_REGISTRY.upper()}",
                }
            ],
            True,
        ),
        ([_registration(AGENT_ID, POLYGON)], False),
        ([_registration(AGENT_ID + 1)], False),
        ([_registration(True)], False),
        ([_registration("1" * 79)], False),
        ([_registration("21x")], False),
        ("not a list", False),
    ],
)
def test_proof_matches(registrations: Any, expected: bool) -> None:
    """The proof must list the agent id under this chain's identity registry."""
    assert proof_matches({"registrations": registrations}, AGENT_ID, GNOSIS) is expected


def _response(status: int, chunks: List[bytes]) -> MagicMock:
    """A streamed `requests` response."""
    response = MagicMock(status_code=status)
    response.iter_content.return_value = iter(chunks)
    response.__enter__.return_value = response
    return response


@pytest.mark.parametrize(
    "status, chunks, expected",
    [
        (200, [json.dumps({"registrations": []}).encode()], ProofStatus.FOUND),
        (301, [], ProofStatus.REDIRECTED),
        (404, [], ProofStatus.NOT_FOUND),
        (503, [], ProofStatus.UNAVAILABLE),
        (200, [b"not json"], ProofStatus.NOT_FOUND),
        (200, [b"[1, 2]"], ProofStatus.NOT_FOUND),
        (200, [b" " * (PROOF_MAX_BYTES + 1)], ProofStatus.NOT_FOUND),
    ],
)
def test_fetch_proof_statuses(
    status: int, chunks: List[bytes], expected: ProofStatus
) -> None:
    """Redirects, errors, oversize and non-object bodies never count as a proof."""
    with patch(
        "packages.valory.skills.chatui_abci.mech_report.requests.get",
        return_value=_response(status, chunks),
    ) as mock_get:
        found, _ = fetch_proof("bobmech.com")
    assert found is expected
    mock_get.assert_called_once()
    assert (
        mock_get.call_args[0][0]
        == "https://bobmech.com/.well-known/agent-registration.json"
    )
    assert mock_get.call_args[1]["allow_redirects"] is False


def test_fetch_proof_network_error_is_unavailable() -> None:
    """A failed connection means the domain could not be reached."""
    with patch(
        "packages.valory.skills.chatui_abci.mech_report.requests.get",
        side_effect=requests.ConnectionError("down"),
    ):
        assert fetch_proof("bobmech.com") == (ProofStatus.UNAVAILABLE, None)


def test_proof_url_is_the_exact_host() -> None:
    """The proof is read from the declared host only."""
    assert (
        proof_url("bobmech.com")
        == "https://bobmech.com/.well-known/agent-registration.json"
    )


@pytest.mark.parametrize(
    "agent_id, proof, verified",
    [
        (
            AGENT_ID,
            (ProofStatus.FOUND, {"registrations": [_registration(AGENT_ID)]}),
            True,
        ),
        (
            None,
            (ProofStatus.FOUND, {"registrations": [_registration(AGENT_ID)]}),
            False,
        ),
        (AGENT_ID, None, False),
        (AGENT_ID, (ProofStatus.UNAVAILABLE, None), False),
        (AGENT_ID, (ProofStatus.REDIRECTED, None), False),
        (AGENT_ID, (ProofStatus.NOT_FOUND, None), False),
        (AGENT_ID, (ProofStatus.FOUND, {"registrations": [_registration(1)]}), False),
    ],
)
def test_verify_domain(agent_id: Optional[int], proof: Any, verified: bool) -> None:
    """Only a matching proof verifies; every failure carries a note."""
    result, note = verify_domain(agent_id, proof, GNOSIS)
    assert result is verified
    assert (note is None) is verified


def test_age_days_is_never_negative() -> None:
    """A creation time in the future reads as zero days."""
    created = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert age_days(created, datetime(2026, 10, 1, tzinfo=timezone.utc)) == 122
    assert age_days(created, datetime(2026, 5, 1, tzinfo=timezone.utc)) == 0


@pytest.mark.parametrize(
    "is_valory, refusal, approvable",
    [(False, None, True), (True, None, False), (False, Refusal.NEVER_DELIVERED, False)],
)
def test_report_is_approvable_only_when_unrefused_and_third_party(
    is_valory: bool, refusal: Optional[Refusal], approvable: bool
) -> None:
    """Valory mechs and refused mechs are never offered for approval."""
    report = MechReport(
        address="0x" + "b" * 40,
        chain_id=GNOSIS,
        fetched_at=1,
        is_valory=is_valory,
        refusal=refusal,
    )
    assert report.approvable is approvable
    facts = report.to_prompt()
    assert facts["approvable"] is approvable
    assert facts["refusal"] == (refusal.value if refusal else None)
    assert {
        "fetched_at",
        "service_id",
        "creator",
        "metadata_hash",
        "max_delivery_rate",
        "payment_type_id",
        "accepted_rate",
    }.isdisjoint(facts)
    assert facts["price_raised"] is False


@pytest.mark.parametrize(
    "accepted, live, raised",
    [
        (None, 10**16, False),
        (10**16, 10**16, False),
        (10**16, 10**16 + 1, True),
        (10**16, None, False),
    ],
)
def test_price_raised_only_when_the_live_rate_is_above_the_accepted_one(
    accepted: Optional[int], live: Optional[int], raised: bool
) -> None:
    """An approved mech that now charges more than the user accepted is flagged; a cut is not."""
    report = MechReport(
        address="0x" + "b" * 40,
        chain_id=GNOSIS,
        fetched_at=1,
        accepted_rate=accepted,
        max_delivery_rate=live,
    )
    assert report.price_raised is raised
    assert report.to_prompt()["price_raised"] is raised


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
