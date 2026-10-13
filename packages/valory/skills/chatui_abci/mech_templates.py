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

"""Render a mech report and its consent card; no model writes any of this text."""

from html import escape
from typing import List, Optional, Tuple

from packages.valory.skills.chatui_abci.mech_report import (
    MechReport,
    Refusal,
    VALORY_TERMS,
    payment_line,
)

LINE_BREAK = "<br>"
CHAIN_NAMES = {100: "Gnosis", 137: "Polygon", 8453: "Base", 10: "Optimism"}
OLAS_DISCLAIMER = "Olas does not check third-party mechs or their claims."
VERIFIED_MEANS = (
    "Verified means the same party controls the domain and the mech, nothing more."
)
REFUSAL_SENTENCES = {
    Refusal.NEVER_DELIVERED: (
        "It has never delivered an on-chain request, so it cannot be approved."
    ),
    Refusal.NOT_INDEXED: "No such mech is found on this chain.",
    Refusal.RECORD_UNAVAILABLE: "Its record cannot be read right now; try again later.",
    Refusal.MANIFEST_UNREADABLE: (
        "I can't read this mech's description, so I can't approve it. Try again later."
    ),
}
PRICE_UNREADABLE = "I can't read what this mech charges, so it cannot be approved."
ASK_ALONE = "To approve one of these, ask about it on its own."
# Refusals under which no card was read, so there is no operator or claim to report.
_NO_CARD = frozenset(
    {Refusal.RECORD_UNAVAILABLE, Refusal.NOT_INDEXED, Refusal.MANIFEST_UNREADABLE}
)


def render_consent(report: MechReport) -> str:
    """The exact terms the user accepts by confirming."""
    return (
        f"Approving accepts up to {report.payment_ceiling} per request for "
        f"{report.address}. If its operator raises the price, your agent stops "
        "using this mech until you approve the new price. It starts with no track "
        "record on your side and earns work through normal scoring. Reply to confirm."
    )


def offers_consent(report: MechReport, cap: Optional[int]) -> bool:
    """Whether the mech can be approved now, so a report shown alone ends with a consent card."""
    return _ending(report, cap, offer=True)[1]


def render_report(report: MechReport, cap: Optional[int], offer: bool = True) -> str:
    """One short message about the mech, operator text escaped, ending in a verdict.

    :param report: the report to render.
    :param cap: the agent's cap for the mech's payment asset, or `None` when it has none.
    :param offer: whether an approvable mech gets its consent card; `False` when several
        mechs share one reply, so a yes could not name one.
    :return: the message, lines joined with ``<br>``.
    """
    lines = [
        f"{escape(report.name) if report.name else 'Unnamed mech'}, "
        f"{report.address}, on {_chain_name(report.chain_id)}."
    ]
    third_party_card = not report.is_valory and report.refusal not in _NO_CARD
    if third_party_card:
        lines.append(_operator_line(report))
    if report.created_at is not None:
        lines.append(_created_line(report))
    if report.tools:
        lines.append(f"Tools: {', '.join(escape(tool) for tool in report.tools)}.")
    if report.payment_method is not None:
        ceiling = (
            f", up to {report.payment_ceiling} per request"
            if report.payment_ceiling is not None
            else ""
        )
        lines.append(f"Paid with {report.payment_method}{ceiling}.")
    if report.received_requests is not None:
        lines.append(_record_line(report))
    if third_party_card:
        lines.append(OLAS_DISCLAIMER)
    lines.append(_ending(report, cap, offer)[0])
    return LINE_BREAK.join(lines)


def _chain_name(chain_id: int) -> str:
    """Name the chain, or give its id."""
    return CHAIN_NAMES.get(chain_id, f"chain {chain_id}")


def _operator_line(report: MechReport) -> str:
    """Who runs the mech, with the verification verdict."""
    if not report.domain_verified:
        return "Its operator is not verified."
    parts: List[str] = []
    if report.operator_name:
        parts.append(escape(report.operator_name))
    if report.domain:
        parts.append(escape(report.domain))
    who = ", ".join(parts) or "its operator"
    return f"Run by {who}, verified. {VERIFIED_MEANS}"


def _created_line(report: MechReport) -> str:
    """When the mech was created, and how many other mechs its creator made."""
    age = f", {report.age_days} days ago" if report.age_days is not None else ""
    same = (
        f", created by the same address as {report.same_creator_mechs} other mechs"
        if report.same_creator_mechs is not None
        else ""
    )
    return f"Created {report.created_at}{age}{same}."


def _record_line(report: MechReport) -> str:
    """The mech's delivery record."""
    return (
        f"{report.received_requests} requests received, "
        f"{report.self_delivered or 0} delivered by it, "
        f"{report.delivered_by_others or 0} delivered by other mechs after it "
        "missed the deadline; off-chain requests are counted once settled."
    )


def _ending(report: MechReport, cap: Optional[int], offer: bool) -> Tuple[str, bool]:
    """The verdict, and whether the mech can be approved now."""
    if report.is_valory:
        return (
            "This is a Valory mech the agent already uses; its accuracy is at "
            f"{report.analytics_url}. {VALORY_TERMS}",
            False,
        )
    if report.refusal is not None:
        return REFUSAL_SENTENCES[report.refusal], False
    if report.max_delivery_rate is None or report.payment_ceiling is None:
        return PRICE_UNREADABLE, False
    if cap is None or report.max_delivery_rate > cap:
        _, allowed = payment_line(report.payment_type_id, cap, report.chain_id)
        if allowed is None:
            return (
                f"This agent allows no mech paid with {report.payment_method}, "
                "so it cannot be approved.",
                False,
            )
        return (
            f"It charges {report.payment_ceiling} per request, above the "
            f"{allowed} this agent allows, so it cannot be approved.",
            False,
        )
    if report.is_approved and not report.price_raised:
        return (
            f"Approved at up to {report.accepted_ceiling} per request. "
            "Say remove to remove it.",
            False,
        )
    if report.is_approved:
        raised = (
            f"Approved at up to {report.accepted_ceiling}; it now charges up to "
            f"{report.payment_ceiling}, so your agent has stopped using it until "
            "you approve the new price."
        )
        return (f"{raised} {render_consent(report)}" if offer else raised), True
    return (render_consent(report) if offer else "It can be approved."), True
