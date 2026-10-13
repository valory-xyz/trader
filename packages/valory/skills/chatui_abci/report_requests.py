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

"""Fetch mech reports from the chat handler, outside consensus.

The subgraph and the marketplace agent card are read through the HTTP client
connection and the live price through the ledger connection, each answered by
a callback, so the handler never blocks on them.
"""

import json
import time
from datetime import datetime, timezone
from string import Template
from typing import Any, Callable, Dict, List, Optional, cast

from aea.protocols.base import Message

from packages.valory.contracts.mech_mm.contract import MechMM
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    HTTP_CLIENT_PUBLIC_ID,
    LEDGER_API_ADDRESS,
)
from packages.valory.skills.abstract_round_abci.dialogues import (
    ContractApiDialogues,
    HttpDialogues,
)
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.chatui_abci.mech_report import (
    ADDRESS_PATTERN,
    ANALYTICS_MECH_URL,
    CHAIN_IDS,
    MechReport,
    RETRYABLE_REFUSALS,
    age_days,
    created_at_utc,
    payment_line,
    payment_type_id,
    read_card,
    refusal_for,
)

REPORT_CACHE_SECONDS = 300
MAX_STORED_REPORTS = 20
MAX_REPORTS_PER_PROMPT = 3
HTTP_OK = 200
JSON_HEADERS = {"Content-Type": "application/json"}
MAX_DELIVERY_RATE_CALLABLE = "get_max_delivery_rate"
MAX_DELIVERY_RATE_KEY = "max_delivery_rate"

MECH_RECORD_QUERY = Template(
    '{ meches(where: {address: "$address"}) { address owner receivedRequests '
    "selfDeliveredFromReceived deliveredByOthersFromReceived paymentType "
    "service { id } } "
    'createMeches(where: {mech: "$address"}) { blockTimestamp } }'
)
SAME_CREATOR_QUERY = Template(
    '{ meches(first: 1000, where: {owner: "$creator"}) { id } }'
)


def addresses_in(text: str) -> List[str]:
    """Get the distinct mech addresses named in the text, lowercase, in order."""
    found = (match.lower() for match in ADDRESS_PATTERN.findall(text))
    return list(dict.fromkeys(found))[:MAX_REPORTS_PER_PROMPT]


def agent_card_url(api_url: str, network: str, service_id: int) -> str:
    """The marketplace agent card of the service on the network."""
    return f"{api_url.rstrip('/')}/{network}/ai-agents/{service_id}/agent-card.json"


def _json_body(message: Message) -> Optional[Any]:
    """Decode a successful HTTP response's JSON body, or `None`."""
    http_message = cast(HttpMessage, message)
    if http_message.status_code != HTTP_OK:
        return None
    try:
        return json.loads(http_message.body)
    except (ValueError, TypeError, RecursionError):
        return None


def _graph_data(message: Message) -> Optional[Dict[str, Any]]:
    """Get a GraphQL response's `data`, or `None` when the call failed."""
    body = _json_body(message)
    if not isinstance(body, dict) or body.get("errors"):
        return None
    data = body.get("data")
    return data if isinstance(data, dict) else None


def _as_int(value: Any) -> Optional[int]:
    """Read an integer given as a number or a decimal string, or `None`."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _state_int(message: Message, key: str) -> Optional[int]:
    """Read an integer from a contract `STATE` reply's body, or `None` for any other reply."""
    reply = cast(ContractApiMessage, message)
    if reply.performative != ContractApiMessage.Performative.STATE:
        return None
    body = reply.state.body or {}
    return _as_int(body.get(key))


