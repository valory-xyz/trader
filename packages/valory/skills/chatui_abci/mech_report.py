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

"""The report the chat shows about a mech before the user approves it.

Built on demand in the chat handler, outside consensus: the manifest and the
subgraph record are read for the one mech asked about, and the operator's
domain proof is fetched live. The rules for reading the manifest and checking
the proof match mech-client's operator report.
"""

import enum
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

PROOF_PATH = "/.well-known/agent-registration.json"
# The ERC-8004 IdentityRegistry, at the same address on every chain.
IDENTITY_REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
PROOF_FETCH_TIMEOUT = 5
PROOF_MAX_BYTES = 64 * 1024
PROOF_CHUNK_BYTES = 8 * 1024
AGENT_ID_MAX_DIGITS = 78
MAX_TEXT_LENGTH = 2048
MAX_DOMAIN_LENGTH = 253
LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
TLD_PATTERN = re.compile(r"[a-z]{1,63}|xn--[a-z0-9-]{1,59}")
ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
SECONDS_PER_DAY = 86400

CHAIN_IDS = {"gnosis": 100, "polygon": 137, "base": 8453, "optimism": 10}
NATIVE_ASSETS = {100: "xDAI", 137: "POL", 8453: "ETH", 10: "ETH"}
# payment type id (lowercase, no 0x) -> (asset label or None for native, decimals)
TOKEN_PAYMENTS = {
    "ba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1": (None, 18),
    "3679d66ef546e66ce9057c4a052f317b135bc8e8c509638f7966edfd4fcf45e9": ("OLAS", 18),
    "6406bb5f31a732f898e1ce9fdd988a80a808d36ab5d9a4a4805a8be8d197d5e3": ("USDC", 6),
}
NEVERMINED_PAYMENTS = frozenset(
    {
        "803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316",
        "0d6fd99afa9c4c580fab5e341922c2a5c4b61d880da60506193d7bf88944dd14",
    }
)
VALORY_TERMS = (
    "By submitting a request to this Mech, you agree to be bound by Valory AG's "
    "Mech Terms (v1.0), available at https://www.valory.xyz/terms/mechs."
)
ANALYTICS_MECH_URL = (
    "https://mech-analytics-api.autonolas.tech/v1/metrics/mech/{chain_id}/{address}"
)


class ProofStatus(enum.Enum):
    """What fetching an operator's domain proof found."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    REDIRECTED = "redirected"
    UNAVAILABLE = "unavailable"


class Refusal(enum.Enum):
    """Why a mech cannot be approved."""

    RECORD_UNAVAILABLE = "record_unavailable"
    NOT_INDEXED = "not_indexed"
    MANIFEST_UNREADABLE = "manifest_unreadable"
    NEVER_DELIVERED = "never_delivered"


# Refusals a retry may clear, so they are not cached.
RETRYABLE_REFUSALS = frozenset(
    {Refusal.RECORD_UNAVAILABLE, Refusal.MANIFEST_UNREADABLE}
)


@dataclass
class MechReport:  # pylint: disable=too-many-instance-attributes
    """What the chat knows about a mech, as of `fetched_at`."""

    address: str
    chain_id: int
    fetched_at: int
    is_valory: bool = False
    is_approved: bool = False
    refusal: Optional[Refusal] = None
    operator_name: Optional[str] = None
    domain: Optional[str] = None
    domain_verified: bool = False
    domain_note: Optional[str] = None
    created_at: Optional[str] = None
    age_days: Optional[int] = None
    same_creator_mechs: Optional[int] = None
    tools: List[str] = field(default_factory=list)
    payment_method: Optional[str] = None
    payment_ceiling: Optional[str] = None
    received_requests: Optional[int] = None
    self_delivered: Optional[int] = None
    delivered_by_others: Optional[int] = None
    benchmarks: Dict[str, str] = field(default_factory=dict)
    terms_url: Optional[str] = None
    terms_sentence: Optional[str] = None
    analytics_url: Optional[str] = None
    # set while being built, not shown
    service_id: Optional[int] = None
    creator: Optional[str] = None
    metadata_hash: Optional[str] = None

    @property
    def approvable(self) -> bool:
        """Whether the user may approve this mech."""
        return self.refusal is None and not self.is_valory

    def to_prompt(self) -> Dict[str, Any]:
        """Render the facts the chat may show, dropping build-only fields."""
        facts = asdict(self)
        for key in ("fetched_at", "service_id", "creator", "metadata_hash"):
            facts.pop(key)
        facts["refusal"] = self.refusal.value if self.refusal else None
        facts["approvable"] = self.approvable
        return facts


def clean_text(value: Any) -> Optional[str]:
    """Accept stripped, non-empty, printable text of at most 2048 characters."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_TEXT_LENGTH:
        return None
    if any(unicodedata.category(char).startswith("C") for char in text):
        return None
    return text


