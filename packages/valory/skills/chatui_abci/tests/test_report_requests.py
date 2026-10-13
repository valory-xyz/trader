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

import json
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import MagicMock

import pytest

from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    LEDGER_API_ADDRESS,
)
from packages.valory.skills.chatui_abci.mech_report import Refusal
from packages.valory.skills.chatui_abci.report_requests import (
    MAX_STORED_REPORTS,
    MechReportRequests,
    addresses_in,
    agent_card_url,
)

MECH = "0x" + "b0" * 20
VALORY_MECH = "0x" + "c0" * 20
CREATOR = "0x" + "d0" * 20
NATIVE = "0xba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
SERVICE_ID = 975
RATE = 10**16
MARKETPLACE = "https://marketplace"
MARKETPLACE_API = "https://marketplace.olas.network/api/erc8004"
CARD_URL = f"{MARKETPLACE_API}/gnosis/ai-agents/{SERVICE_ID}/agent-card.json"
STATE = ContractApiMessage.Performative.STATE
ERROR = ContractApiMessage.Performative.ERROR


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
                    "paymentType": NATIVE,
                    "service": {"id": str(SERVICE_ID)},
                }
            ],
            "createMeches": [{"blockTimestamp": "1750000000"}],
        }
    }


def _card(address: str = MECH, provider: Any = None) -> Dict[str, Any]:
    """A marketplace agent card for the mech."""
    return {
        "name": "Bob's mech",
        "metadata": {"network": "gnosis", "mechAddress": f"eip155:100:{address}"},
        "skills": [{"name": "prediction-online"}, {"name": "prediction-offline"}],
        "provider": provider,
    }


SAME_CREATOR = {"data": {"meches": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}}
NOT_INDEXED: Dict[str, Any] = {"data": {"meches": [], "createMeches": []}}
PROVIDER = {"organization": "Bob Labs", "url": "https://bobmech.com"}


def _price(rate: Any, performative: Any = STATE) -> SimpleNamespace:
    """A contract API reply carrying the max delivery rate."""
    body = {"max_delivery_rate": rate} if rate is not None else {}
    return SimpleNamespace(performative=performative, state=SimpleNamespace(body=body))


class _Fetcher(MechReportRequests):
    """The mixin on a fake context that records requests and answers them in order."""

    def __init__(
        self, valid: Iterable[str] = (), approved: Optional[Dict[str, int]] = None
    ) -> None:
        self.context = MagicMock()
        self.context.params.mech_chain_id = "gnosis"
        self.context.default_ledger_id = "ethereum"
        self.context.params.valid_mechs = frozenset(valid)
        self.context.params.marketplace_api_url = MARKETPLACE_API
        self.context.mechs_subgraph.url = MARKETPLACE
        self.context.requests.request_id_to_callback = {}
        self.shared_state = SimpleNamespace(
            mech_reports={},
            approved_mechs=list(approved or {}),
            approved_mech_rates=dict(approved or {}),
        )
        self.sent: List[Dict[str, Any]] = []
        self._nonces: List[str] = []
        self.context.http_dialogues.create.side_effect = self._create
        self.context.contract_api_dialogues.create.side_effect = self._create

    def _create(self, **kwargs: Any) -> Any:
        nonce = f"nonce-{len(self.sent)}"
        self.sent.append(kwargs)
        self._nonces.append(nonce)
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = (nonce, "")
        return SimpleNamespace(**kwargs), dialogue

    def answer(self, body: Any, status: int = 200) -> None:
        """Answer the oldest request still waiting with an HTTP reply."""
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.reply(SimpleNamespace(status_code=status, body=raw))

    def reply(self, message: Any) -> None:
        """Deliver a reply to the oldest request still waiting, as the handlers would."""
        nonce = self._nonces.pop(0)
        callback = self.context.requests.request_id_to_callback.pop(nonce)
        callback(message, None)

    def query(self, index: int) -> Optional[str]:
        """Get the GraphQL query of the index-th request, if it was a POST."""
        body = self.sent[index].get("body")
        return json.loads(body)["query"] if body else None


def _run(fetcher: _Fetcher, addresses: List[str]) -> MagicMock:
    """Start the reports and return the `done` callback."""
    done = MagicMock()
    fetcher._with_mech_reports(addresses, done)
    return done


def _full_run(fetcher: _Fetcher, address: str = MECH, **card_fields: Any) -> MagicMock:
    """Fetch one report through all four reads with a priced, delivering mech."""
    done = _run(fetcher, [address])
    fetcher.answer(_record(address))
    fetcher.answer(SAME_CREATOR)
    fetcher.answer(_card(address, **card_fields))
    fetcher.reply(_price(RATE))
    return done


