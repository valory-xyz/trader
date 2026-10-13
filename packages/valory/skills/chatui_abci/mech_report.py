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

Built on demand in the chat handler, outside consensus, from the marketplace
subgraph record, the marketplace agent card and the mech contract's live price.
"""

import enum
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

MAX_TEXT_LENGTH = 2048
MAX_TOOLS = 50
ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")

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
    name: Optional[str] = None
    is_valory: bool = False
    is_approved: bool = False
    refusal: Optional[Refusal] = None
    operator_name: Optional[str] = None
    domain: Optional[str] = None
    domain_verified: bool = False
    created_at: Optional[str] = None
    age_days: Optional[int] = None
    same_creator_mechs: Optional[int] = None
    tools: List[str] = field(default_factory=list)
    payment_method: Optional[str] = None
    payment_ceiling: Optional[str] = None
    # the rate the user accepted when approving, rendered like payment_ceiling
    accepted_ceiling: Optional[str] = None
    received_requests: Optional[int] = None
    self_delivered: Optional[int] = None
    delivered_by_others: Optional[int] = None
    analytics_url: Optional[str] = None
    service_id: Optional[int] = None
    creator: Optional[str] = None
    # the live price in the payment asset's smallest unit, and its payment
    # type id (lowercase, no 0x); what an approval records
    max_delivery_rate: Optional[int] = None
    payment_type_id: Optional[str] = None
    accepted_rate: Optional[int] = None

    @property
    def approvable(self) -> bool:
        """Whether the user may approve this mech."""
        return self.refusal is None and not self.is_valory

    @property
    def price_raised(self) -> bool:
        """Whether an approved mech now charges more than the user accepted."""
        return (
            self.accepted_rate is not None
            and self.max_delivery_rate is not None
            and self.max_delivery_rate > self.accepted_rate
        )


@dataclass(frozen=True)
class CardFacts:
    """What the marketplace agent card says about a mech, once checked against its address."""

    name: Optional[str]
    tools: List[str]
    operator_name: Optional[str]
    domain: Optional[str]
    domain_verified: bool


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


def url_host(value: Any) -> Optional[str]:
    """Get the lowercase host of a URL, or `None` when there is none."""
    text = clean_text(value)
    if text is None:
        return None
    try:
        return urlparse(text).hostname or None
    except ValueError:
        return None


def https_url(value: Any) -> Optional[str]:
    """Accept an https URL with a host and no whitespace."""
    text = clean_text(value)
    if text is None or any(char.isspace() for char in text):
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return text


def card_names_mech(card: Dict[str, Any], address: str) -> bool:
    """Whether the card's `metadata.mechAddress` ends with the address, case-insensitively."""
    metadata = card.get("metadata")
    mech_address = metadata.get("mechAddress") if isinstance(metadata, dict) else None
    return isinstance(mech_address, str) and mech_address.lower().endswith(
        address.lower()
    )


def read_card(card: Any, address: str) -> Optional[CardFacts]:
    """Read the agent card for the mech, or `None` when it is not an object about this mech."""
    if not isinstance(card, dict) or not card_names_mech(card, address):
        return None
    skills = card.get("skills")
    names = (
        (skill.get("name") for skill in skills if isinstance(skill, dict))
        if isinstance(skills, list)
        else ()
    )
    tools = [text for text in (clean_text(name) for name in names) if text]
    provider = card.get("provider")
    operator_name = domain = None
    if isinstance(provider, dict):
        operator_name = clean_text(provider.get("organization"))
        domain = url_host(provider.get("url"))
    return CardFacts(
        name=clean_text(card.get("name")),
        tools=tools[:MAX_TOOLS],
        operator_name=operator_name,
        domain=domain,
        domain_verified=isinstance(provider, dict),
    )


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


def payment_type_id(payment_type: Any) -> Optional[str]:
    """Normalise a payment type id to lowercase hex without the 0x prefix."""
    type_id = str(payment_type or "").lower().removeprefix("0x")
    return type_id or None


def cap_for(type_id: Optional[str], caps: Mapping[Any, int]) -> Optional[int]:
    """The agent's cap for a payment type, in the asset's smallest unit.

    :param type_id: the payment type id, lowercase hex without 0x.
    :param caps: mech-interact's `delivery_rate_caps`, keyed by its payment
        type enum, whose values are the selectors with the 0x prefix.
    :return: the cap, or `None` when the asset has no cap.
    """
    if type_id is None:
        return None
    for payment_type, cap in caps.items():
        if payment_type_id(getattr(payment_type, "value", payment_type)) == type_id:
            return cap
    return None


def age_days(created_at: datetime, now: datetime) -> int:
    """Get the whole days since creation, never negative."""
    return max((now - created_at).days, 0)


def refusal_for(
    record_found: Optional[bool], card_read: bool, self_delivered: int
) -> Optional[Refusal]:
    """Decide whether a mech must be refused, in order of what is checked first.

    :param record_found: whether the subgraph lists the mech; `None` when it could not be read.
    :param card_read: whether the marketplace agent card was read and names the mech.
    :param self_delivered: the requests the mech delivered itself.
    :return: the refusal, or `None` when the mech may be approved.
    """
    if record_found is None:
        return Refusal.RECORD_UNAVAILABLE
    if not record_found:
        return Refusal.NOT_INDEXED
    if not card_read:
        return Refusal.MANIFEST_UNREADABLE
    if self_delivered <= 0:
        return Refusal.NEVER_DELIVERED
    return None


def created_at_utc(block_timestamp: Any) -> Optional[datetime]:
    """Convert a block timestamp to a UTC datetime, or `None` when unreadable."""
    try:
        return datetime.fromtimestamp(int(block_timestamp), timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
