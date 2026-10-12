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

"""Tests for building mech reports from the chat handler."""

import concurrent.futures
import json
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.chatui_abci.mech_report import (
    IDENTITY_REGISTRY,
    ProofStatus,
    Refusal,
)
from packages.valory.skills.chatui_abci.report_requests import (
    MAX_STORED_REPORTS,
    MechReportRequests,
    addresses_in,
)

MECH = "0x" + "b0" * 20
VALORY_MECH = "0x" + "c0" * 20
CREATOR = "0x" + "d0" * 20
METADATA = "ab" * 32
NATIVE = "0xba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
AGENT_ID = 609
PROOF_TARGET = "packages.valory.skills.chatui_abci.report_requests.fetch_proof"
MATCHING_PROOF = (
    ProofStatus.FOUND,
    {
        "registrations": [
            {"agentId": AGENT_ID, "agentRegistry": f"eip155:100:{IDENTITY_REGISTRY}"}
        ]
    },
)


def _record(address: str = MECH, self_delivered: str = "412") -> Dict[str, Any]:
    """A marketplace subgraph record for one mech."""
    return {
        "data": {
            "meches": [
                {
                    "address": address,
                    "owner": CREATOR.upper().replace("0X", "0x"),
                    "receivedRequests": "430",
                    "selfDeliveredFromReceived": self_delivered,
                    "deliveredByOthersFromReceived": "11",
                    "maxDeliveryRate": str(10**16),
                    "paymentType": NATIVE,
                    "service": {
                        "id": "975",
                        "metadata": [{"metadata": "0x" + METADATA}],
                    },
                }
            ],
            "createMeches": [{"blockTimestamp": "1750000000"}],
        }
    }


SAME_CREATOR = {"data": {"meches": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}}
MANIFEST = {
    "operator": {"name": "Bob Labs", "domain": "bobmech.com"},
    "tools": ["prediction-online", "prediction-offline"],
    "toolMetadata": {
        "prediction-online": {
            "benchmark": {
                "metric": "accuracy",
                "value": 0.71,
                "window": "30d",
                "url": "https://bobmech.com/bench",
            }
        }
    },
    "termsUrl": "https://bobmech.com/terms",
}
AGENT = {"data": {"service": {"id": "975", "erc8004Agent": {"id": str(AGENT_ID)}}}}


class _Fetcher(MechReportRequests):
    """The mixin on a fake context that records requests and answers them in order."""

    def __init__(self, valid: Iterable[str] = (), approved: Iterable[str] = ()) -> None:
        self.context = MagicMock()
        self.context.params.mech_chain_id = "gnosis"
        self.context.params.valid_mechs = frozenset(valid)
        self.context.params.ipfs_address = "https://ipfs/"
        self.context.params.service_registry_subgraph_url = "https://registry"
        self.context.mechs_subgraph.url = "https://marketplace"
        self.context.requests.request_id_to_callback = {}
        self.shared_state = SimpleNamespace(
            mech_reports={}, approved_mechs=list(approved)
        )
        self.sent: List[Dict[str, Any]] = []
        self._nonces: List[str] = []
        self.context.http_dialogues.create.side_effect = self._create

    def _create(self, **kwargs: Any) -> Any:
        nonce = f"nonce-{len(self.sent)}"
        self.sent.append(kwargs)
        self._nonces.append(nonce)
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = (nonce, "")
        return SimpleNamespace(**kwargs), dialogue

    def answer(self, body: Any, status: int = 200) -> None:
        """Answer the oldest request still waiting."""
        nonce = self._nonces.pop(0)
        callback = self.context.requests.request_id_to_callback.pop(nonce)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        callback(SimpleNamespace(status_code=status, body=raw), None)

    def query(self, index: int) -> Optional[str]:
        """Get the GraphQL query of the index-th request, if it was a POST."""
        body = self.sent[index]["body"]
        return json.loads(body)["query"] if body else None


def _run(fetcher: _Fetcher, addresses: List[str]) -> MagicMock:
    """Start the reports and return the `done` callback."""
    done = MagicMock()
    fetcher._with_mech_reports(addresses, done)
    return done


def test_full_report_is_built_from_four_reads_and_a_proof() -> None:
    """Record, creator, manifest and agent id are read in order; the proof verifies the domain."""
    fetcher = _Fetcher()
    with patch(PROOF_TARGET, return_value=MATCHING_PROOF) as mock_proof:
        done = _run(fetcher, [MECH])
        fetcher.answer(_record())
        fetcher.answer(SAME_CREATOR)
        fetcher.answer(MANIFEST)
        fetcher.answer(AGENT)

    assert [request["url"] for request in fetcher.sent] == [
        "https://marketplace",
        "https://marketplace",
        "https://ipfs/f01701220" + METADATA,
        "https://registry",
    ]
    assert f'address: "{MECH}"' in str(fetcher.query(0))
    assert f'owner: "{CREATOR}"' in str(fetcher.query(1))
    assert fetcher.sent[2]["method"] == "GET"
    assert 'service(id: "975")' in str(fetcher.query(3))
    mock_proof.assert_called_once_with("bobmech.com")
    done.assert_called_once()

    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is None and report.approvable
    assert (report.operator_name, report.domain) == ("Bob Labs", "bobmech.com")
    assert report.domain_verified is True and report.domain_note is None
    assert report.same_creator_mechs == 2
    assert report.tools == ["prediction-online", "prediction-offline"]
    assert (report.payment_method, report.payment_ceiling) == ("xDAI", "0.01 xDAI")
    assert (
        report.received_requests,
        report.self_delivered,
        report.delivered_by_others,
    ) == (430, 412, 11)
    assert report.benchmarks == {"prediction-online": "https://bobmech.com/bench"}
    assert report.terms_url == "https://bobmech.com/terms"
    assert report.created_at == "2025-06-15"