def test_full_report_is_built_from_record_creator_card_and_live_price() -> None:
    """Record, creator and card go over HTTP, the price over the ledger connection, in order."""
    fetcher = _Fetcher()
    done = _full_run(fetcher, provider=PROVIDER)

    assert [request.get("url") for request in fetcher.sent[:3]] == [
        MARKETPLACE,
        MARKETPLACE,
        CARD_URL,
    ]
    assert f'address: "{MECH}"' in str(fetcher.query(0))
    assert "maxDeliveryRate" not in str(fetcher.query(0))
    assert f'owner: "{CREATOR}"' in str(fetcher.query(1))
    assert fetcher.sent[2]["method"] == "GET"
    price_request = fetcher.sent[3]
    assert price_request["counterparty"] == LEDGER_API_ADDRESS
    assert price_request["performative"] == ContractApiMessage.Performative.GET_STATE
    # The ledger connection keys its APIs by ledger type and picks the chain from kwargs.
    assert price_request["ledger_id"] == "ethereum"
    assert price_request["kwargs"].body == {"chain_id": "gnosis"}
    assert price_request["contract_id"] == "valory/mech_mm:0.1.0"
    assert price_request["contract_address"] == MECH
    assert price_request["callable"] == "get_max_delivery_rate"
    assert fetcher.context.outbox.put_message.call_count == 4
    done.assert_called_once()

    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is None and report.approvable
    assert report.fetched_at > 0
    assert report.name == "Bob's mech"
    assert (report.operator_name, report.domain) == ("Bob Labs", "bobmech.com")
    assert report.domain_verified is True
    assert report.same_creator_mechs == 2
    assert report.tools == ["prediction-online", "prediction-offline"]
    assert (report.payment_method, report.payment_ceiling) == ("xDAI", "0.01 xDAI")
    assert (report.max_delivery_rate, report.payment_type_id) == (RATE, NATIVE[2:])
    assert (report.accepted_rate, report.accepted_ceiling) == (None, None)
    assert (
        report.received_requests,
        report.self_delivered,
        report.delivered_by_others,
    ) == (430, 412, 11)
    assert report.service_id == SERVICE_ID
    assert report.created_at == "2025-06-15"


def test_the_card_url_follows_the_agents_chain() -> None:
    """The network segment is the chain the agent's mechs are on."""
    fetcher = _Fetcher()
    fetcher.context.params.mech_chain_id = "Polygon"
    _run(fetcher, [MECH])
    fetcher.answer(_record())
    fetcher.answer(SAME_CREATOR)
    assert fetcher.sent[2]["url"] == (
        f"{MARKETPLACE_API}/polygon/ai-agents/{SERVICE_ID}/agent-card.json"
    )
    assert agent_card_url(MARKETPLACE_API + "/", "base", 7) == (
        f"{MARKETPLACE_API}/base/ai-agents/7/agent-card.json"
    )


def test_a_fresh_report_is_reused_without_new_requests() -> None:
    """Follow-up questions about the same mech hit the cache."""
    fetcher = _Fetcher()
    _full_run(fetcher)
    sent = len(fetcher.sent)

    done = _run(fetcher, [MECH])

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
    """A mech the subgraph does not list cannot be approved, and nothing more is read."""
    fetcher = _Fetcher()
    _run(fetcher, [MECH])
    fetcher.answer(NOT_INDEXED)
    assert fetcher.shared_state.mech_reports[MECH].refusal is Refusal.NOT_INDEXED
    assert len(fetcher.sent) == 1


@pytest.mark.parametrize(
    "body, status",
    [
        (b"", 500),
        (b"not json", 200),
        (["list"], 200),
        (_card("0x" + "e0" * 20), 200),
        ({"name": "Bob's mech", "skills": []}, 200),
    ],
)
def test_an_unreadable_card_is_refused_without_a_price_read(
    body: Any, status: int
) -> None:
    """A failed, non-object or mismatched card refuses approval; the price is never read."""
    fetcher = _Fetcher()
    _run(fetcher, [MECH])
    fetcher.answer(_record())
    fetcher.answer(SAME_CREATOR)
    fetcher.answer(body, status=status)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is Refusal.MANIFEST_UNREADABLE
    assert report.fetched_at == 0
    assert report.max_delivery_rate is None
    assert len(fetcher.sent) == 3


def test_a_mech_without_a_service_has_no_card_to_read() -> None:
    """No service id, no card URL: refused as unreadable after the creator read."""
    fetcher = _Fetcher()
    record = _record()
    record["data"]["meches"][0]["service"] = None
    _run(fetcher, [MECH])
    fetcher.answer(record)
    fetcher.answer(SAME_CREATOR)
    assert (
        fetcher.shared_state.mech_reports[MECH].refusal is Refusal.MANIFEST_UNREADABLE
    )
    assert len(fetcher.sent) == 2


@pytest.mark.parametrize(
    "reply",
    [
        _price(None, ERROR),
        _price(RATE, ERROR),
        _price(None),
        _price("many"),
        _price(True),
    ],
)
def test_an_unreadable_price_leaves_the_rate_unknown(reply: Any) -> None:
    """Anything but a STATE reply with an integer leaves the price unknown; the report still lands."""
    fetcher = _Fetcher()
    done = _run(fetcher, [MECH])
    fetcher.answer(_record())
    fetcher.answer(SAME_CREATOR)
    fetcher.answer(_card())
    fetcher.reply(reply)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is None
    assert (report.max_delivery_rate, report.payment_ceiling) == (None, None)
    assert report.payment_method == "xDAI"
    # a failed read is retried on the next question instead of served from the cache
    assert report.fetched_at == 0
    done.assert_called_once()