def hostname(value: Any) -> Optional[str]:
    """Accept a bare lowercase hostname: no scheme, port, path or trailing dot."""
    if not isinstance(value, str):
        return None
    host = value.strip()
    if len(host) > MAX_DOMAIN_LENGTH or "." not in host:
        return None
    labels = host.split(".")
    if not all(LABEL_PATTERN.fullmatch(label) for label in labels):
        return None
    if not TLD_PATTERN.fullmatch(labels[-1]):
        return None
    return host


def https_url(value: Any) -> Optional[str]:
    """Accept an https URL with a host and no whitespace."""
    text = clean_text(value)
    if text is None or any(char.isspace() for char in text):
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return text


def read_operator(manifest: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Get the operator's name and domain, or `None` unless both are usable."""
    operator = manifest.get("operator")
    if not isinstance(operator, dict):
        return None
    name = clean_text(operator.get("name"))
    domain = hostname(operator.get("domain"))
    if name is None or domain is None:
        return None
    return name, domain


def read_tools(manifest: Dict[str, Any]) -> List[str]:
    """Get the tool names the manifest lists."""
    tools = manifest.get("tools")
    if not isinstance(tools, list):
        return []
    return [text for text in (clean_text(tool) for tool in tools) if text]


def read_benchmarks(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Get each tool's benchmark link; a tool without a usable https link is left out.

    Only the link is read: a benchmark is the operator's claim, shown live
    through its link, never as a stored figure.
    """
    metadata = manifest.get("toolMetadata")
    if not isinstance(metadata, dict):
        return {}
    links: Dict[str, str] = {}
    for tool, meta in sorted(metadata.items()):
        benchmark = meta.get("benchmark") if isinstance(meta, dict) else None
        url = https_url(benchmark.get("url")) if isinstance(benchmark, dict) else None
        if url is not None:
            links[str(tool)] = url
    return links


def payment_line(
    payment_type: Any, max_delivery_rate: Any, chain_id: int
) -> Tuple[str, Optional[str]]:
    """Name the payment asset and, where the asset is known, the per-request ceiling.

    :param payment_type: the mech's payment type id from the subgraph.
    :param max_delivery_rate: the mech's maximum delivery rate, in the asset's smallest unit.
    :param chain_id: the chain the mech is on.
    :return: the payment method and the ceiling text, or `None` when no figure can be named.
    """
    type_id = str(payment_type or "").lower().removeprefix("0x")
    if type_id in NEVERMINED_PAYMENTS:
        return "a Nevermined subscription", None
    if type_id not in TOKEN_PAYMENTS:
        return "an unrecognised payment method", None
    asset, decimals = TOKEN_PAYMENTS[type_id]
    asset = asset or NATIVE_ASSETS.get(chain_id)
    if asset is None:
        return "the chain's native token", None
    try:
        rate = int(max_delivery_rate)
    except (TypeError, ValueError):
        return asset, None
    amount = Decimal(rate) / (Decimal(10) ** decimals)
    return asset, f"{amount.normalize():f} {asset}"


def age_days(created_at: datetime, now: datetime) -> int:
    """Get the whole days since creation, never negative."""
    return max((now - created_at).days, 0)


def refusal_for(
    record_found: Optional[bool], manifest_read: bool, self_delivered: int
) -> Optional[Refusal]:
    """Decide whether a mech must be refused, in order of what is checked first.

    :param record_found: whether the subgraph lists the mech; `None` when it could not be read.
    :param manifest_read: whether the manifest was read.
    :param self_delivered: the requests the mech delivered itself.
    :return: the refusal, or `None` when the mech may be approved.
    """
    if record_found is None:
        return Refusal.RECORD_UNAVAILABLE
    if not record_found:
        return Refusal.NOT_INDEXED
    if not manifest_read:
        return Refusal.MANIFEST_UNREADABLE
    if self_delivered <= 0:
        return Refusal.NEVER_DELIVERED
    return None


def proof_url(domain: str) -> str:
    """Get the URL the operator's domain publishes its proof at."""
    return f"https://{domain}{PROOF_PATH}"


def fetch_proof(domain: str) -> Tuple[ProofStatus, Optional[Dict[str, Any]]]:
    """Fetch the domain's proof: exact host, https, no redirects, at most 64 KB."""
    try:
        response = requests.get(
            proof_url(domain),
            timeout=PROOF_FETCH_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException:
        return ProofStatus.UNAVAILABLE, None
    with response:
        if response.status_code >= 500:
            return ProofStatus.UNAVAILABLE, None
        if 300 <= response.status_code < 400:
            return ProofStatus.REDIRECTED, None
        if not 200 <= response.status_code < 300:
            return ProofStatus.NOT_FOUND, None
        body = b""
        try:
            for chunk in response.iter_content(PROOF_CHUNK_BYTES):
                body += chunk
                if len(body) > PROOF_MAX_BYTES:
                    return ProofStatus.NOT_FOUND, None
        except requests.RequestException:
            return ProofStatus.UNAVAILABLE, None
    try:
        document = json.loads(body)
    except (ValueError, RecursionError):
        return ProofStatus.NOT_FOUND, None
    if not isinstance(document, dict):
        return ProofStatus.NOT_FOUND, None
    return ProofStatus.FOUND, document


def _agent_id_of(entry: Any) -> Optional[int]:
    """Read a registration's agent id, as an int or a decimal string."""
    if not isinstance(entry, dict):
        return None
    agent_id = entry.get("agentId")
    if isinstance(agent_id, bool):
        return None
    if isinstance(agent_id, int):
        return agent_id
    if (
        isinstance(agent_id, str)
        and agent_id.isascii()
        and agent_id.isdigit()
        and len(agent_id) <= AGENT_ID_MAX_DIGITS
    ):
        return int(agent_id)
    return None


def proof_matches(proof: Dict[str, Any], agent_id: int, chain_id: int) -> bool:
    """Check that the proof lists the agent id under the chain's identity registry."""
    registrations = proof.get("registrations")
    if not isinstance(registrations, list):
        return False
    expected = f"eip155:{chain_id}:{IDENTITY_REGISTRY}".lower()
    for entry in registrations:
        if _agent_id_of(entry) != agent_id:
            continue
        registry = entry.get("agentRegistry")
        if isinstance(registry, str) and registry.lower() == expected:
            return True
    return False


def verify_domain(
    agent_id: Optional[int],
    proof: Optional[Tuple[ProofStatus, Optional[Dict[str, Any]]]],
    chain_id: int,
) -> Tuple[bool, Optional[str]]:
    """Decide whether the domain is verified, with the reason when it is not.

    :param agent_id: the mech's ERC-8004 agent id, `None` when it has none or it could not be read.
    :param proof: the result of `fetch_proof`, `None` when it could not be run.
    :param chain_id: the chain the mech is on.
    :return: whether the domain is verified, and a note when it is not.
    """
    if agent_id is None:
        return False, "the mech has no ERC-8004 identity to match the domain against"
    if proof is None:
        return False, "the domain could not be checked"
    status, document = proof
    if status is ProofStatus.UNAVAILABLE:
        return False, "the domain could not be reached for its proof"
    if status is ProofStatus.REDIRECTED:
        return False, "the domain redirects the proof request to another host"
    if status is ProofStatus.NOT_FOUND or document is None:
        return False, "the domain publishes no proof for this mech"
    if not proof_matches(document, agent_id, chain_id):
        return False, "the domain's proof does not list this mech"
    return True, None


def created_at_utc(block_timestamp: Any) -> Optional[datetime]:
    """Convert a block timestamp to a UTC datetime, or `None` when unreadable."""
    try:
        return datetime.fromtimestamp(int(block_timestamp), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
