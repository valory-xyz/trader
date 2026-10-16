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

"""Render a mech report from its published facts and decide what it offers; no model writes this text."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from packages.valory.skills.chatui_abci.models import Offer
from packages.valory.skills.mech_interact_abci.mech_reader import (
    CardStatus,
    MechFacts,
    RecordStatus,
)
from packages.valory.skills.mech_interact_abci.payment_types import (
    NVM_PAYMENT_TYPES,
    PaymentType,
)

# A blank line between paragraphs, for readability in the chat.
PARAGRAPH_BREAK = "<br><br>"
CHAIN_NAMES = {100: "Gnosis", 137: "Polygon", 8453: "Base", 10: "Optimism"}
NATIVE_ASSETS = {100: "xDAI", 137: "POL", 8453: "ETH", 10: "ETH"}
# payment type -> (asset label, or None for the chain's native token; decimals)
TOKEN_PAYMENTS: Dict[PaymentType, Tuple[Optional[str], int]] = {
    PaymentType.NATIVE: (None, 18),
    PaymentType.TOKEN_OLAS: ("OLAS", 18),
    PaymentType.TOKEN_USDC: ("USDC", 6),
}
VALORY_TERMS = (
    "By submitting a request to this Mech, you agree to be bound by Valory AG's "
    "Mech Terms (v1.0), available at https://www.valory.xyz/terms/mechs."
)
ANALYTICS_MECH_URL = (
    "https://mech-analytics-api.autonolas.tech/v1/metrics/mech/{chain_id}/{address}"
)
OLAS_DISCLAIMER = "Olas does not check third-party mechs or their claims."
VERIFIED_MEANS = (
    "Verified means the same party controls the domain and the mech, nothing more."
)
RECORD_UNAVAILABLE = "Its record cannot be read right now; try again later."
NOT_INDEXED = "No such mech is found on this chain."
CARD_UNAVAILABLE = (
    "I can't read this mech's description right now, so I can't approve it. "
    "Try again later."
)
NO_CARD = "This mech publishes no description, so it cannot be approved."
NEVER_DELIVERED = (
    "It has never delivered an on-chain request, so it cannot be approved."
)
PRICE_UNREADABLE = "I can't read what this mech charges, so it cannot be approved."


@dataclass(frozen=True)
class Standing:
    """What this agent holds about the mech: Valory or not, its cap, the accepted rate, the pin.

    `cap` is the asset's cap as discovery bounds it before any accepted rate,
    so a raised price can be offered again up to it.
    """

    valory: bool
    cap: Optional[int]
    accepted_rate: Optional[int]
    pinnable: bool
    pinned: bool


def payment_line(
    payment_type: Any, max_delivery_rate: Any, chain_id: Optional[int]
) -> Tuple[str, Optional[str]]:
    """Name the payment asset and, where the asset is known, the per-request ceiling.

    :param payment_type: the mech's payment type id from the subgraph.
    :param max_delivery_rate: the mech's maximum delivery rate, in the asset's smallest unit.
    :param chain_id: the chain the mech is on.
    :return: the payment method and the ceiling text, or `None` when no figure can be named.
    """
    try:
        kind = PaymentType(str(payment_type).lower())
    except ValueError:
        return "an unrecognised payment method", None
    if kind in NVM_PAYMENT_TYPES:
        return "a Nevermined subscription", None
    if kind not in TOKEN_PAYMENTS:
        return "an unrecognised payment method", None
    asset, decimals = TOKEN_PAYMENTS[kind]
    asset = asset or NATIVE_ASSETS.get(chain_id or 0)
    if asset is None:
        return "the chain's native token", None
    try:
        rate = int(max_delivery_rate)
    except (TypeError, ValueError):
        return asset, None
    amount = Decimal(rate) / (Decimal(10) ** decimals)
    return asset, f"{amount.normalize():f} {asset}"


def accept_line(price_text: str, address: str) -> str:
    """The exact phrase that accepts the offer."""
    return f"To approve, reply exactly: I accept {price_text} per request for {address}"


def render_report(
    facts: MechFacts, standing: Standing, now: datetime
) -> Tuple[str, Optional[Offer]]:
    """The report, operator text escaped and paragraphs separated by a blank line, and the offer it ends with, if any."""
    method, price_text = payment_line(
        facts.payment_type, facts.max_delivery_rate, facts.chain_id
    )
    third_party_card = facts.card_read and not standing.valory
    chain = CHAIN_NAMES.get(facts.chain_id or 0) or (
        "an unknown chain" if facts.chain_id is None else f"chain {facts.chain_id}"
    )
    if facts.name:
        title = f"{escape(facts.name)}, {facts.address}, on {chain}."
    elif facts.record is RecordStatus.FOUND:
        title = f"Unnamed mech, {facts.address}, on {chain}."
    else:
        title = f"{facts.address} on {chain}."
    lines = [title]
    if third_party_card:
        lines.append(_operator_line(facts))
    if facts.created_at is not None:
        days = max((now - facts.created_at).days, 0)
        lines.append(f"Created {facts.created_at.date().isoformat()}, {days} days ago.")
    if facts.tools:
        lines.append(f"Tools: {', '.join(escape(tool) for tool in facts.tools)}.")
    if facts.record is RecordStatus.FOUND:
        ceiling = f", up to {price_text} per request" if price_text else ""
        lines.append(f"Paid with {method}{ceiling}.")
        lines.append(
            f"{facts.received_requests or 0} requests received, "
            f"{facts.self_delivered or 0} delivered by it, "
            f"{facts.delivered_by_others or 0} delivered by other mechs after it "
            "missed the deadline; off-chain requests are counted once settled."
        )
    if third_party_card:
        lines.append(OLAS_DISCLAIMER)
    ending, offers = _ending(facts, standing, method, price_text)
    lines.extend(ending)
    offer = None
    if offers and price_text is not None and facts.max_delivery_rate is not None:
        offer = Offer(
            facts.address, facts.max_delivery_rate, str(facts.payment_type), price_text
        )
    return PARAGRAPH_BREAK.join(lines), offer


def _operator_line(facts: MechFacts) -> str:
    """Who runs the mech, with the verification verdict."""
    if not facts.operator_verified:
        return "Its operator is not verified."
    parts = [
        escape(part)
        for part in (facts.operator_name, facts.operator_domain)
        if part is not None
    ]
    who = ", ".join(parts) or "its operator"
    return f"Run by {who}, verified. {VERIFIED_MEANS}"


def _pin_hint(address: str, standing: Standing) -> List[str]:
    """How to pin or unpin the mech, only when the agent may pin it."""
    if not standing.pinnable:
        return []
    if standing.pinned:
        return [f"To stop pinning it, reply: unpin {address}"]
    return [f"To add it to your pinned mechs, reply: pin {address}"]


def verdict(facts: MechFacts, standing: Standing) -> str:
    """The report's first closing line, which says where the mech stands."""
    method, price_text = payment_line(
        facts.payment_type, facts.max_delivery_rate, facts.chain_id
    )
    return _ending(facts, standing, method, price_text)[0][0]