def test_a_decimal_string_rate_is_read() -> None:
    """A rate serialised as a string is still a rate."""
    fetcher = _Fetcher()
    _run(fetcher, [MECH])
    fetcher.answer(_record())
    fetcher.answer(SAME_CREATOR)
    fetcher.answer(_card())
    fetcher.reply(_price(str(RATE)))
    assert fetcher.shared_state.mech_reports[MECH].max_delivery_rate == RATE


def test_a_mech_that_never_delivered_is_refused() -> None:
    """Zero on-chain deliveries refuses approval even with a verified operator and a price."""
    fetcher = _Fetcher()
    _run(fetcher, [MECH])
    fetcher.answer(_record(self_delivered="0"))
    fetcher.answer(SAME_CREATOR)
    fetcher.answer(_card(provider=PROVIDER))
    fetcher.reply(_price(RATE))
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.refusal is Refusal.NEVER_DELIVERED
    assert report.domain_verified is True
    assert report.max_delivery_rate == RATE


def test_a_valory_mech_carries_our_figures_and_is_not_approvable() -> None:
    """Our own mechs carry the analytics link and are not offered."""
    fetcher = _Fetcher(valid=[VALORY_MECH])
    _full_run(fetcher, VALORY_MECH)
    report = fetcher.shared_state.mech_reports[VALORY_MECH]
    assert report.is_valory and not report.approvable
    assert report.analytics_url == (
        f"https://mech-analytics-api.autonolas.tech/v1/metrics/mech/100/{VALORY_MECH}"
    )


def test_a_card_without_a_provider_reads_as_not_verified() -> None:
    """No provider on the card: no operator, not verified, still approvable."""
    fetcher = _Fetcher()
    _full_run(fetcher)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.domain_verified is False
    assert (report.operator_name, report.domain) == (None, None)
    assert report.approvable


def test_a_mech_without_a_creator_skips_the_creator_read() -> None:
    """No owner in the record: the card is read next."""
    fetcher = _Fetcher()
    record = _record()
    record["data"]["meches"][0]["owner"] = None
    _run(fetcher, [MECH])
    fetcher.answer(record)
    assert fetcher.sent[1]["url"] == CARD_URL
    assert fetcher.shared_state.mech_reports == {}


def test_done_runs_once_after_every_address_is_ready() -> None:
    """Several addresses in one message are fetched together and reported together."""
    fetcher = _Fetcher()
    other = "0x" + "e0" * 20
    done = _run(fetcher, [MECH, other])
    fetcher.answer(NOT_INDEXED)
    done.assert_not_called()
    fetcher.answer(NOT_INDEXED)
    done.assert_called_once()


def test_the_store_keeps_only_the_most_recent_reports() -> None:
    """Old reports are dropped past the cap, oldest first."""
    fetcher = _Fetcher()
    addresses = [f"0x{index:040x}" for index in range(MAX_STORED_REPORTS + 1)]
    for address in addresses:
        _run(fetcher, [address])
        fetcher.answer(NOT_INDEXED)
        fetcher.shared_state.mech_reports[address].fetched_at = int(address, 16) + 1
    assert len(fetcher.shared_state.mech_reports) == MAX_STORED_REPORTS
    assert addresses[0] not in fetcher.shared_state.mech_reports


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"tell me about {MECH.upper().replace('0X', '0x')}", [MECH]),
        (f"{MECH} and {MECH} again", [MECH]),
        ("approve the Bob Labs one", []),
        ("short 0x1234 address", []),
        ("", []),
        (
            " ".join(f"0x{index:040x}" for index in range(5)),
            [f"0x{index:040x}" for index in range(3)],
        ),
    ],
)
def test_addresses_in(text: str, expected: List[str]) -> None:
    """Addresses are found case-insensitively, deduplicated and capped."""
    assert addresses_in(text) == expected


def test_an_approved_mech_carries_the_accepted_price() -> None:
    """The report shows what the user accepted next to what the mech charges now."""
    fetcher = _Fetcher(approved={MECH: RATE // 10})
    _full_run(fetcher)
    report = fetcher.shared_state.mech_reports[MECH]
    assert report.is_approved is True
    assert (report.accepted_rate, report.accepted_ceiling) == (RATE // 10, "0.001 xDAI")
    assert report.price_raised is True


def test_the_live_price_read_can_be_used_on_its_own() -> None:
    """The confirm step re-reads the price through the same request."""
    fetcher = _Fetcher()
    got = MagicMock()
    fetcher._read_max_delivery_rate(MECH, got)
    assert fetcher.sent[0]["contract_address"] == MECH
    fetcher.reply(_price(RATE + 1))
    got.assert_called_once_with(RATE + 1)