def test_a_fresh_report_is_reused_without_new_requests() -> None:
    """Follow-up questions about the same mech hit the cache."""
    fetcher = _Fetcher()
    with patch(PROOF_TARGET, return_value=MATCHING_PROOF):
        _run(fetcher, [MECH])
        for body in (_record(), SAME_CREATOR, MANIFEST, AGENT):
            fetcher.answer(body)
    sent = len(fetcher.sent)

    done = _run(fetcher, [MECH.upper().replace("0X", "0x").lower()])

    done.assert_called_once()
    assert len(fetcher.sent) == sent


def test_an_unreadable_subgraph_is_refused_and_retried_next_time() -> None:
    """A failed record read refuses approval and is not cached."""
    fetcher = _Fetcher()
    done = _run(fetcher, [MECH])
    fetcher.answer(b"", status=502)

    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is Refusal.RECORD_UNAVAILABLE
    done.assert_called_once()
    _run(fetcher, [MECH])
    assert len(fetcher.sent) == 2


def test_an_unindexed_mech_is_refused() -> None:
    """A mech the subgraph does not list cannot be approved."""
    fetcher = _Fetcher()
    _run(fetcher, [MECH])
    fetcher.answer({"data": {"meches": [], "createMeches": []}})
    assert fetcher.shared_state.mech_reports[MECH].refusal is Refusal.NOT_INDEXED
    assert len(fetcher.sent) == 1


def test_an_unreadable_manifest_is_refused_without_a_proof() -> None:
    """No manifest, no approval, and the operator's domain is never contacted."""
    fetcher = _Fetcher()
    with patch(PROOF_TARGET) as mock_proof:
        _run(fetcher, [MECH])
        fetcher.answer(_record())
        fetcher.answer(SAME_CREATOR)
        fetcher.answer(b"not json")
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is Refusal.MANIFEST_UNREADABLE
    assert report.fetched_at == 0
    mock_proof.assert_not_called()
    assert len(fetcher.sent) == 3


def test_a_mech_that_never_delivered_is_refused() -> None:
    """Zero on-chain deliveries refuses approval even with a verified domain."""
    fetcher = _Fetcher()
    with patch(PROOF_TARGET, return_value=MATCHING_PROOF):
        _run(fetcher, [MECH])
        for body in (_record(self_delivered="0"), SAME_CREATOR, MANIFEST, AGENT):
            fetcher.answer(body)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is Refusal.NEVER_DELIVERED
    assert report.domain_verified is True


def test_a_valory_mech_skips_the_proof_and_links_our_figures() -> None:
    """Our own mechs carry the analytics link and terms sentence and are not offered."""
    fetcher = _Fetcher(valid=[VALORY_MECH])
    with patch(PROOF_TARGET) as mock_proof:
        _run(fetcher, [VALORY_MECH])
        fetcher.answer(_record(VALORY_MECH))
        fetcher.answer(SAME_CREATOR)
        fetcher.answer(MANIFEST)
    report = fetcher.shared_state.mech_reports[VALORY_MECH]
    assert report.is_valory and not report.approvable
    assert report.analytics_url == (
        f"https://mech-analytics-api.autonolas.tech/v1/metrics/mech/100/{VALORY_MECH}"
    )
    assert report.terms_sentence and "Valory AG" in report.terms_sentence
    mock_proof.assert_not_called()
    assert len(fetcher.sent) == 3


def test_a_slow_proof_reads_as_not_verified() -> None:
    """A proof that does not finish in time leaves the domain unverified, approval still offered."""
    fetcher = _Fetcher()
    future = MagicMock()
    future.result.side_effect = concurrent.futures.TimeoutError()
    fetcher._proof_executor_instance = MagicMock(submit=MagicMock(return_value=future))
    _run(fetcher, [MECH])
    for body in (_record(), SAME_CREATOR, MANIFEST, AGENT):
        fetcher.answer(body)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.domain_verified is False
    assert report.domain_note == "the domain could not be checked"
    assert report.approvable


def test_done_runs_once_after_every_address_is_ready() -> None:
    """Several addresses in one message are fetched together and reported together."""
    fetcher = _Fetcher()
    other = "0x" + "e0" * 20
    done = _run(fetcher, [MECH, other])
    fetcher.answer({"data": {"meches": [], "createMeches": []}})
    done.assert_not_called()
    fetcher.answer({"data": {"meches": [], "createMeches": []}})
    done.assert_called_once()


def test_the_store_keeps_only_the_most_recent_reports() -> None:
    """Old reports are dropped past the cap, oldest first."""
    fetcher = _Fetcher()
    addresses = [f"0x{index:040x}" for index in range(MAX_STORED_REPORTS + 1)]
    for address in addresses:
        _run(fetcher, [address])
        fetcher.answer({"data": {"meches": [], "createMeches": []}})
        fetcher.shared_state.mech_reports[address].fetched_at = int(address, 16) + 1
    assert len(fetcher.shared_state.mech_reports) == MAX_STORED_REPORTS


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"tell me about {MECH.upper().replace('0X', '0x')}", [MECH]),
        (f"{MECH} and {MECH} again", [MECH]),
        ("approve the Bob Labs one", []),
        ("short 0x1234 address", []),
        (
            " ".join(f"0x{index:040x}" for index in range(5)),
            [f"0x{index:040x}" for index in range(3)],
        ),
    ],
)
def test_addresses_in(text: str, expected: List[str]) -> None:
    """Addresses are found case-insensitively, deduplicated and capped."""
    assert addresses_in(text) == expected