class MechReportRequests:  # pylint: disable=too-few-public-methods
    """Mixin for the chat handler: build mech reports on demand, with a short cache."""

    context: Any
    shared_state: Any

    @property
    def _chain_id(self) -> Optional[int]:
        """Get the id of the chain the agent's mechs are on."""
        return CHAIN_IDS.get(self._network)

    @property
    def _network(self) -> str:
        """Get the lowercase name of the chain the agent's mechs are on."""
        return str(self.context.params.mech_chain_id).lower()

    def _fresh_report(self, address: str) -> Optional[MechReport]:
        """Get the stored report for the address while it is fresh."""
        report = self.shared_state.mech_reports.get(address)
        if report is None or time.time() - report.fetched_at > REPORT_CACHE_SECONDS:
            return None
        return report

    def _with_mech_reports(
        self, addresses: List[str], done: Callable[[], None]
    ) -> None:
        """Make sure each address has a fresh report, then call `done` once."""
        missing = [
            address for address in addresses if self._fresh_report(address) is None
        ]
        if not missing:
            done()
            return
        remaining = {"count": len(missing)}

        def one_done() -> None:
            remaining["count"] -= 1
            if remaining["count"] == 0:
                done()

        for address in missing:
            self._fetch_mech_record(address, one_done)

    def _register_callback(
        self, nonce: str, callback: Callable[[Message], None]
    ) -> None:
        """Have the reply to the request with this nonce passed to `callback`."""
        requests = cast(Requests, self.context.requests)
        requests.request_id_to_callback[nonce] = lambda reply, _behaviour: callback(
            reply
        )

    def _send_report_request(
        self,
        url: str,
        callback: Callable[[Message], None],
        query: Optional[str] = None,
    ) -> None:
        """Send an HTTP request through the client connection; `callback` gets the reply."""
        http_dialogues = cast(HttpDialogues, self.context.http_dialogues)
        message, dialogue = http_dialogues.create(
            counterparty=str(HTTP_CLIENT_PUBLIC_ID),
            performative=HttpMessage.Performative.REQUEST,
            method="POST" if query is not None else "GET",
            url=url,
            headers=(
                "".join(f"{key}: {val}\r\n" for key, val in JSON_HEADERS.items())
                if query is not None
                else ""
            ),
            version="",
            body=json.dumps({"query": query}).encode() if query is not None else b"",
        )
        self._register_callback(dialogue.dialogue_label.dialogue_reference[0], callback)
        self.context.outbox.put_message(message=message)

    def _read_max_delivery_rate(
        self, address: str, callback: Callable[[Optional[int]], None]
    ) -> None:
        """Read the mech's live `maxDeliveryRate`; `callback` gets it, or `None` when unreadable."""
        contract_api_dialogues = cast(
            ContractApiDialogues, self.context.contract_api_dialogues
        )
        message, dialogue = contract_api_dialogues.create(
            counterparty=LEDGER_API_ADDRESS,
            performative=ContractApiMessage.Performative.GET_STATE,
            ledger_id=self.context.default_ledger_id,
            contract_id=str(MechMM.contract_id),
            contract_address=address,
            callable=MAX_DELIVERY_RATE_CALLABLE,
            kwargs=ContractApiMessage.Kwargs(
                {"chain_id": str(self.context.params.mech_chain_id)}
            ),
        )

        def on_reply(reply: Message) -> None:
            rate = _state_int(reply, MAX_DELIVERY_RATE_KEY)
            if rate is None:
                self.context.logger.warning(
                    f"Could not read maxDeliveryRate of {address}: {reply}"
                )
            callback(rate)

        self._register_callback(dialogue.dialogue_label.dialogue_reference[0], on_reply)
        self.context.outbox.put_message(message=message)

    def _fetch_mech_record(self, address: str, done: Callable[[], None]) -> None:
        """Read the mech's subgraph record, then go on to its creator, card and price."""
        report = MechReport(
            address=address,
            chain_id=self._chain_id or 0,
            fetched_at=int(time.time()),
            is_valory=address in self.context.params.valid_mechs,
            is_approved=address in self.shared_state.approved_mechs,
            accepted_rate=self.shared_state.approved_mech_rates.get(address),
        )

        def on_record(reply: Message) -> None:
            data = _graph_data(reply)
            if data is None:
                self._finish_report(report, None, False, done)
                return
            meches = data.get("meches") or []
            created = data.get("createMeches") or []
            if not meches or not isinstance(meches[0], dict):
                self._finish_report(report, False, False, done)
                return
            self._read_record(report, meches[0], created)
            self._fetch_same_creator(report, done)

        self._send_report_request(
            self.context.mechs_subgraph.url,
            on_record,
            MECH_RECORD_QUERY.substitute(address=address),
        )

    @staticmethod
    def _read_record(
        report: MechReport, mech: Dict[str, Any], created: List[Any]
    ) -> None:
        """Copy the subgraph record into the report."""
        report.creator = str(mech.get("owner") or "").lower() or None
        report.received_requests = _as_int(mech.get("receivedRequests"))
        report.self_delivered = _as_int(mech.get("selfDeliveredFromReceived"))
        report.delivered_by_others = _as_int(mech.get("deliveredByOthersFromReceived"))
        report.payment_type_id = payment_type_id(mech.get("paymentType"))
        report.payment_method, _ = payment_line(
            report.payment_type_id, None, report.chain_id
        )
        if report.accepted_rate is not None:
            _, report.accepted_ceiling = payment_line(
                report.payment_type_id, report.accepted_rate, report.chain_id
            )
        raw_service = mech.get("service")
        service: Dict[str, Any] = raw_service if isinstance(raw_service, dict) else {}
        report.service_id = _as_int(service.get("id"))
        created_at = (
            created_at_utc(created[0].get("blockTimestamp"))
            if created and isinstance(created[0], dict)
            else None
        )
        if created_at is not None:
            report.created_at = created_at.date().isoformat()
            report.age_days = age_days(created_at, datetime.now(timezone.utc))
        if report.is_valory:
            report.analytics_url = ANALYTICS_MECH_URL.format(
                chain_id=report.chain_id, address=report.address
            )

    def _fetch_same_creator(self, report: MechReport, done: Callable[[], None]) -> None:
        """Count the other mechs created by the same address, then read the card."""
        if report.creator is None:
            self._fetch_card(report, done)
            return

        def on_creator(reply: Message) -> None:
            data = _graph_data(reply)
            meches = data.get("meches") if data else None
            if isinstance(meches, list):
                report.same_creator_mechs = max(len(meches) - 1, 0)
            self._fetch_card(report, done)

        self._send_report_request(
            self.context.mechs_subgraph.url,
            on_creator,
            SAME_CREATOR_QUERY.substitute(creator=report.creator),
        )

    def _fetch_card(self, report: MechReport, done: Callable[[], None]) -> None:
        """Read the marketplace agent card, then the live price."""
        if report.service_id is None:
            self._finish_report(report, True, False, done)
            return

        def on_card(reply: Message) -> None:
            facts = read_card(_json_body(reply), report.address)
            if facts is None:
                self._finish_report(report, True, False, done)
                return
            report.name = facts.name
            report.tools = facts.tools
            report.operator_name = facts.operator_name
            report.domain = facts.domain
            report.domain_verified = facts.domain_verified
            self._fetch_price(report, done)

        self._send_report_request(
            agent_card_url(
                self.context.params.marketplace_api_url,
                self._network,
                report.service_id,
            ),
            on_card,
        )

    def _fetch_price(self, report: MechReport, done: Callable[[], None]) -> None:
        """Read the live price from the mech contract, then finish the report."""

        def on_price(rate: Optional[int]) -> None:
            report.max_delivery_rate = rate
            report.payment_method, report.payment_ceiling = payment_line(
                report.payment_type_id, rate, report.chain_id
            )
            if rate is None:
                # kept for the conversation, but refetched on the next question
                report.fetched_at = 0
            self._finish_report(report, True, True, done)

        self._read_max_delivery_rate(report.address, on_price)

    def _finish_report(
        self,
        report: MechReport,
        record_found: Optional[bool],
        card_read: bool,
        done: Callable[[], None],
    ) -> None:
        """Decide any refusal, store the report, and signal the caller."""
        report.refusal = refusal_for(
            record_found, card_read, report.self_delivered or 0
        )
        if report.refusal in RETRYABLE_REFUSALS:
            # kept for the conversation, but refetched on the next question
            report.fetched_at = 0
        stored: Dict[str, MechReport] = self.shared_state.mech_reports
        stored[report.address] = report
        while len(stored) > MAX_STORED_REPORTS:
            oldest = min(stored, key=lambda address: stored[address].fetched_at)
            del stored[oldest]
        done()