def _ending(  # pylint: disable=too-many-return-statements
    facts: MechFacts, standing: Standing, method: str, price_text: Optional[str]
) -> Tuple[List[str], bool]:
    """The closing lines from the first verdict that applies, and whether they make an offer."""
    address = facts.address
    remove_hint = f"To stop using it, reply: remove {address}"
    if standing.valory:
        analytics = ANALYTICS_MECH_URL.format(chain_id=facts.chain_id, address=address)
        return [
            "This is a Valory mech the agent already uses; its accuracy is at "
            f"{analytics}. {VALORY_TERMS}",
            *_pin_hint(address, standing),
        ], False
    if facts.record is RecordStatus.UNAVAILABLE:
        return [RECORD_UNAVAILABLE], False
    if facts.record is RecordStatus.NOT_INDEXED:
        return [NOT_INDEXED], False
    if facts.card is CardStatus.UNAVAILABLE:
        return [CARD_UNAVAILABLE], False
    if not facts.card_read:
        return [NO_CARD], False
    if not facts.self_delivered:
        return [NEVER_DELIVERED], False
    _, cap_text = payment_line(facts.payment_type, standing.cap, facts.chain_id)
    if standing.cap is None or cap_text is None:
        return [
            f"This agent allows no mech paid with {method}, so it cannot be approved."
        ], False
    rate = facts.max_delivery_rate
    if rate is None or price_text is None:
        return [PRICE_UNREADABLE], False
    if rate > standing.cap:
        return [
            f"It charges {price_text} per request, above the {cap_text} this agent "
            "allows, so it cannot be approved."
        ], False
    accepted = standing.accepted_rate
    if accepted is not None:
        _, accepted_text = payment_line(facts.payment_type, accepted, facts.chain_id)
        if rate <= accepted:
            return [
                f"Approved at up to {accepted_text} per request.",
                remove_hint,
                *_pin_hint(address, standing),
            ], False
        return [
            f"Approved at up to {accepted_text}; it now charges up to {price_text}, "
            "so your agent has stopped using it until you accept the new price.",
            accept_line(price_text, address),
            remove_hint,
        ], True
    return [
        f"Approving accepts up to {price_text} per request. If its operator raises "
        "the price, your agent stops using this mech until you accept the new "
        "price. It starts with no track record on your side and earns work "
        "through normal scoring.",
        accept_line(price_text, address),
    ], True
