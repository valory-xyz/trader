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

The subgraph, manifest and registry reads go through the agent's HTTP client
connection, each answered by a callback, so the handler never blocks on them.
The domain proof cannot go that way, because the connection follows redirects,
so it runs on a worker thread and is joined, with a bounded wait, once the
other reads are done.
"""

import concurrent.futures
import json
import time
from datetime import datetime, timezone
from string import Template
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from aea.protocols.base import Message

from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    HTTP_CLIENT_PUBLIC_ID,
)
from packages.valory.skills.abstract_round_abci.dialogues import HttpDialogues
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.chatui_abci.mech_report import (
    ADDRESS_PATTERN,
    ANALYTICS_MECH_URL,
    CHAIN_IDS,
    MechReport,
    PROOF_FETCH_TIMEOUT,
    ProofStatus,
    RETRYABLE_REFUSALS,
    VALORY_TERMS,
    age_days,
    created_at_utc,
    fetch_proof,
    https_url,
    payment_line,
    payment_type_id,
    read_benchmarks,
    read_operator,
    read_tools,
    refusal_for,
    verify_domain,
)

REPORT_CACHE_SECONDS = 300
# The IPFS gateway path prefix of a CIDv1 given as hex, as the manifest hash is.
CID_PREFIX = "f01701220"
# The subgraph stores the manifest hash with a ``0x`` prefix.
METADATA_PREFIX_SIZE = 2
MAX_STORED_REPORTS = 20
MAX_REPORTS_PER_PROMPT = 3
HTTP_OK = 200
JSON_HEADERS = {"Content-Type": "application/json"}

MECH_RECORD_QUERY = Template(
    '{ meches(where: {address: "$address"}) { address owner receivedRequests '
    "selfDeliveredFromReceived deliveredByOthersFromReceived maxDeliveryRate "
    "paymentType service { id metadata { metadata } } } "
    'createMeches(where: {mech: "$address"}) { blockTimestamp } }'
)
SAME_CREATOR_QUERY = Template(
    '{ meches(first: 1000, where: {owner: "$creator"}) { id } }'
)
AGENT_ID_QUERY = Template('{ service(id: "$service_id") { id erc8004Agent { id } } }')

Proof = Tuple[ProofStatus, Optional[Dict[str, Any]]]


def addresses_in(text: str) -> List[str]:
    """Get the distinct mech addresses named in the text, lowercase, in order."""
    found = (match.lower() for match in ADDRESS_PATTERN.findall(text))
    return list(dict.fromkeys(found))[:MAX_REPORTS_PER_PROMPT]


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
    """Read a subgraph integer, or `None`."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MechReportRequests:  # pylint: disable=too-few-public-methods
    """Mixin for the chat handler: build mech reports on demand, with a short cache."""

    context: Any
    shared_state: Any
    _proof_executor_instance: Optional[concurrent.futures.ThreadPoolExecutor] = None

    @property
    def _proof_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Get the worker that fetches domain proofs, starting it on first use."""
        if self._proof_executor_instance is None:
            self._proof_executor_instance = concurrent.futures.ThreadPoolExecutor(
                max_workers=2
            )
        return self._proof_executor_instance

    def _shutdown_proof_executor(self) -> None:
        """Stop the proof worker, if it was started."""
        if self._proof_executor_instance is not None:
            self._proof_executor_instance.shutdown(wait=False)
            self._proof_executor_instance = None

    @property
    def _chain_id(self) -> Optional[int]:
        """Get the id of the chain the agent's mechs are on."""
        return CHAIN_IDS.get(str(self.context.params.mech_chain_id).lower())

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
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        requests = cast(Requests, self.context.requests)
        requests.request_id_to_callback[nonce] = lambda reply, _behaviour: callback(
            reply
        )
        self.context.outbox.put_message(message=message)

    def _fetch_mech_record(self, address: str, done: Callable[[], None]) -> None:
        """Read the mech's subgraph record, then go on to its creator and manifest."""
        chain_id = self._chain_id or 0
        report = MechReport(
            address=address,
            chain_id=chain_id,
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

    def _read_record(
        self, report: MechReport, mech: Dict[str, Any], created: List[Any]
    ) -> None:
        """Copy the subgraph record into the report."""
        report.creator = str(mech.get("owner") or "").lower() or None
        report.received_requests = _as_int(mech.get("receivedRequests"))
        report.self_delivered = _as_int(mech.get("selfDeliveredFromReceived"))
        report.delivered_by_others = _as_int(mech.get("deliveredByOthersFromReceived"))
        report.payment_type_id = payment_type_id(mech.get("paymentType"))
        report.max_delivery_rate = _as_int(mech.get("maxDeliveryRate"))
        report.payment_method, report.payment_ceiling = payment_line(
            mech.get("paymentType"), mech.get("maxDeliveryRate"), report.chain_id
        )
        if report.accepted_rate is not None:
            _, report.accepted_ceiling = payment_line(
                mech.get("paymentType"), report.accepted_rate, report.chain_id
            )
        raw_service = mech.get("service")
        service: Dict[str, Any] = raw_service if isinstance(raw_service, dict) else {}
        report.service_id = _as_int(service.get("id"))
        metadata = service.get("metadata") or []
        first = metadata[0] if metadata and isinstance(metadata[0], dict) else {}
        metadata_hex = first.get("metadata")
        report.metadata_hash = (
            metadata_hex[METADATA_PREFIX_SIZE:]
            if isinstance(metadata_hex, str)
            and len(metadata_hex) > METADATA_PREFIX_SIZE
            else None
        )
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
            report.terms_sentence = VALORY_TERMS

    def _fetch_same_creator(self, report: MechReport, done: Callable[[], None]) -> None:
        """Count the other mechs created by the same address, then read the manifest."""
        if report.creator is None:
            self._fetch_manifest(report, done)
            return

        def on_creator(reply: Message) -> None:
            data = _graph_data(reply)
            meches = data.get("meches") if data else None
            if isinstance(meches, list):
                report.same_creator_mechs = max(len(meches) - 1, 0)
            self._fetch_manifest(report, done)

        self._send_report_request(
            self.context.mechs_subgraph.url,
            on_creator,
            SAME_CREATOR_QUERY.substitute(creator=report.creator),
        )

    def _fetch_manifest(self, report: MechReport, done: Callable[[], None]) -> None:
        """Read the manifest, start the domain proof, then look up the agent id."""
        if report.metadata_hash is None:
            self._finish_report(report, True, False, done)
            return

        def on_manifest(reply: Message) -> None:
            manifest = _json_body(reply)
            if not isinstance(manifest, dict):
                self._finish_report(report, True, False, done)
                return
            report.tools = read_tools(manifest)
            report.benchmarks = read_benchmarks(manifest)
            report.terms_url = https_url(manifest.get("termsUrl"))
            operator = read_operator(manifest)
            if operator is None or report.is_valory:
                self._finish_report(report, True, True, done)
                return
            report.operator_name, report.domain = operator
            proof = self._proof_executor.submit(fetch_proof, report.domain)
            self._fetch_agent_id(report, proof, done)

        self._send_report_request(
            self.context.params.ipfs_address + CID_PREFIX + report.metadata_hash,
            on_manifest,
        )

    def _fetch_agent_id(
        self,
        report: MechReport,
        proof: "concurrent.futures.Future[Proof]",
        done: Callable[[], None],
    ) -> None:
        """Look up the mech's ERC-8004 agent id, then decide the domain."""
        if report.service_id is None:
            self._decide_domain(report, None, proof, done)
            return

        def on_agent(reply: Message) -> None:
            data = _graph_data(reply)
            service = data.get("service") if data else None
            agent = service.get("erc8004Agent") if isinstance(service, dict) else None
            agent_id = _as_int(agent.get("id")) if isinstance(agent, dict) else None
            self._decide_domain(report, agent_id, proof, done)

        self._send_report_request(
            self.context.params.service_registry_subgraph_url,
            on_agent,
            AGENT_ID_QUERY.substitute(service_id=report.service_id),
        )

    def _decide_domain(
        self,
        report: MechReport,
        agent_id: Optional[int],
        proof: "concurrent.futures.Future[Proof]",
        done: Callable[[], None],
    ) -> None:
        """Join the proof, within its timeout, and record whether the domain is verified."""
        try:
            result: Optional[Proof] = proof.result(timeout=PROOF_FETCH_TIMEOUT)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            result = None
        report.domain_verified, report.domain_note = verify_domain(
            agent_id, result, report.chain_id
        )
        self._finish_report(report, True, True, done)

    def _finish_report(
        self,
        report: MechReport,
        record_found: Optional[bool],
        manifest_read: bool,
        done: Callable[[], None],
    ) -> None:
        """Decide any refusal, store the report, and signal the caller."""
        report.refusal = refusal_for(
            record_found, manifest_read, report.self_delivered or 0
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
