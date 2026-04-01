#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2026 Valory AG
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

"""Analyze Pearl log bundles and emit a compact structured report."""

# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
# pylint: disable=too-many-locals
# pylint: disable=too-many-instance-attributes
# pylint: disable=broad-exception-caught
# pylint: disable=too-many-statements
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-nested-blocks
# pylint: disable=chained-comparison
# pylint: disable=too-many-boolean-expressions

from __future__ import annotations

import argparse
import json
import math
import re
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

TIMESTAMP_RE = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}\]")
PEARL_VERSION_RE = re.compile(r"Pearl/(?P<version>[\w\.\-]+)")
CHATUI_RE = re.compile(
    r"Loaded chat UI parameters: ChatuiConfig\("
    r"trading_strategy='(?P<trading_strategy>[^']+)', "
    r"initial_trading_strategy='(?P<initial_trading_strategy>[^']+)', "
    r"allowed_tools=\[(?P<allowed_tools>[^\]]*)\], "
    r"fixed_bet_size=(?P<fixed_bet_size>[^,]+), "
    r"max_bet_size=(?P<max_bet_size>[^\)]+)\)"
)
FETCHED_MARKETS_RE = re.compile(
    r"Fetched (?P<count>\d+) Yes/No markets across (?P<categories>\d+) categories"
)
CONSTRUCTED_BETS_RE = re.compile(
    r"Constructed (?P<constructed>\d+) bet_dicts from (?P<total>\d+) total markets "
    r"\((?P<skipped>\d+) skipped, (?P<blacklisted>\d+) blacklisted"
)
CATEGORY_RE = re.compile(
    r"Category '(?P<category>[^']+)': (?P<valid>\d+)/(?P<total>\d+) validated "
    r"\((?P<invalid>\d+) failed\)"
)
TRADES_RE = re.compile(
    r"Fetched total of (?P<count>\d+) trades for (?P<agent>0x[a-fA-F0-9]+)"
)
POSITIONS_RE = re.compile(
    r"Fetched total of (?P<count>\d+) positions for (?P<agent>0x[a-fA-F0-9]+)"
)
REDEEMABLE_RE = re.compile(r"Fetched (?P<count>\d+) redeemable positions")
PERF_RE = re.compile(
    r'"metrics": \{'
    r'"all_time_funds_used": (?P<funds_used>[-\d\.]+), '
    r'"all_time_profit": (?P<profit>[-\d\.]+), '
    r'"funds_locked_in_markets": (?P<locked>[-\d\.]+), '
    r'"available_funds": (?P<available>[-\d\.]+), '
    r'"roi": (?P<roi>[-\d\.]+), '
    r'"settled_mech_request_count": (?P<settled>\d+), '
    r'"total_mech_request_count": (?P<total>\d+), '
    r'"open_mech_request_count": (?P<open>\d+), '
    r'"placed_mech_request_count": (?P<placed>\d+)'
)
BET_TOTAL_RE = re.compile(r'"total": (?P<total>\d+), "items": \[')
MECH_V2_RE = re.compile(r"supports v2 features")
MARKETPLACE_RE = re.compile(r"self\.marketplace_address='(?P<address>0x[a-fA-F0-9]+)'")
POL_RATE_RE = re.compile(
    r"POL→USDC conversion: (?P<pol>[-\d\.]+) POL .* \(rate: 1 POL = (?P<rate>[-\d\.]+) USDC\)"
)
BALANCE_RE = re.compile(
    r"Calculated balances: token_balance=(?P<token>[-\d\.]+), "
    r"native_balance_converted=(?P<native>[-\d\.]+), "
    r"available_funds=(?P<available>[-\d\.]+)"
)
PREDICTION_HISTORY_ITEM_RE = re.compile(
    r'"items": \[\{"id": "(?P<id>[^"]+)", '
    r'"market": \{.*?"title": "(?P<title>[^"]+)"\}, '
    r'"prediction_side": "(?P<prediction_side>[^"]+)", '
    r'"bet_amount": (?P<bet_amount>[-\d\.]+), '
    r'"status": "(?P<status>[^"]+)", '
    r'"net_profit": (?P<net_profit>[-\d\.]+), '
    r'"created_at": "(?P<created_at>[^"]+)"'
)
POSITION_DETAILS_RE = re.compile(
    r'"question": "(?P<question>[^"]+)", .*'
    r'"total_bet": (?P<total_bet>[-\d\.]+), '
    r'"payout": (?P<payout>[-\d\.]+), .*'
    r'"status": "(?P<status>[^"]+)", .*'
    r'"bet": \{"amount": (?P<amount>[-\d\.]+), "side": "(?P<side>[^"]+)", '
    r'"placed_at": "(?P<placed_at>[^"]+)"\}, '
    r'"intelligence": \{"prediction_tool": "(?P<prediction_tool>[^"]+)", '
    r'"implied_probability": (?P<implied_probability>[-\d\.]+)'
)
RUNTIME_BET_AMOUNT_RE = re.compile(r"Bet amount: (?P<bet_amount>\d+)")
RUNTIME_APPROVED_BET_RE = re.compile(
    r"Strategy approved bet: (?P<bet_amount_native>[-\d\.]+) (?P<token>\w+) "
    r"on (?P<side>YES|NO), expected_profit=(?P<expected_profit_native>[-\d\.]+) (?P=token)"
)
RUNTIME_NO_BET_RE = re.compile(
    r"Strategy returned no bet \(bet_amount <= 0 or no vote\)\."
)
RUNTIME_SIDE_DIAGNOSTIC_RE = re.compile(r"(?P<label>yes|no): (?P<message>.+)")
RUNTIME_NO_TRADE_REASON_RE = re.compile(r"No trade: (?P<reason>.+)")
RUNTIME_MAX_BET_RE = re.compile(
    r"max_bet: (?P<max_bet>[-\d\.]+), n_bets: (?P<n_bets>\d+), min_edge: (?P<min_edge>[-\d\.]+)"
)
USED_TRADING_STRATEGY_RE = re.compile(r"Used trading strategy: (?P<strategy>[\w_]+)")
RUNTIME_P_YES_RE = re.compile(
    r"market_type: (?P<market_type>\w+), p_yes: (?P<p_yes>[-\d\.]+)"
)
RUNTIME_SELECTED_RE = re.compile(
    r"Selected (?P<label>yes|no): bet=(?P<bet>[-\d\.]+) (?P<token>\w+), "
    r"shares=(?P<shares>[-\d\.]+), expected_profit=(?P<expected_profit>[-\d\.]+) (?P=token), "
    r"G_improvement=(?P<g_improvement>[-\d\.]+)"
)
PREDICTION_ACCURACY_RE = re.compile(
    r'"prediction_accuracy": (?P<prediction_accuracy>[-\d\.]+)'
)
PREPARED_METADATA_RE = re.compile(r"'tool': '(?P<tool>[^']+)'")
PREPARED_METADATA_QUESTION_RE = re.compile(
    r'With the given question "(?P<question>.+?)" and the `yes` option represented'
)
BET_CONTEXT_RE = re.compile(
    r"title='(?P<title>[^']+)'.*?"
    r"outcomeTokenMarginalPrices=\[(?P<price_yes>[-\d\.]+), (?P<price_no>[-\d\.]+)\].*?"
    r"outcome_token_ids=\{'Yes': '(?P<yes_token>[^']+)', 'No': '(?P<no_token>[^']+)'\}"
)
ORDERBOOK_REQUEST_RE = re.compile(
    r"Payload data: \{'request_type': 'fetch_order_book', 'params': \{'token_id': '(?P<token_id>\d+)'\}\}"
)
ORDERBOOK_RESPONSE_RE = re.compile(
    r'payload=\{"asks": \[(?P<asks>.*?)\], "bids":',
)
ORDERBOOK_LEVEL_RE = re.compile(
    r'"price": "(?P<price>[-\d\.]+)", "size": "(?P<size>[-\d\.]+)"'
)
SIDE_METRICS_RE = re.compile(
    r"(?P<label>yes|no): spend=(?P<spend>[-\d\.]+), shares=(?P<shares>[-\d\.]+), "
    r"vwap=(?P<vwap>[-\d\.]+), edge=(?P<edge>[+\-][-\d\.]+), "
    r"G_improvement=(?P<g_improvement>[-\d\.]+)"
)
MECH_RESPONSE_RESULT_RE = re.compile(
    r'Received mech responses: .*?"result": "\{\\n  \\"p_yes\\": (?P<p_yes>[-\d\.]+),\\n  \\"p_no\\": (?P<p_no>[-\d\.]+),\\n  \\"confidence\\": (?P<confidence>[-\d\.]+),\\n  \\"info_utility\\": (?P<info_utility>[-\d\.]+)\\n\}"'
)
ACCURACY_STORE_RE = re.compile(
    r"Updated accuracy store for tool '(?P<tool>[^']+)' \((?P<outcome>winning|losing), curPrice=(?P<cur_price>[-\d\.]+)\)"
)

POLYMARKET_MARKETPLACE = "0x343F2B005cF6D70bA610CD9F1F1927049414B582"
OMEN_MARKETPLACE = "0x735FAAb1c4Ec41128c367AFb5c3baC73509f70bB"
DEFAULT_AUDIT_FEE = 0.01


def walk_book_local(asks: List[Dict[str, str]], spend: float) -> tuple[float, float]:
    """Local CLOB walk used by diagnostics."""
    if spend <= 0 or not asks:
        return 0.0, 0.0
    remaining = float(spend)
    cost = 0.0
    shares = 0.0
    for level in sorted(asks, key=lambda a: float(a["price"])):
        price = float(level["price"])
        size = float(level["size"])
        if price <= 0 or size <= 0:
            continue
        level_cost = price * size
        if level_cost <= remaining:
            cost += level_cost
            shares += size
            remaining -= level_cost
        else:
            fill_shares = remaining / price
            cost += remaining
            shares += fill_shares
            break
    return cost, shares


def optimize_side_local(
    p: float,
    w_bet: float,
    b_min: float,
    b_max: float,
    fee: float,
    grid_points: int,
    asks: List[Dict[str, str]],
) -> tuple[float, float, float, float]:
    """Minimal local optimizer for CLOB diagnostics."""
    g_baseline = math.log(w_bet) if w_bet > 0 else -math.inf
    if b_max <= 0 or w_bet <= 0:
        return 0.0, 0.0, g_baseline, g_baseline
    b_min = min(b_min, b_max)
    grid_points = max(grid_points, 2)
    best_spend = 0.0
    best_shares = 0.0
    best_g = g_baseline
    step = (b_max - b_min) / (grid_points - 1)
    for i in range(grid_points):
        b = b_min + i * step
        cost, shares = walk_book_local(asks, b)
        if cost <= 0 or shares <= 0:
            continue
        wealth_if_win = w_bet - cost + shares - fee
        wealth_if_lose = w_bet - cost - fee
        if wealth_if_win <= 0 or wealth_if_lose <= 0:
            continue
        g = p * math.log(wealth_if_win) + (1 - p) * math.log(wealth_if_lose)
        if g > best_g:
            best_g = g
            best_spend = cost
            best_shares = shares
    return best_spend, best_shares, best_g, g_baseline


def parse_timestamp(line: str) -> Optional[datetime]:
    """Parse a log timestamp."""
    match = TIMESTAMP_RE.match(line)
    if match is None:
        return None
    return datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def clean_allowed_tools(raw: str) -> List[str]:
    """Parse the tools list from a ChatUI log line."""
    if raw.strip() == "":
        return []
    return [part.strip().strip("'") for part in raw.split(",") if part.strip()]


@dataclass
class SessionSummary:
    """Summary of one agent session log."""

    file: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    pearl_version: Optional[str] = None
    trading_strategy: Optional[str] = None
    initial_trading_strategy: Optional[str] = None
    allowed_tools: List[str] = field(default_factory=list)
    fixed_bet_size: Optional[int] = None
    max_bet_size: Optional[int] = None
    fetched_yes_no_markets: List[Dict[str, int]] = field(default_factory=list)
    constructed_markets: List[Dict[str, int]] = field(default_factory=list)
    category_validation: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_trades: List[int] = field(default_factory=list)
    total_positions: List[int] = field(default_factory=list)
    redeemable_positions: List[int] = field(default_factory=list)
    performance_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    bet_totals: List[int] = field(default_factory=list)
    marketplace_address: Optional[str] = None
    marketplace_supports_v2: bool = False
    pol_usdc_rates: List[float] = field(default_factory=list)
    balance_snapshots: List[Dict[str, float]] = field(default_factory=list)
    prediction_history_items: List[Dict[str, Any]] = field(default_factory=list)
    position_details: List[Dict[str, Any]] = field(default_factory=list)
    runtime_bet_amounts: List[Dict[str, Any]] = field(default_factory=list)
    runtime_approved_bets: List[Dict[str, Any]] = field(default_factory=list)
    runtime_no_bet_count: int = 0
    runtime_no_bet_reasons: List[Dict[str, Any]] = field(default_factory=list)
    runtime_selected_bets: List[Dict[str, Any]] = field(default_factory=list)
    runtime_max_bet_contexts: List[Dict[str, Any]] = field(default_factory=list)
    runtime_probability_contexts: List[Dict[str, Any]] = field(default_factory=list)
    runtime_side_diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    runtime_strategy_names: List[Dict[str, Any]] = field(default_factory=list)
    prediction_accuracy_values: List[float] = field(default_factory=list)
    prepared_tools: List[Dict[str, Any]] = field(default_factory=list)
    prepared_markets: List[Dict[str, Any]] = field(default_factory=list)
    mech_response_summaries: List[Dict[str, Any]] = field(default_factory=list)
    accuracy_store_updates: List[Dict[str, Any]] = field(default_factory=list)
    bet_contexts: List[Dict[str, Any]] = field(default_factory=list)
    orderbook_snapshots: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dictionary."""
        latest_perf = (
            self.performance_snapshots[-1] if self.performance_snapshots else None
        )
        return {
            "file": self.file,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "pearl_version": self.pearl_version,
            "trading_strategy": self.trading_strategy,
            "initial_trading_strategy": self.initial_trading_strategy,
            "allowed_tools": self.allowed_tools,
            "fixed_bet_size": self.fixed_bet_size,
            "max_bet_size": self.max_bet_size,
            "latest_market_fetch": (
                self.fetched_yes_no_markets[-1] if self.fetched_yes_no_markets else None
            ),
            "latest_constructed_markets": (
                self.constructed_markets[-1] if self.constructed_markets else None
            ),
            "category_validation": self.category_validation,
            "latest_total_trades": self.total_trades[-1] if self.total_trades else None,
            "latest_total_positions": (
                self.total_positions[-1] if self.total_positions else None
            ),
            "latest_redeemable_positions": (
                self.redeemable_positions[-1] if self.redeemable_positions else None
            ),
            "latest_performance": latest_perf,
            "latest_bet_total": self.bet_totals[-1] if self.bet_totals else None,
            "marketplace_address": self.marketplace_address,
            "marketplace_supports_v2": self.marketplace_supports_v2,
            "latest_pol_usdc_rate": (
                self.pol_usdc_rates[-1] if self.pol_usdc_rates else None
            ),
            "latest_balance_snapshot": (
                self.balance_snapshots[-1] if self.balance_snapshots else None
            ),
            "prediction_history_items": self.prediction_history_items,
            "position_details": self.position_details,
            "runtime_bet_amounts": self.runtime_bet_amounts,
            "runtime_approved_bets": self.runtime_approved_bets,
            "runtime_no_bet_count": self.runtime_no_bet_count,
            "runtime_no_bet_reasons": self.runtime_no_bet_reasons,
            "runtime_selected_bets": self.runtime_selected_bets,
            "runtime_max_bet_contexts": self.runtime_max_bet_contexts,
            "runtime_probability_contexts": self.runtime_probability_contexts,
            "runtime_side_diagnostics": self.runtime_side_diagnostics,
            "runtime_strategy_names": self.runtime_strategy_names,
            "prediction_accuracy_values": self.prediction_accuracy_values,
            "prepared_tools": self.prepared_tools,
            "prepared_markets": self.prepared_markets,
            "mech_response_summaries": self.mech_response_summaries,
            "accuracy_store_updates": self.accuracy_store_updates,
            "bet_contexts": self.bet_contexts,
            "orderbook_snapshots": self.orderbook_snapshots,
        }


def iter_zip_text_files(bundle: Path) -> Iterable[tuple[str, List[str]]]:
    """Yield text files from the zip bundle."""
    with zipfile.ZipFile(bundle) as zf:
        for name in zf.namelist():
            if not name.endswith((".log", ".txt", ".json")):
                continue
            try:
                text = zf.read(name).decode("utf-8", "ignore")
            except (KeyError, NotImplementedError, RuntimeError):
                continue
            yield name, text.splitlines()


def analyze_session(name: str, lines: List[str]) -> SessionSummary:
    """Analyze a single agent log."""
    session = SessionSummary(file=name)
    pending_side_diagnostics: Dict[str, str] = {}
    pending_orderbook_token_id: Optional[str] = None

    for line in lines:
        ts = parse_timestamp(line)
        if ts is not None:
            ts_str = ts.isoformat()
            if session.start_time is None:
                session.start_time = ts_str
            session.end_time = ts_str

        version_match = PEARL_VERSION_RE.search(line)
        if version_match is not None:
            session.pearl_version = version_match.group("version")

        chatui_match = CHATUI_RE.search(line)
        if chatui_match is not None:
            session.trading_strategy = chatui_match.group("trading_strategy")
            session.initial_trading_strategy = chatui_match.group(
                "initial_trading_strategy"
            )
            session.allowed_tools = clean_allowed_tools(
                chatui_match.group("allowed_tools")
            )
            session.fixed_bet_size = int(chatui_match.group("fixed_bet_size"))
            session.max_bet_size = int(chatui_match.group("max_bet_size"))

        fetched_match = FETCHED_MARKETS_RE.search(line)
        if fetched_match is not None:
            session.fetched_yes_no_markets.append(
                {
                    "count": int(fetched_match.group("count")),
                    "categories": int(fetched_match.group("categories")),
                }
            )

        constructed_match = CONSTRUCTED_BETS_RE.search(line)
        if constructed_match is not None:
            session.constructed_markets.append(
                {
                    "constructed": int(constructed_match.group("constructed")),
                    "total": int(constructed_match.group("total")),
                    "skipped": int(constructed_match.group("skipped")),
                    "blacklisted": int(constructed_match.group("blacklisted")),
                }
            )

        category_match = CATEGORY_RE.search(line)
        if category_match is not None:
            session.category_validation[category_match.group("category")] = {
                "valid": int(category_match.group("valid")),
                "total": int(category_match.group("total")),
                "invalid": int(category_match.group("invalid")),
            }

        trades_match = TRADES_RE.search(line)
        if trades_match is not None:
            session.total_trades.append(int(trades_match.group("count")))

        positions_match = POSITIONS_RE.search(line)
        if positions_match is not None:
            session.total_positions.append(int(positions_match.group("count")))

        redeemable_match = REDEEMABLE_RE.search(line)
        if redeemable_match is not None:
            session.redeemable_positions.append(int(redeemable_match.group("count")))

        perf_match = PERF_RE.search(line)
        if perf_match is not None:
            session.performance_snapshots.append(
                {
                    "funds_used": float(perf_match.group("funds_used")),
                    "profit": float(perf_match.group("profit")),
                    "locked_funds": float(perf_match.group("locked")),
                    "available_funds": float(perf_match.group("available")),
                    "roi": float(perf_match.group("roi")),
                    "settled_mech_requests": int(perf_match.group("settled")),
                    "total_mech_requests": int(perf_match.group("total")),
                    "open_mech_requests": int(perf_match.group("open")),
                    "placed_mech_requests": int(perf_match.group("placed")),
                }
            )
        prediction_accuracy_match = PREDICTION_ACCURACY_RE.search(line)
        if prediction_accuracy_match is not None:
            session.prediction_accuracy_values.append(
                float(prediction_accuracy_match.group("prediction_accuracy"))
            )

        bet_total_match = BET_TOTAL_RE.search(line)
        if bet_total_match is not None:
            session.bet_totals.append(int(bet_total_match.group("total")))

        marketplace_match = MARKETPLACE_RE.search(line)
        if marketplace_match is not None:
            session.marketplace_address = marketplace_match.group("address")

        if MECH_V2_RE.search(line) is not None:
            session.marketplace_supports_v2 = True

        pol_rate_match = POL_RATE_RE.search(line)
        if pol_rate_match is not None:
            session.pol_usdc_rates.append(float(pol_rate_match.group("rate")))

        balance_match = BALANCE_RE.search(line)
        if balance_match is not None:
            session.balance_snapshots.append(
                {
                    "token_balance": float(balance_match.group("token")),
                    "native_balance_converted": float(balance_match.group("native")),
                    "available_funds": float(balance_match.group("available")),
                }
            )

        prediction_history_match = PREDICTION_HISTORY_ITEM_RE.search(line)
        if prediction_history_match is not None:
            session.prediction_history_items.append(
                {
                    "id": prediction_history_match.group("id"),
                    "title": prediction_history_match.group("title"),
                    "prediction_side": prediction_history_match.group(
                        "prediction_side"
                    ),
                    "bet_amount": float(prediction_history_match.group("bet_amount")),
                    "status": prediction_history_match.group("status"),
                    "net_profit": float(prediction_history_match.group("net_profit")),
                    "created_at": prediction_history_match.group("created_at"),
                }
            )

        position_details_match = POSITION_DETAILS_RE.search(line)
        if position_details_match is not None:
            session.position_details.append(
                {
                    "question": position_details_match.group("question"),
                    "total_bet": float(position_details_match.group("total_bet")),
                    "payout": float(position_details_match.group("payout")),
                    "status": position_details_match.group("status"),
                    "amount": float(position_details_match.group("amount")),
                    "side": position_details_match.group("side"),
                    "placed_at": position_details_match.group("placed_at"),
                    "prediction_tool": position_details_match.group("prediction_tool"),
                    "implied_probability": float(
                        position_details_match.group("implied_probability")
                    ),
                }
            )

        runtime_bet_amount_match = RUNTIME_BET_AMOUNT_RE.search(line)
        if runtime_bet_amount_match is not None:
            session.runtime_bet_amounts.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "bet_amount_wei": int(runtime_bet_amount_match.group("bet_amount")),
                }
            )

        runtime_approved_bet_match = RUNTIME_APPROVED_BET_RE.search(line)
        if runtime_approved_bet_match is not None:
            session.runtime_approved_bets.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "bet_amount_native": float(
                        runtime_approved_bet_match.group("bet_amount_native")
                    ),
                    "token": runtime_approved_bet_match.group("token"),
                    "side": runtime_approved_bet_match.group("side"),
                    "expected_profit_native": float(
                        runtime_approved_bet_match.group("expected_profit_native")
                    ),
                }
            )

        if RUNTIME_NO_BET_RE.search(line) is not None:
            session.runtime_no_bet_count += 1
            session.runtime_no_bet_reasons.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "reason": None,
                    "side_diagnostics": dict(pending_side_diagnostics),
                }
            )
            pending_side_diagnostics = {}

        side_diag_match = RUNTIME_SIDE_DIAGNOSTIC_RE.search(line)
        if (
            side_diag_match is not None
            and "Selected " not in line
            and "No trade:" not in line
        ):
            pending_side_diagnostics[side_diag_match.group("label")] = (
                side_diag_match.group("message")
            )
            session.runtime_side_diagnostics.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "label": side_diag_match.group("label"),
                    "message": side_diag_match.group("message"),
                }
            )

        no_trade_reason_match = RUNTIME_NO_TRADE_REASON_RE.search(line)
        if no_trade_reason_match is not None:
            if session.runtime_no_bet_reasons:
                session.runtime_no_bet_reasons[-1]["reason"] = (
                    no_trade_reason_match.group("reason")
                )
                session.runtime_no_bet_reasons[-1]["side_diagnostics"] = dict(
                    pending_side_diagnostics
                )

        prepared_metadata_match = PREPARED_METADATA_RE.search(line)
        if prepared_metadata_match is not None and "Prepared metadata" in line:
            question_match = PREPARED_METADATA_QUESTION_RE.search(line)
            session.prepared_tools.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "tool": prepared_metadata_match.group("tool"),
                }
            )
            session.prepared_markets.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "tool": prepared_metadata_match.group("tool"),
                    "question": (
                        question_match.group("question")
                        if question_match is not None
                        else None
                    ),
                }
            )

        mech_response_match = MECH_RESPONSE_RESULT_RE.search(line)
        if mech_response_match is not None:
            session.mech_response_summaries.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "p_yes": float(mech_response_match.group("p_yes")),
                    "p_no": float(mech_response_match.group("p_no")),
                    "confidence": float(mech_response_match.group("confidence")),
                    "info_utility": float(mech_response_match.group("info_utility")),
                }
            )

        accuracy_store_match = ACCURACY_STORE_RE.search(line)
        if accuracy_store_match is not None:
            session.accuracy_store_updates.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "tool": accuracy_store_match.group("tool"),
                    "outcome": accuracy_store_match.group("outcome"),
                    "cur_price": float(accuracy_store_match.group("cur_price")),
                }
            )

        bet_context_match = BET_CONTEXT_RE.search(line)
        if bet_context_match is not None:
            session.bet_contexts.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "title": bet_context_match.group("title"),
                    "price_yes": float(bet_context_match.group("price_yes")),
                    "price_no": float(bet_context_match.group("price_no")),
                    "yes_token": bet_context_match.group("yes_token"),
                    "no_token": bet_context_match.group("no_token"),
                }
            )

        orderbook_request_match = ORDERBOOK_REQUEST_RE.search(line)
        if orderbook_request_match is not None:
            pending_orderbook_token_id = orderbook_request_match.group("token_id")

        orderbook_response_match = ORDERBOOK_RESPONSE_RE.search(line)
        if (
            orderbook_response_match is not None
            and pending_orderbook_token_id is not None
        ):
            asks = [
                {"price": m.group("price"), "size": m.group("size")}
                for m in ORDERBOOK_LEVEL_RE.finditer(
                    orderbook_response_match.group("asks")
                )
            ]
            session.orderbook_snapshots.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "token_id": pending_orderbook_token_id,
                    "asks": asks,
                }
            )
            pending_orderbook_token_id = None

        runtime_max_bet_match = RUNTIME_MAX_BET_RE.search(line)
        if runtime_max_bet_match is not None:
            session.runtime_max_bet_contexts.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "max_bet": float(runtime_max_bet_match.group("max_bet")),
                    "n_bets": int(runtime_max_bet_match.group("n_bets")),
                    "min_edge": float(runtime_max_bet_match.group("min_edge")),
                }
            )

        runtime_strategy_match = USED_TRADING_STRATEGY_RE.search(line)
        if runtime_strategy_match is not None:
            session.runtime_strategy_names.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "strategy": runtime_strategy_match.group("strategy"),
                }
            )

        runtime_p_yes_match = RUNTIME_P_YES_RE.search(line)
        if runtime_p_yes_match is not None:
            session.runtime_probability_contexts.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "market_type": runtime_p_yes_match.group("market_type"),
                    "p_yes": float(runtime_p_yes_match.group("p_yes")),
                }
            )

        runtime_selected_match = RUNTIME_SELECTED_RE.search(line)
        if runtime_selected_match is not None:
            session.runtime_selected_bets.append(
                {
                    "timestamp": ts_str if ts is not None else None,
                    "label": runtime_selected_match.group("label"),
                    "bet": float(runtime_selected_match.group("bet")),
                    "token": runtime_selected_match.group("token"),
                    "shares": float(runtime_selected_match.group("shares")),
                    "expected_profit": float(
                        runtime_selected_match.group("expected_profit")
                    ),
                    "g_improvement": float(
                        runtime_selected_match.group("g_improvement")
                    ),
                }
            )

    return session


def backfill_session_from_runtime(
    session: Optional[SessionSummary],
) -> Optional[SessionSummary]:
    """Backfill missing active-session fields from runtime logs when startup config is absent."""
    if session is None:
        return None

    if session.trading_strategy is None and session.runtime_strategy_names:
        session.trading_strategy = session.runtime_strategy_names[-1]["strategy"]

    if (not session.allowed_tools) and session.prepared_tools:
        session.allowed_tools = sorted(
            {entry["tool"] for entry in session.prepared_tools}
        )

    if session.max_bet_size is None and session.runtime_max_bet_contexts:
        last_max_bet = session.runtime_max_bet_contexts[-1]["max_bet"]
        if last_max_bet is not None:
            if session.runtime_approved_bets:
                token = session.runtime_approved_bets[-1].get("token")
                if token == "xDAI":
                    session.max_bet_size = int(last_max_bet * 10**18)
                elif token == "USDC":
                    session.max_bet_size = int(last_max_bet * 10**6)
                else:
                    session.max_bet_size = last_max_bet
            else:
                session.max_bet_size = last_max_bet

    return session


def fetch_live_polymarket_book(token_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the live Polymarket book for a token."""
    url = f"https://clob.polymarket.com/book?token_id={token_id}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
        if response.status != 200:
            return None
        return json.loads(response.read().decode("utf-8"))


def detect_market_family(session: Optional[SessionSummary]) -> str:
    """Infer the market family for a session."""
    if session is None:
        return "unknown"
    if session.marketplace_address == POLYMARKET_MARKETPLACE:
        return "polymarket"
    if session.marketplace_address == OMEN_MARKETPLACE:
        return "omen"
    return "unknown"


def build_execution_audits(active: Optional[SessionSummary]) -> List[Dict[str, Any]]:
    """Build execution-side math audits for visible positions."""
    if active is None:
        return []

    audits: List[Dict[str, Any]] = []
    latest_balance = active.balance_snapshots[-1] if active.balance_snapshots else None

    for detail in active.position_details:
        audit: Dict[str, Any] = {
            "question": detail["question"],
            "placed_at": detail["placed_at"],
            "prediction_tool": detail["prediction_tool"],
            "side": detail["side"],
            "cost": detail["amount"],
            "payout": detail["payout"],
            "implied_probability": detail["implied_probability"],
            "status": "insufficient_data",
            "notes": [],
        }
        if latest_balance is None:
            audit["notes"].append("Missing balance snapshot for wealth proxy.")
            audits.append(audit)
            continue

        wealth_proxy = latest_balance["available_funds"] + detail["total_bet"]
        probability = detail["implied_probability"] / 100.0
        cost = detail["amount"]
        payout = detail["payout"]
        mech_fee = DEFAULT_AUDIT_FEE

        audit["wealth_proxy"] = wealth_proxy
        audit["wealth_proxy_basis"] = "latest_available_funds_plus_total_bet"
        expected_value = probability * payout - cost - mech_fee
        audit["expected_value"] = expected_value
        audit["expected_value_status"] = "pass" if expected_value > 0 else "fail"

        if (
            wealth_proxy <= 0
            or wealth_proxy - cost <= 0
            or wealth_proxy - cost + payout <= 0
        ):
            audit["notes"].append(
                "Non-positive wealth branch prevents log-wealth check."
            )
            audits.append(audit)
            continue

        expected_log_wealth = probability * math.log(
            wealth_proxy - cost + payout - mech_fee
        ) + (1.0 - probability) * math.log(wealth_proxy - cost - mech_fee)
        baseline_log_wealth = math.log(wealth_proxy)
        audit["expected_log_wealth"] = expected_log_wealth
        audit["baseline_log_wealth"] = baseline_log_wealth
        audit["delta_log_wealth"] = expected_log_wealth - baseline_log_wealth
        audit["status"] = (
            "pass" if expected_log_wealth >= baseline_log_wealth else "fail"
        )
        audit["notes"].append(
            f"Uses execution-time proxy wealth and assumes mech fee={DEFAULT_AUDIT_FEE:.2f} unless exposed in logs."
        )
        audits.append(audit)

    return audits


def build_runtime_log_wealth_audits(
    active: Optional[SessionSummary],
) -> List[Dict[str, Any]]:
    """Build provisional log-wealth audits from runtime Kelly logs."""
    if active is None:
        return []

    audits: List[Dict[str, Any]] = []

    for selected in active.runtime_selected_bets:
        ts = selected.get("timestamp")
        probability_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_probability_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )
        max_bet_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_max_bet_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )

        audit: Dict[str, Any] = {
            "timestamp": ts,
            "side": selected["label"],
            "token": selected["token"],
            "cost": selected["bet"],
            "shares": selected["shares"],
            "status": "insufficient_data",
            "notes": [],
        }

        if probability_ctx is None or max_bet_ctx is None:
            audit["notes"].append(
                "Missing runtime p_yes or max_bet context for selected bet."
            )
            audits.append(audit)
            continue

        p_yes = probability_ctx["p_yes"]
        probability = p_yes if selected["label"] == "yes" else 1.0 - p_yes
        wealth_proxy = max_bet_ctx["max_bet"]
        fee = DEFAULT_AUDIT_FEE

        audit["probability"] = probability
        audit["wealth_proxy"] = wealth_proxy
        audit["wealth_proxy_basis"] = "runtime_max_bet"

        expected_value = probability * selected["shares"] - selected["bet"] - fee
        audit["expected_value"] = expected_value
        audit["expected_value_status"] = "pass" if expected_value > 0 else "fail"

        if (
            wealth_proxy <= 0
            or wealth_proxy - selected["bet"] <= 0
            or wealth_proxy - selected["bet"] + selected["shares"] <= 0
        ):
            audit["notes"].append(
                "Non-positive wealth branch prevents log-wealth check."
            )
            audits.append(audit)
            continue

        expected_log_wealth = probability * math.log(
            wealth_proxy - selected["bet"] + selected["shares"] - fee
        ) + (1.0 - probability) * math.log(wealth_proxy - selected["bet"] - fee)
        baseline_log_wealth = math.log(wealth_proxy)
        audit["expected_log_wealth"] = expected_log_wealth
        audit["baseline_log_wealth"] = baseline_log_wealth
        audit["delta_log_wealth"] = expected_log_wealth - baseline_log_wealth
        audit["status"] = (
            "pass" if expected_log_wealth >= baseline_log_wealth else "fail"
        )
        audit["notes"].append(
            f"Uses runtime max_bet as wealth proxy, runtime shares as payout proxy, and fee={DEFAULT_AUDIT_FEE:.2f}."
        )
        audits.append(audit)

    return audits


def describe_execution_audit_availability(
    active: Optional[SessionSummary],
) -> Dict[str, Any]:
    """Explain whether execution math audit can run for the active session."""
    if active is None:
        return {
            "available": False,
            "reason": "No active session selected.",
        }

    market_family = detect_market_family(active)
    if active.runtime_selected_bets and active.runtime_probability_contexts:
        return {
            "available": True,
            "reason": (
                f"Runtime Kelly logs with probability and share context were parsed for {market_family}, "
                "but this remains a proxy audit because we do not have full real pre-trade state and a clean pre-vs-post trade comparison."
            ),
        }
    if active.position_details:
        return {
            "available": True,
            "reason": (
                f"Position-details payloads with probability fields were parsed for {market_family}, "
                "but this remains a proxy audit because we do not have full real pre-trade state and a clean pre-vs-post trade comparison."
            ),
        }

    if active.prediction_history_items:
        return {
            "available": False,
            "reason": (
                f"{market_family.capitalize()} session exposes prediction history, but the logged "
                "position-details payloads did not include the probability/tool fields required for "
                "execution math audit. We are also missing the real pre-trade state needed for a strict "
                "pre-vs-post trade comparison."
            ),
        }

    return {
        "available": False,
        "reason": (
            "No auditable prediction history or position-details payloads were parsed, and we are "
            "missing the real pre-trade state needed for a strict pre-vs-post trade comparison."
        ),
    }


def build_amount_field_analysis(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Explain sizing config fields versus executed amount fields visible in logs."""
    if active is None:
        return {}

    return {
        "sizing_config_fields": {
            "fixed_bet_size": active.fixed_bet_size,
            "max_bet_size": active.max_bet_size,
        },
        "field_meanings": {
            "fixed_bet_size": "Configured fixed-size override from Chat UI/runtime config.",
            "max_bet_size": "Configured sizing cap from Chat UI/runtime config.",
            "bet_amount": "Prediction-history per-bet amount exposed by the performance API.",
            "bet.amount": "Position-details per-trade amount; derived from the same bet record for the displayed trade.",
            "total_bet": "Position-level total amount allocated to that market in the position-details response.",
            "payout": "Win-state payout proxy shown in position-details.",
        },
    }


def build_runtime_strategy_activity(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Summarize runtime strategy decisions from behavioural logs."""
    if active is None:
        return {}
    return {
        "approved_bets": active.runtime_approved_bets,
        "bet_amount_events": active.runtime_bet_amounts,
        "no_bet_count": active.runtime_no_bet_count,
        "no_bet_reasons": active.runtime_no_bet_reasons,
    }


def build_live_trade_quality(active: Optional[SessionSummary]) -> List[Dict[str, Any]]:
    """Build live trade quality metrics from runtime decision logs."""
    if active is None:
        return []

    rows: List[Dict[str, Any]] = []
    for selected in active.runtime_selected_bets:
        ts = selected.get("timestamp")
        probability_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_probability_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )
        max_bet_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_max_bet_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )
        mech_ctx = next(
            (
                ctx
                for ctx in reversed(active.mech_response_summaries)
                if ctx.get("timestamp") and ts and ctx["timestamp"] <= ts
            ),
            None,
        )
        tool_ctx = next(
            (
                ctx
                for ctx in reversed(active.prepared_markets)
                if ctx.get("timestamp") and ts and ctx["timestamp"] <= ts
            ),
            None,
        )

        if probability_ctx is None or max_bet_ctx is None:
            continue

        probability = (
            probability_ctx["p_yes"]
            if selected["label"] == "yes"
            else 1.0 - probability_ctx["p_yes"]
        )
        cost = selected["bet"]
        shares = selected["shares"]
        execution_price = cost / shares if shares > 0 else None
        edge = probability - execution_price if execution_price is not None else None
        fee = DEFAULT_AUDIT_FEE
        ev = probability * shares - cost - fee
        wealth_proxy = max_bet_ctx["max_bet"]
        if (
            wealth_proxy > 0
            and wealth_proxy - cost > 0
            and wealth_proxy - cost + shares - fee > 0
        ):
            expected_log_wealth = probability * math.log(
                wealth_proxy - cost + shares - fee
            ) + (1.0 - probability) * math.log(wealth_proxy - cost - fee)
            delta_log_wealth = expected_log_wealth - math.log(wealth_proxy)
        else:
            expected_log_wealth = None
            delta_log_wealth = None

        rows.append(
            {
                "timestamp": ts,
                "tool": (
                    tool_ctx["tool"]
                    if tool_ctx is not None
                    else (active.allowed_tools[0] if active.allowed_tools else None)
                ),
                "question": tool_ctx.get("question") if tool_ctx is not None else None,
                "p": probability,
                "confidence": mech_ctx["confidence"] if mech_ctx is not None else None,
                "info_utility": (
                    mech_ctx["info_utility"] if mech_ctx is not None else None
                ),
                "shares": shares,
                "cost": cost,
                "execution_price": execution_price,
                "edge": edge,
                "ev": ev,
                "delta_log_wealth": delta_log_wealth,
            }
        )
    return rows


def build_tool_analysis(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Summarize tool usage and visible quality signals."""
    if active is None:
        return {}

    prepared_tools = [entry["tool"] for entry in active.prepared_tools]
    tool_usage: Dict[str, int] = {}
    for tool in prepared_tools:
        tool_usage[tool] = tool_usage.get(tool, 0) + 1

    avg_confidence = None
    avg_info_utility = None
    if active.mech_response_summaries:
        avg_confidence = sum(
            m["confidence"] for m in active.mech_response_summaries
        ) / len(active.mech_response_summaries)
        avg_info_utility = sum(
            m["info_utility"] for m in active.mech_response_summaries
        ) / len(active.mech_response_summaries)

    accuracy_store_summary: Dict[str, Dict[str, int]] = {}
    for update in active.accuracy_store_updates:
        tool = update["tool"]
        outcome = update["outcome"]
        bucket = accuracy_store_summary.setdefault(tool, {"winning": 0, "losing": 0})
        bucket[outcome] = bucket.get(outcome, 0) + 1

    return {
        "allowed_tools": active.allowed_tools,
        "prepared_tool_usage": tool_usage,
        "prediction_accuracy": (
            active.prediction_accuracy_values[-1]
            if active.prediction_accuracy_values
            else None
        ),
        "mech_response_count": len(active.mech_response_summaries),
        "avg_confidence": avg_confidence,
        "avg_info_utility": avg_info_utility,
        "accuracy_store_summary": accuracy_store_summary,
    }


def categorize_market_question(question: Optional[str]) -> str:
    """Infer a coarse market type from the question text."""
    if not question:
        return "unknown"

    text = question.lower()
    if any(
        token in text
        for token in (
            "company",
            "enterprise",
            "customer",
            "customers",
            "tesla",
            "monday.com",
            "agentalent.ai",
            "product",
            "production",
            "contractor",
            "contract",
        )
    ):
        return "company_product"
    if any(
        token in text
        for token in (
            "organizations",
            "industry",
            "adoption",
            "framework",
            "owner-operators",
            "freight",
            "trucking",
            "major organizations",
        )
    ):
        return "macro_industry"
    if any(
        token in text
        for token in (
            "shipping",
            "strait",
            "houthi",
            "war",
            "conflict",
            "military",
            "attack",
            "europol",
            "cross-border",
            "law enforcement",
            "fraud network",
        )
    ):
        return "geopolitics_logistics"
    if any(
        token in text
        for token in (
            "government",
            "regulation",
            "regulations",
            "policy",
            "official agency",
            "official government",
            "nasa",
            "army",
            "country",
        )
    ):
        return "government_regulation"
    if any(
        token in text
        for token in ("family", "health reasons", "retired", "john toshack")
    ):
        return "personality_entertainment"
    return "other"


def build_market_profile(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Summarize question mix and tool quality by coarse market type."""
    if active is None:
        return {}

    live_rows = build_live_trade_quality(active)
    profile: Dict[str, Dict[str, Any]] = {}
    for row in live_rows:
        market_type = categorize_market_question(row.get("question"))
        bucket = profile.setdefault(
            market_type,
            {
                "count": 0,
                "tools": {},
                "confidences": [],
                "edges": [],
                "evs": [],
                "log_deltas": [],
                "questions": [],
            },
        )
        bucket["count"] += 1
        tool = row.get("tool") or "unknown"
        bucket["tools"][tool] = bucket["tools"].get(tool, 0) + 1
        if row.get("confidence") is not None:
            bucket["confidences"].append(row["confidence"])
        if row.get("edge") is not None:
            bucket["edges"].append(row["edge"])
        if row.get("ev") is not None:
            bucket["evs"].append(row["ev"])
        if row.get("delta_log_wealth") is not None:
            bucket["log_deltas"].append(row["delta_log_wealth"])
        if row.get("question"):
            bucket["questions"].append(row["question"])

    summarized: Dict[str, Any] = {}
    for market_type, bucket in profile.items():
        summarized[market_type] = {
            "count": bucket["count"],
            "tool_usage": bucket["tools"],
            "avg_confidence": (
                sum(bucket["confidences"]) / len(bucket["confidences"])
                if bucket["confidences"]
                else None
            ),
            "avg_edge": (
                sum(bucket["edges"]) / len(bucket["edges"]) if bucket["edges"] else None
            ),
            "avg_ev": (
                sum(bucket["evs"]) / len(bucket["evs"]) if bucket["evs"] else None
            ),
            "avg_log_delta": (
                sum(bucket["log_deltas"]) / len(bucket["log_deltas"])
                if bucket["log_deltas"]
                else None
            ),
            "example_questions": bucket["questions"][:2],
        }
    return summarized


def build_tools_market_analysis(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Summarize tool behavior by market type."""
    if active is None:
        return {}

    live_rows = build_live_trade_quality(active)
    matrix: Dict[str, Dict[str, Any]] = {}
    for row in live_rows:
        tool = row.get("tool") or "unknown"
        market_type = categorize_market_question(row.get("question"))
        bucket = matrix.setdefault(tool, {}).setdefault(
            market_type,
            {
                "count": 0,
                "confidences": [],
                "edges": [],
                "evs": [],
                "log_deltas": [],
                "questions": [],
            },
        )
        bucket["count"] += 1
        if row.get("confidence") is not None:
            bucket["confidences"].append(row["confidence"])
        if row.get("edge") is not None:
            bucket["edges"].append(row["edge"])
        if row.get("ev") is not None:
            bucket["evs"].append(row["ev"])
        if row.get("delta_log_wealth") is not None:
            bucket["log_deltas"].append(row["delta_log_wealth"])
        if row.get("question"):
            bucket["questions"].append(row["question"])

    summary: Dict[str, Any] = {}
    for tool, tool_buckets in matrix.items():
        summary[tool] = {}
        for market_type, bucket in tool_buckets.items():
            summary[tool][market_type] = {
                "count": bucket["count"],
                "avg_confidence": (
                    sum(bucket["confidences"]) / len(bucket["confidences"])
                    if bucket["confidences"]
                    else None
                ),
                "avg_edge": (
                    sum(bucket["edges"]) / len(bucket["edges"])
                    if bucket["edges"]
                    else None
                ),
                "avg_ev": (
                    sum(bucket["evs"]) / len(bucket["evs"]) if bucket["evs"] else None
                ),
                "avg_log_delta": (
                    sum(bucket["log_deltas"]) / len(bucket["log_deltas"])
                    if bucket["log_deltas"]
                    else None
                ),
                "example_questions": bucket["questions"][:2],
            }
    return summary


def build_tools_market_summary(tools_market_analysis: Dict[str, Any]) -> List[str]:
    """Create a short human summary from the tools/market matrix."""
    summaries: List[str] = []
    for tool, buckets in sorted(tools_market_analysis.items()):
        if not buckets:
            continue

        parts: List[str] = []
        sorted_buckets = sorted(
            buckets.items(),
            key=lambda item: (
                item[1].get("avg_ev")
                if item[1].get("avg_ev") is not None
                else float("-inf")
            ),
            reverse=True,
        )

        if len(sorted_buckets) >= 2:
            best_type, best_bucket = sorted_buckets[0]
            worst_type, worst_bucket = sorted_buckets[-1]
            if (
                best_bucket.get("avg_ev") is not None
                and worst_bucket.get("avg_ev") is not None
                and best_type != worst_type
            ):
                parts.append(f"`{best_type}`: better edge / EV than `{worst_type}`")

        strongest_conf = max(
            (
                (market_type, bucket)
                for market_type, bucket in buckets.items()
                if bucket.get("avg_confidence") is not None
            ),
            key=lambda item: item[1]["avg_confidence"],
            default=None,
        )
        if strongest_conf is not None:
            market_type, bucket = strongest_conf
            parts.append(
                f"`{market_type}`: avg confidence `{bucket['avg_confidence']:.2f}`"
            )

        if parts:
            summaries.append(f"`{tool}`: " + "; ".join(parts))

    return summaries


def build_settlement_update_tracker(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Track whether new settled outcomes or accuracy updates are visible in logs."""
    if active is None:
        return {}

    settled_status_counts = {"won": 0, "lost": 0}
    for item in active.prediction_history_items:
        status = item.get("status")
        if status in settled_status_counts:
            settled_status_counts[status] += 1
    for item in active.position_details:
        status = item.get("status")
        if status in settled_status_counts:
            settled_status_counts[status] += 1

    accuracy_updates = len(active.accuracy_store_updates)
    has_new_settlements = (
        accuracy_updates > 0 or sum(settled_status_counts.values()) > 0
    )
    likely_accuracy_static = (
        bool(active.prediction_accuracy_values) and not has_new_settlements
    )

    return {
        "accuracy_store_updates": accuracy_updates,
        "settled_status_counts": settled_status_counts,
        "has_new_settlements": has_new_settlements,
        "likely_accuracy_static_due_to_no_settlement": likely_accuracy_static,
    }


def build_cause_hints(
    active: Optional[SessionSummary], previous: Optional[SessionSummary]
) -> List[str]:
    """Provide lightweight diagnostic hints for apparent tool changes."""
    if active is None:
        return []

    hints: List[str] = []
    active_tool_analysis = build_tool_analysis(active)
    previous_tool_analysis = (
        build_tool_analysis(previous) if previous is not None else {}
    )
    active_market_profile = build_market_profile(active)

    active_tools = set(active_tool_analysis.get("prepared_tool_usage", {}).keys())
    previous_tools = set(previous_tool_analysis.get("prepared_tool_usage", {}).keys())
    new_tools = sorted(active_tools - previous_tools)
    if new_tools and previous_tools:
        hints.append(
            f"Tool mix changed versus previous same-family session; new tool(s): {', '.join(new_tools)}."
        )

    active_conf = active_tool_analysis.get("avg_confidence")
    prev_conf = previous_tool_analysis.get("avg_confidence")
    if active_conf is not None and prev_conf is not None and active_conf < prev_conf:
        hints.append(
            f"Average mech confidence fell from {prev_conf:.2f} to {active_conf:.2f}, which may reflect a harder market batch rather than a settled-performance drop."
        )

    if active_market_profile:
        low_conf_types = [
            market_type
            for market_type, bucket in active_market_profile.items()
            if bucket.get("avg_confidence") is not None
            and bucket["avg_confidence"] < 0.7
        ]
        if low_conf_types:
            hints.append(
                "Lower-confidence live trades clustered in these market types: "
                + ", ".join(sorted(low_conf_types))
                + "."
            )

    settlement_tracker = build_settlement_update_tracker(active)
    if settlement_tracker.get("likely_accuracy_static_due_to_no_settlement"):
        hints.append(
            "Prediction accuracy likely stayed flat because no new settled outcomes or accuracy-store updates were visible in this bundle."
        )

    if not hints:
        hints.append(
            "No clear degradation signal was isolated; current evidence is more consistent with market-mix variation than with a confirmed tool regression."
        )
    return hints


def build_historical_tool_quality(
    active: Optional[SessionSummary], previous: Optional[SessionSummary]
) -> Dict[str, Any]:
    """Build historical tool-quality metrics when outcome-linked data is available."""
    if active is None:
        return {}

    settled_samples: List[Dict[str, Any]] = []
    for detail in active.position_details:
        status = detail.get("status")
        if status not in {"won", "lost"}:
            continue
        probability = detail["implied_probability"] / 100.0
        outcome = 1.0 if status == "won" else 0.0
        squared_error = (probability - outcome) ** 2
        settled_samples.append(
            {
                "tool": detail.get("prediction_tool"),
                "status": status,
                "probability": probability,
                "squared_error": squared_error,
            }
        )

    brier = None
    rmse = None
    if settled_samples:
        mean_sq = sum(sample["squared_error"] for sample in settled_samples) / len(
            settled_samples
        )
        brier = mean_sq
        rmse = math.sqrt(mean_sq)

    per_tool: Dict[str, Dict[str, Any]] = {}
    for sample in settled_samples:
        tool = sample.get("tool") or "unknown"
        bucket = per_tool.setdefault(tool, {"won": 0, "lost": 0, "squared_errors": []})
        bucket[sample["status"]] += 1
        bucket["squared_errors"].append(sample["squared_error"])

    for tool, bucket in per_tool.items():
        if bucket["squared_errors"]:
            mean_sq = sum(bucket["squared_errors"]) / len(bucket["squared_errors"])
            bucket["brier"] = mean_sq
            bucket["rmse"] = math.sqrt(mean_sq)
        del bucket["squared_errors"]

    comparison_is_comparable = (
        active is not None
        and previous is not None
        and detect_market_family(active) == detect_market_family(previous)
    )

    active_accuracy = (
        active.prediction_accuracy_values[-1]
        if active.prediction_accuracy_values
        else None
    )
    previous_accuracy = (
        previous.prediction_accuracy_values[-1]
        if comparison_is_comparable
        and previous is not None
        and previous.prediction_accuracy_values
        else None
    )
    accuracy_delta = (
        active_accuracy - previous_accuracy
        if active_accuracy is not None and previous_accuracy is not None
        else None
    )

    return {
        "prediction_accuracy": active_accuracy,
        "prediction_accuracy_previous": previous_accuracy,
        "prediction_accuracy_delta": accuracy_delta,
        "comparison_is_comparable": comparison_is_comparable,
        "brier": brier,
        "rmse": rmse,
        "settled_samples": len(settled_samples),
        "per_tool": per_tool,
        "accuracy_store_summary": build_tool_analysis(active).get(
            "accuracy_store_summary", {}
        ),
    }


def build_settled_bet_outcomes(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Summarize resolved bets using the visible post-settlement payloads."""
    if active is None:
        return {}

    position_rows = []
    for detail in active.position_details:
        status = detail.get("status")
        if status not in {"won", "lost"}:
            continue
        amount = detail.get("amount")
        payout = detail.get("payout")
        gross_multiple = (
            payout / amount if amount not in (None, 0) and payout is not None else None
        )
        net_profit = (
            payout - amount if amount is not None and payout is not None else None
        )
        position_rows.append(
            {
                "question": detail.get("question"),
                "status": status,
                "tool": detail.get("prediction_tool"),
                "amount": amount,
                "payout": payout,
                "gross_multiple": gross_multiple,
                "net_profit_proxy": net_profit,
            }
        )

    history_rows = [
        item
        for item in active.prediction_history_items
        if item.get("status") in {"won", "lost"}
    ]

    outcome_counts = {"won": 0, "lost": 0}
    for row in position_rows:
        outcome_counts[row["status"]] += 1
    if not position_rows:
        for row in history_rows:
            outcome_counts[row["status"]] += 1

    avg_gross_multiple = None
    avg_net_profit = None
    if position_rows:
        multiples = [
            row["gross_multiple"]
            for row in position_rows
            if row.get("gross_multiple") is not None
        ]
        profits = [
            row["net_profit_proxy"]
            for row in position_rows
            if row.get("net_profit_proxy") is not None
        ]
        avg_gross_multiple = sum(multiples) / len(multiples) if multiples else None
        avg_net_profit = sum(profits) / len(profits) if profits else None
    elif history_rows:
        profits = [row["net_profit"] for row in history_rows]
        avg_net_profit = sum(profits) / len(profits) if profits else None

    per_tool: Dict[str, Dict[str, Any]] = {}
    for row in position_rows:
        tool = row.get("tool") or "unknown"
        bucket = per_tool.setdefault(
            tool, {"won": 0, "lost": 0, "gross_multiples": [], "net_profits": []}
        )
        bucket[row["status"]] += 1
        if row.get("gross_multiple") is not None:
            bucket["gross_multiples"].append(row["gross_multiple"])
        if row.get("net_profit_proxy") is not None:
            bucket["net_profits"].append(row["net_profit_proxy"])

    for tool, bucket in per_tool.items():
        bucket["avg_gross_multiple"] = (
            sum(bucket["gross_multiples"]) / len(bucket["gross_multiples"])
            if bucket["gross_multiples"]
            else None
        )
        bucket["avg_net_profit"] = (
            sum(bucket["net_profits"]) / len(bucket["net_profits"])
            if bucket["net_profits"]
            else None
        )
        del bucket["gross_multiples"]
        del bucket["net_profits"]

    return {
        "resolved_count": len(position_rows) if position_rows else len(history_rows),
        "outcome_counts": outcome_counts,
        "avg_gross_multiple": avg_gross_multiple,
        "avg_net_profit": avg_net_profit,
        "per_tool": per_tool,
        "examples": position_rows[:3] if position_rows else history_rows[:3],
    }


def build_polymarket_clob_no_bet_diagnostics(
    active: Optional[SessionSummary], live_check: bool = False
) -> List[Dict[str, Any]]:
    """Replay polymarket CLOB no-bets using logged books and optional live venue constraints."""
    if active is None or detect_market_family(active) != "polymarket":
        return []

    diagnostics: List[Dict[str, Any]] = []
    fee = DEFAULT_AUDIT_FEE

    for item in active.runtime_no_bet_reasons:
        ts = item.get("timestamp")
        prob_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_probability_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )
        max_ctx = next(
            (
                ctx
                for ctx in reversed(active.runtime_max_bet_contexts)
                if ctx.get("timestamp") == ts
            ),
            None,
        )
        bet_ctx = next(
            (
                ctx
                for ctx in reversed(active.bet_contexts)
                if ctx.get("timestamp") and ts and ctx["timestamp"] <= ts
            ),
            None,
        )
        if prob_ctx is None or max_ctx is None or bet_ctx is None:
            continue

        side_diags = item.get("side_diagnostics", {})
        for label, message in side_diags.items():
            metrics_match = SIDE_METRICS_RE.search(f"{label}: {message}")
            if metrics_match is None:
                continue
            spend = float(metrics_match.group("spend"))
            shares = float(metrics_match.group("shares"))
            edge = float(metrics_match.group("edge"))
            g_improvement = float(metrics_match.group("g_improvement"))
            if spend > 0 or shares > 0:
                continue
            if edge <= 0 and g_improvement <= 0:
                continue

            token_id = bet_ctx["yes_token"] if label == "yes" else bet_ctx["no_token"]
            asks_snapshot = next(
                (
                    ob["asks"]
                    for ob in reversed(active.orderbook_snapshots)
                    if ob.get("timestamp")
                    and ts
                    and ob["timestamp"] <= ts
                    and ob["token_id"] == token_id
                ),
                None,
            )
            if not asks_snapshot:
                continue

            probability = (
                prob_ctx["p_yes"] if label == "yes" else 1.0 - prob_ctx["p_yes"]
            )
            w_bet = max_ctx["max_bet"]
            unconstrained_spend, unconstrained_shares, unconstrained_g, baseline = (
                optimize_side_local(
                    p=probability,
                    w_bet=w_bet,
                    b_min=1e-6,
                    b_max=w_bet,
                    fee=fee,
                    grid_points=500,
                    asks=asks_snapshot,
                )
            )
            unconstrained_ev = (
                probability * unconstrained_shares - unconstrained_spend - fee
                if unconstrained_spend > 0
                else None
            )

            diag: Dict[str, Any] = {
                "timestamp": ts,
                "question": bet_ctx.get("title"),
                "side": label,
                "probability": probability,
                "w_bet": w_bet,
                "fallback_edge": edge,
                "logged_g_improvement": g_improvement,
                "token_id": token_id,
                "best_ask_logged": min(
                    float(level["price"]) for level in asks_snapshot
                ),
                "unconstrained_spend": unconstrained_spend,
                "unconstrained_shares": unconstrained_shares,
                "unconstrained_ev": unconstrained_ev,
                "unconstrained_log_delta": unconstrained_g - baseline,
                "feasible_b_found_without_venue_min": unconstrained_spend > 0,
            }

            if live_check:
                try:
                    live_book = fetch_live_polymarket_book(token_id)
                except Exception as exc:  # pragma: no cover - network dependent
                    diag["live_check_error"] = str(exc)
                    diagnostics.append(diag)
                    continue
                if live_book is not None:
                    min_order_size = float(live_book.get("min_order_size", 0) or 0)
                    diag["live_min_order_size"] = min_order_size
                    if min_order_size > 0:
                        remaining = min_order_size
                        venue_min_spend = 0.0
                        venue_min_shares = 0.0
                        for level in asks_snapshot:
                            lp = float(level["price"])
                            ls = float(level["size"])
                            fill = min(ls, remaining)
                            venue_min_spend += fill * lp
                            venue_min_shares += fill
                            remaining -= fill
                            if remaining <= 0:
                                break
                        diag["logged_book_min_executable_spend_for_live_min_size"] = (
                            venue_min_spend
                        )
                        diag["logged_book_min_executable_shares_for_live_min_size"] = (
                            venue_min_shares
                        )
                        diag["platform_constraint_blocks_trade"] = (
                            venue_min_spend > w_bet
                        )
                        venue_win = w_bet - venue_min_spend + venue_min_shares - fee
                        venue_lose = w_bet - venue_min_spend - fee
                        venue_valid = (
                            venue_min_shares > 0 and venue_win > 0 and venue_lose > 0
                        )
                        diag["venue_min_trade_valid"] = venue_valid
                        if venue_valid:
                            venue_ev = (
                                probability * venue_min_shares - venue_min_spend - fee
                            )
                            venue_log = (
                                probability * math.log(venue_win)
                                + (1.0 - probability) * math.log(venue_lose)
                                - baseline
                            )
                            diag["venue_min_trade_ev"] = venue_ev
                            diag["venue_min_trade_log_delta"] = venue_log
                        else:
                            diag["venue_min_trade_ev"] = None
                            diag["venue_min_trade_log_delta"] = None
            diagnostics.append(diag)

    return diagnostics


def _format_side_label(side: str) -> str:
    """Render side label consistently for markdown summaries."""
    return side.upper()


def _expected_side_behavior(
    side: str,
    message: str,
    market_family: str,
    polymarket_diag: Optional[Dict[str, Any]] = None,
) -> str:
    """Translate raw runtime side diagnostics into expected behavior."""
    side_label = _format_side_label(side)
    oracle_match = re.search(
        r"oracle prob (?P<prob>[-\d\.]+) < min_oracle_prob (?P<min_prob>[-\d\.]+)",
        message,
    )
    if oracle_match is not None:
        return (
            f"{side_label} should be rejected by the probability gate, "
            f"so no trade is expected on that side."
        )

    best_ask_match = re.search(
        r"edge vs best_ask (?P<edge>[+\-][-\d\.]+) < min_edge (?P<min_edge>[-\d\.]+)",
        message,
    )
    if best_ask_match is not None:
        return (
            f"{side_label} should be rejected on entry price grounds at the best ask, "
            f"so no trade is expected on that side."
        )

    metrics_match = SIDE_METRICS_RE.search(f"{side}: {message}")
    if metrics_match is None:
        return f"{side_label} was not expected to produce a valid trade."

    spend = float(metrics_match.group("spend"))
    shares = float(metrics_match.group("shares"))
    edge = float(metrics_match.group("edge"))
    g_improvement = float(metrics_match.group("g_improvement"))

    if spend > 0 and shares > 0 and g_improvement > 0:
        return (
            f"{side_label} did produce a positive executable sizing candidate, "
            f"so a trade would normally be expected on that side."
        )

    if polymarket_diag:
        unconstrained_b = polymarket_diag.get("unconstrained_spend")
        unconstrained_ev = polymarket_diag.get("unconstrained_ev")
        unconstrained_log_delta = polymarket_diag.get("unconstrained_log_delta")
        no_positive_unconstrained_candidate = (
            not unconstrained_b
            or unconstrained_b <= 0
            or unconstrained_ev is None
            or unconstrained_ev <= 0
            or unconstrained_log_delta is None
            or unconstrained_log_delta <= 0
        )
        if no_positive_unconstrained_candidate:
            return (
                f"{side_label} looked favorable only on the marginal/fallback price signal, "
                f"but replaying the executable book did not produce a positive EV or "
                f"log-wealth-improving trade."
            )

    if polymarket_diag and polymarket_diag.get("platform_constraint_blocks_trade"):
        min_order_size = polymarket_diag.get("live_min_order_size")
        venue_min_spend = polymarket_diag.get(
            "logged_book_min_executable_spend_for_live_min_size"
        )
        venue_min_ev = polymarket_diag.get("venue_min_trade_ev")
        venue_min_log_delta = polymarket_diag.get("venue_min_trade_log_delta")
        venue_min_valid = polymarket_diag.get("venue_min_trade_valid")
        w_bet = polymarket_diag.get("w_bet")
        detail = []
        if min_order_size:
            detail.append(f"minimum venue order `{min_order_size:g}` shares")
        if venue_min_spend is not None:
            detail.append(f"logged-book spend `{venue_min_spend:.4f}`")
        if w_bet is not None:
            detail.append(f"per-bet bankroll `{w_bet:.4f}`")
        if venue_min_valid is False:
            detail.append("minimum executable order is not wealth-valid")
        elif venue_min_ev is not None and venue_min_log_delta is not None:
            detail.append(
                f"minimum executable order would have `EV≈{venue_min_ev:.4f}` and "
                f"`log_delta≈{venue_min_log_delta:.6f}`"
            )
        joined = ", ".join(detail)
        return (
            f"{side_label} had a positive theoretical setup, but the bet was not placeable "
            f"because the platform minimum trade blocked it"
            + (f" ({joined})." if joined else ".")
        )

    if polymarket_diag and polymarket_diag.get("feasible_b_found_without_venue_min"):
        unconstrained_b = polymarket_diag.get("unconstrained_spend")
        unconstrained_ev = polymarket_diag.get("unconstrained_ev")
        unconstrained_log_delta = polymarket_diag.get("unconstrained_log_delta")
        return (
            f"{side_label} had a positive theoretical sizing candidate"
            f" (`b≈{unconstrained_b:.4f}`, `EV≈{unconstrained_ev:.4f}`, "
            f"`log_delta≈{unconstrained_log_delta:.6f}`), but no executable "
            f"trade was ultimately placed."
        )

    if edge > 0 and g_improvement <= 0:
        if market_family == "polymarket":
            return (
                f"{side_label} looked directionally favorable, but we would still expect no trade "
                f"because no executable Kelly-improving size was found."
            )
        return (
            f"{side_label} looked directionally favorable, but no Kelly-improving bet size "
            f"was found, so no trade is expected on that side."
        )

    return f"{side_label} was not expected to produce a tradable Kelly-positive sizing outcome."


def build_expected_no_bet_explanations(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build human-readable no-bet explanations from report diagnostics."""
    market_family = report.get("market_family", "unknown")
    poly_diag_index = {
        (item.get("timestamp"), item.get("side")): item
        for item in report.get("polymarket_clob_no_bet_diagnostics", [])
    }
    items = report.get("runtime_strategy_activity", {}).get("no_bet_reasons", [])
    explanations: List[Dict[str, Any]] = []

    for item in items:
        timestamp = item.get("timestamp")
        side_diags = item.get("side_diagnostics", {})
        side_expectations: Dict[str, str] = {}
        raw_yes = side_diags.get("yes", "")
        raw_no = side_diags.get("no", "")
        for side in ("yes", "no"):
            message = side_diags.get(side)
            if not message:
                continue
            diag = poly_diag_index.get((timestamp, side))
            side_expectations[side] = _expected_side_behavior(
                side, message, market_family, diag
            )

        summary = None
        for side in ("yes", "no"):
            diag = poly_diag_index.get((timestamp, side))
            if (
                diag
                and diag.get("platform_constraint_blocks_trade")
                and diag.get("unconstrained_spend")
                and (
                    diag.get("unconstrained_ev") is not None
                    and diag.get("unconstrained_ev") > 0
                )
                and (
                    diag.get("unconstrained_log_delta") is not None
                    and diag.get("unconstrained_log_delta") > 0
                )
            ):
                summary = (
                    "Bet was not placed because the platform minimum trade size "
                    "made the otherwise positive candidate non-executable."
                )
                break
        if summary is None:
            yes_prob_gate = "min_oracle_prob" in raw_yes
            no_prob_gate = "min_oracle_prob" in raw_no
            yes_best_ask_gate = "edge vs best_ask" in raw_yes
            no_best_ask_gate = "edge vs best_ask" in raw_no
            yes_metrics = SIDE_METRICS_RE.search(f"yes: {raw_yes}") if raw_yes else None
            no_metrics = SIDE_METRICS_RE.search(f"no: {raw_no}") if raw_no else None
            yes_zero_spend = bool(
                yes_metrics
                and float(yes_metrics.group("spend")) == 0
                and float(yes_metrics.group("shares")) == 0
            )
            no_zero_spend = bool(
                no_metrics
                and float(no_metrics.group("spend")) == 0
                and float(no_metrics.group("shares")) == 0
            )

            if (yes_prob_gate or yes_best_ask_gate) and no_zero_spend:
                summary = (
                    "Bet was not placed because one side failed the entry gate and "
                    "the opposite side did not produce an executable Kelly-positive size."
                )
            elif (no_prob_gate or no_best_ask_gate) and yes_zero_spend:
                summary = (
                    "Bet was not placed because one side failed the entry gate and "
                    "the opposite side did not produce an executable Kelly-positive size."
                )
            elif (yes_prob_gate or yes_best_ask_gate) and (
                no_prob_gate or no_best_ask_gate
            ):
                summary = (
                    "Bet was not placed because both sides failed the entry gates."
                )
            elif yes_zero_spend or no_zero_spend:
                summary = "Bet was not placed because no side produced an executable Kelly-positive trade."
        if summary is None and side_expectations:
            summary = "Bet was not placed because no side produced an executable Kelly-positive trade."

        explanations.append(
            {
                "timestamp": timestamp,
                "summary": summary,
                "side_expectations": side_expectations,
            }
        )

    return explanations


def build_prediction_logic_summary(
    active: Optional[SessionSummary], previous: Optional[SessionSummary]
) -> Dict[str, Any]:
    """Group prediction-side signals separately from sizing/execution."""
    tool_analysis = build_tool_analysis(active)
    historical_tool_quality = build_historical_tool_quality(active, previous)
    market_profile = build_market_profile(active)
    settlement_tracker = build_settlement_update_tracker(active)
    live_trade_quality = build_live_trade_quality(active)

    return {
        "allowed_tools": tool_analysis.get("allowed_tools", []),
        "prepared_tool_usage": tool_analysis.get("prepared_tool_usage", {}),
        "mech_response_count": tool_analysis.get("mech_response_count", 0),
        "avg_confidence": tool_analysis.get("avg_confidence"),
        "avg_info_utility": tool_analysis.get("avg_info_utility"),
        "prediction_accuracy": historical_tool_quality.get("prediction_accuracy"),
        "prediction_accuracy_delta": historical_tool_quality.get(
            "prediction_accuracy_delta"
        ),
        "brier": historical_tool_quality.get("brier"),
        "rmse": historical_tool_quality.get("rmse"),
        "settled_samples": historical_tool_quality.get("settled_samples", 0),
        "accuracy_store_summary": historical_tool_quality.get(
            "accuracy_store_summary", {}
        ),
        "settlement_update_tracker": settlement_tracker,
        "market_profile": market_profile,
        "live_prediction_rows": [
            {
                "timestamp": row.get("timestamp"),
                "tool": row.get("tool"),
                "question": row.get("question"),
                "p": row.get("p"),
                "confidence": row.get("confidence"),
                "info_utility": row.get("info_utility"),
                "market_type": categorize_market_question(row.get("question")),
            }
            for row in live_trade_quality
        ],
    }


def build_sizing_logic_summary(active: Optional[SessionSummary]) -> Dict[str, Any]:
    """Group sizing/execution-side signals separately from prediction quality."""
    amount_fields = build_amount_field_analysis(active)
    runtime_activity = build_runtime_strategy_activity(active)
    runtime_audits = build_runtime_log_wealth_audits(active)
    live_trade_quality = build_live_trade_quality(active)

    ev_values = [row["ev"] for row in live_trade_quality if row.get("ev") is not None]
    edge_values = [
        row["edge"] for row in live_trade_quality if row.get("edge") is not None
    ]
    log_values = [
        row["delta_log_wealth"]
        for row in live_trade_quality
        if row.get("delta_log_wealth") is not None
    ]

    return {
        "config": amount_fields.get("sizing_config_fields", {}),
        "runtime_strategy_activity": runtime_activity,
        "runtime_log_wealth_audits": runtime_audits,
        "no_bet_reasons": runtime_activity.get("no_bet_reasons", []),
        "live_sizing_rows": [
            {
                "timestamp": row.get("timestamp"),
                "tool": row.get("tool"),
                "question": row.get("question"),
                "cost": row.get("cost"),
                "shares": row.get("shares"),
                "execution_price": row.get("execution_price"),
                "edge": row.get("edge"),
                "ev": row.get("ev"),
                "delta_log_wealth": row.get("delta_log_wealth"),
            }
            for row in live_trade_quality
        ],
        "avg_edge": sum(edge_values) / len(edge_values) if edge_values else None,
        "avg_ev": sum(ev_values) / len(ev_values) if ev_values else None,
        "avg_log_delta": sum(log_values) / len(log_values) if log_values else None,
    }


def choose_relevant_sessions(
    sessions: List[SessionSummary],
) -> Dict[str, Optional[SessionSummary]]:
    """Pick the active session and previous same-family session when possible."""
    market_sessions = [
        session
        for session in sessions
        if session.marketplace_address in {POLYMARKET_MARKETPLACE, OMEN_MARKETPLACE}
        or session.trading_strategy is not None
    ]
    market_sessions_sorted = sorted(
        market_sessions,
        key=lambda session: session.start_time or "",
    )
    active = market_sessions_sorted[-1] if market_sessions_sorted else None
    if active is None:
        return {"active": None, "previous": None}
    active_family = detect_market_family(active)
    same_family_sessions = [
        session
        for session in market_sessions_sorted
        if detect_market_family(session) == active_family
    ]
    previous = same_family_sessions[-2] if len(same_family_sessions) > 1 else None
    return {"active": active, "previous": previous}


def build_overview(
    bundle: Path, sessions: List[SessionSummary], polymarket_live_check: bool = False
) -> Dict[str, Any]:
    """Build the top-level report."""
    relevant = choose_relevant_sessions(sessions)
    active = backfill_session_from_runtime(relevant["active"])
    previous = relevant["previous"]

    overview: Dict[str, Any] = {
        "bundle": str(bundle),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions": [session.to_dict() for session in sessions],
        "active_session": active.to_dict() if active is not None else None,
        "previous_session": previous.to_dict() if previous is not None else None,
        "market_family": detect_market_family(active),
        "execution_audits": build_execution_audits(active),
        "runtime_log_wealth_audits": build_runtime_log_wealth_audits(active),
        "execution_audit_availability": describe_execution_audit_availability(active),
        "amount_field_analysis": build_amount_field_analysis(active),
        "runtime_strategy_activity": build_runtime_strategy_activity(active),
        "live_trade_quality": build_live_trade_quality(active),
        "tool_analysis": build_tool_analysis(active),
        "historical_tool_quality": build_historical_tool_quality(active, previous),
        "settled_bet_outcomes": build_settled_bet_outcomes(active),
        "prediction_logic": build_prediction_logic_summary(active, previous),
        "sizing_logic": build_sizing_logic_summary(active),
        "polymarket_clob_no_bet_diagnostics": build_polymarket_clob_no_bet_diagnostics(
            active, live_check=polymarket_live_check
        ),
        "market_profile": build_market_profile(active),
        "tools_market_analysis": build_tools_market_analysis(active),
        "tools_market_summary": build_tools_market_summary(
            build_tools_market_analysis(active)
        ),
        "settlement_update_tracker": build_settlement_update_tracker(active),
        "cause_hints": build_cause_hints(active, previous),
        "observations": [],
    }

    observations: List[str] = []

    if active is not None:
        observations.append(
            f"Active {overview['market_family']} session ran Pearl/{active.pearl_version or 'unknown'} "
            f"with strategy `{active.trading_strategy or 'unknown'}` and "
            f"max bet size `{active.max_bet_size}`."
        )
        if active.performance_snapshots:
            latest_perf = active.performance_snapshots[-1]
            observations.append(
                "Latest performance snapshot shows "
                f"ROI {latest_perf['roi']:.4f}, "
                f"profit {latest_perf['profit']:.2f}, "
                f"funds used {latest_perf['funds_used']:.2f}, "
                f"locked funds {latest_perf['locked_funds']:.2f}."
            )
        if active.constructed_markets:
            latest = active.constructed_markets[-1]
            observations.append(
                "Latest market refresh constructed "
                f"{latest['constructed']} markets with "
                f"{latest['blacklisted']} blacklisted."
            )
        execution_audits = overview["execution_audits"]
        if execution_audits:
            passed = sum(audit["status"] == "pass" for audit in execution_audits)
            failed = sum(audit["status"] == "fail" for audit in execution_audits)
            insufficient = sum(
                audit["status"] == "insufficient_data" for audit in execution_audits
            )
            ev_passed = sum(
                audit.get("expected_value_status") == "pass"
                for audit in execution_audits
            )
            ev_failed = sum(
                audit.get("expected_value_status") == "fail"
                for audit in execution_audits
            )
            observations.append(
                "Execution math audit summary: "
                f"{passed} pass, {failed} fail, {insufficient} insufficient data."
            )
            observations.append(
                f"Execution EV check summary: {ev_passed} pass, {ev_failed} fail."
            )
        else:
            observations.append(
                "Execution math audit unavailable: "
                f"{overview['execution_audit_availability']['reason']}"
            )
        runtime_log_wealth_audits = overview["runtime_log_wealth_audits"]
        if runtime_log_wealth_audits:
            runtime_passed = sum(
                audit["status"] == "pass" for audit in runtime_log_wealth_audits
            )
            runtime_failed = sum(
                audit["status"] == "fail" for audit in runtime_log_wealth_audits
            )
            runtime_ev_passed = sum(
                audit.get("expected_value_status") == "pass"
                for audit in runtime_log_wealth_audits
            )
            runtime_ev_failed = sum(
                audit.get("expected_value_status") == "fail"
                for audit in runtime_log_wealth_audits
            )
            observations.append(
                "Sizing Logic info: EV and log-wealth as expected, including placed and skipped bets."
            )
            observations.append(
                "Runtime log-wealth audit summary: "
                f"{runtime_passed} pass, {runtime_failed} fail."
            )
            observations.append(
                "Runtime EV audit summary: "
                f"{runtime_ev_passed} pass, {runtime_ev_failed} fail."
            )
        runtime_activity = overview["runtime_strategy_activity"]
        approved_bets = runtime_activity.get("approved_bets", [])
        no_bet_count = runtime_activity.get("no_bet_count", 0)
        if approved_bets:
            observations.append(
                f"Runtime strategy activity shows {len(approved_bets)} approved bet(s) "
                f"and {no_bet_count} no-bet cycle(s)."
            )
        tools_market_summary = overview.get("tools_market_summary", [])
        if tools_market_summary:
            observations.append("Tools / Market info:")
            observations.extend(tools_market_summary)
        tool_analysis = overview["tool_analysis"]
        if tool_analysis.get("prediction_accuracy") is not None:
            observations.append(
                f"Visible prediction accuracy is {tool_analysis['prediction_accuracy']:.2f}."
            )
        historical_tool_quality = overview["historical_tool_quality"]
        if historical_tool_quality.get("brier") is not None:
            observations.append(
                f"Historical Brier score from settled samples is {historical_tool_quality['brier']:.4f}."
            )
        settled_outcomes = overview["settled_bet_outcomes"]
        if settled_outcomes.get("resolved_count", 0):
            counts = settled_outcomes.get("outcome_counts", {})
            msg = (
                "Resolved bet outcomes visible: "
                f"won={counts.get('won', 0)}, lost={counts.get('lost', 0)}"
            )
            if settled_outcomes.get("avg_gross_multiple") is not None:
                msg += f", avg payout/bet={settled_outcomes['avg_gross_multiple']:.2f}x"
            if settled_outcomes.get("avg_net_profit") is not None:
                msg += f", avg net result={settled_outcomes['avg_net_profit']:.2f}"
            msg += "."
            observations.append(msg)
        settlement_tracker = overview["settlement_update_tracker"]
        if settlement_tracker.get("likely_accuracy_static_due_to_no_settlement"):
            observations.append(
                "Prediction accuracy likely stayed flat because no new settled outcomes or accuracy-store updates were visible."
            )
    if previous is not None and active is not None:
        if previous.pearl_version != active.pearl_version:
            observations.append(
                f"Version changed from Pearl/{previous.pearl_version or 'unknown'} "
                f"to Pearl/{active.pearl_version or 'unknown'}."
            )
        if previous.trading_strategy != active.trading_strategy:
            observations.append(
                f"Trading strategy changed from `{previous.trading_strategy}` "
                f"to `{active.trading_strategy}`."
            )
        if previous.bet_totals and active.bet_totals:
            delta = active.bet_totals[-1] - previous.bet_totals[-1]
            observations.append(
                f"Visible prediction-history total changed by {delta} "
                f"({previous.bet_totals[-1]} -> {active.bet_totals[-1]})."
            )
    elif active is not None:
        observations.append(
            f"No previous {overview['market_family']} session was available for same-family comparison."
        )

    overview["observations"] = observations
    return overview


def render_markdown(report: Dict[str, Any]) -> str:
    """Render a compact Markdown summary."""

    def fmt_visible(value: Any, *, omen_not_exposed: bool = False) -> str:
        if value is None and omen_not_exposed and report.get("market_family") == "omen":
            return "not exposed in Omen logs"
        return str(value)

    expected_no_bet_explanations = build_expected_no_bet_explanations(report)
    expected_no_bet_by_timestamp = {
        item.get("timestamp"): item for item in expected_no_bet_explanations
    }

    lines = [
        "# Pearl Log Analysis",
        "",
        f"- Bundle: `{report['bundle']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Market family: `{report.get('market_family', 'unknown')}`",
        "",
    ]

    active = report.get("active_session")
    previous = report.get("previous_session")

    if active is not None:
        lines.extend(
            [
                "## Active Session",
                "",
                f"- File: `{active['file']}`",
                f"- Version: `{active['pearl_version']}`",
                f"- Strategy: `{active['trading_strategy']}`",
                f"- Allowed tools: `{', '.join(active['allowed_tools']) or 'n/a'}`",
                f"- Fixed bet size: `{active['fixed_bet_size']}`",
                f"- Max bet size: `{active['max_bet_size']}`",
                f"- Latest total bets visible: `{active['latest_bet_total']}`",
                f"- Latest total trades visible: `{fmt_visible(active['latest_total_trades'], omen_not_exposed=True)}`",
                f"- Latest total positions visible: `{fmt_visible(active['latest_total_positions'], omen_not_exposed=True)}`",
                f"- Latest redeemable positions: `{fmt_visible(active['latest_redeemable_positions'], omen_not_exposed=True)}`",
                f"- Marketplace supports v2: `{active['marketplace_supports_v2']}`",
                "",
            ]
        )
        latest_perf = active.get("latest_performance")
        if latest_perf is not None:
            lines.extend(
                [
                    "## Performance Snapshot",
                    "",
                    f"- ROI: `{latest_perf['roi']}`",
                    f"- Profit: `{latest_perf['profit']}`",
                    f"- Funds used: `{latest_perf['funds_used']}`",
                    f"- Locked funds: `{latest_perf['locked_funds']}`",
                    f"- Available funds: `{latest_perf['available_funds']}`",
                    f"- Settled mech requests: `{latest_perf['settled_mech_requests']}`",
                    f"- Total mech requests: `{latest_perf['total_mech_requests']}`",
                    f"- Open mech requests: `{latest_perf['open_mech_requests']}`",
                    f"- Placed mech requests: `{latest_perf['placed_mech_requests']}`",
                    "",
                ]
            )

    if previous is not None:
        lines.extend(
            [
                "## Previous Session",
                "",
                f"- File: `{previous['file']}`",
                f"- Version: `{previous['pearl_version']}`",
                f"- Strategy: `{previous['trading_strategy']}`",
                f"- Latest total bets visible: `{previous['latest_bet_total']}`",
                "",
            ]
        )

    execution_audits = report.get("execution_audits", [])
    if execution_audits:
        lines.extend(["## Execution Math Audit", ""])
        for audit in execution_audits[:5]:
            lines.append(
                f"- `{audit['status']}` `{audit['question']}` via `{audit['prediction_tool']}` "
                f"(p={audit['implied_probability']:.2f}%, cost={audit['cost']}, payout={audit['payout']})"
            )
            if "expected_value" in audit:
                lines.append(
                    f"  expected_value=`{audit['expected_value']:.6f}` "
                    f"ev_check=`{audit['expected_value_status']}`"
                )
            if "delta_log_wealth" in audit:
                lines.append(
                    f"  delta_log_wealth=`{audit['delta_log_wealth']:.6f}` "
                    f"using wealth proxy `{audit['wealth_proxy_basis']}`=`{audit['wealth_proxy']}`"
                )
            elif audit.get("notes"):
                lines.append(f"  note=`{audit['notes'][0]}`")
        lines.append("")
    else:
        audit_availability = report.get("execution_audit_availability", {})
        if report.get("runtime_log_wealth_audits"):
            message = (
                "Position-details audit unavailable; runtime Kelly audit available. "
                f"Reason: {audit_availability.get('reason', 'unknown reason')}"
            )
        else:
            message = audit_availability.get("reason", "unknown reason")
        lines.extend(
            [
                "## Execution Math Audit",
                "",
                f"- Unavailable: `{message}`",
                "",
            ]
        )

    amount_field_analysis = report.get("amount_field_analysis", {})
    if amount_field_analysis:
        lines.extend(["## Amount Fields", ""])
        sizing_fields = amount_field_analysis.get("sizing_config_fields", {})
        lines.append(
            f"- Config sizing fields: fixed_bet_size=`{sizing_fields.get('fixed_bet_size')}`, "
            f"max_bet_size=`{sizing_fields.get('max_bet_size')}`"
        )
        for key, meaning in amount_field_analysis.get("field_meanings", {}).items():
            lines.append(f"- `{key}`: {meaning}")
        lines.append("")

    runtime_activity = report.get("runtime_strategy_activity", {})
    approved_bets = runtime_activity.get("approved_bets", [])
    if approved_bets or runtime_activity.get("no_bet_count", 0):
        lines.extend(["## Runtime Strategy Activity", ""])
        for bet in approved_bets[:5]:
            lines.append(
                f"- Approved bet at `{bet['timestamp']}`: "
                f"`{bet['bet_amount_native']}` `{bet['token']}` on `{bet['side']}`, "
                f"expected_profit=`{bet['expected_profit_native']}` `{bet['token']}`"
            )
        if runtime_activity.get("no_bet_count", 0):
            lines.append(
                f"- No-bet cycles observed: `{runtime_activity['no_bet_count']}`"
            )
        no_bet_reasons = runtime_activity.get("no_bet_reasons", [])
        for item in no_bet_reasons:
            explanation = expected_no_bet_by_timestamp.get(item.get("timestamp"))
            if explanation and explanation.get("summary"):
                lines.append(
                    f"- No-bet interpretation at `{item.get('timestamp')}`: `{explanation['summary']}`"
                )
            elif item.get("reason"):
                lines.append(
                    f"- No-bet interpretation at `{item.get('timestamp')}`: `Bet was not placed because no executable Kelly-positive trade was available.`"
                )
        lines.append("")

    runtime_log_wealth_audits = report.get("runtime_log_wealth_audits", [])
    if runtime_log_wealth_audits:
        lines.extend(["## Runtime Log-Wealth Audit", ""])
        for audit in runtime_log_wealth_audits[:5]:
            lines.append(
                f"- `{audit['status']}` at `{audit['timestamp']}` side=`{audit['side']}` "
                f"p=`{audit['probability']:.4f}` cost=`{audit['cost']}` shares=`{audit['shares']}`"
            )
            lines.append(
                f"  expected_value=`{audit['expected_value']:.6f}` "
                f"delta_log_wealth=`{audit['delta_log_wealth']:.6f}` "
                f"wealth_proxy=`{audit['wealth_proxy']}`"
            )
        lines.append("")

    live_trade_quality = report.get("live_trade_quality", [])
    if live_trade_quality:
        lines.extend(["## Live Trade Quality", ""])
        for row in live_trade_quality[:5]:
            lines.append(
                f"- `{row['timestamp']}` tool=`{row.get('tool')}` p=`{row['p']:.4f}` "
                f"confidence=`{row.get('confidence') if row.get('confidence') is not None else 'n/a'}` "
                f"shares=`{row['shares']}` cost=`{row['cost']}`"
            )
            lines.append(
                f"  execution_price=`{row['execution_price']:.6f}` "
                f"edge=`{row['edge']:.6f}` "
                f"EV=`{row['ev']:.6f}` "
                f"log_delta=`{row['delta_log_wealth']:.6f}`"
            )
        lines.append("")

    prediction_logic = report.get("prediction_logic", {})
    if prediction_logic:
        lines.extend(["## Prediction Logic", ""])
        lines.append(
            f"- Allowed tools: `{', '.join(prediction_logic.get('allowed_tools', [])) or 'n/a'}`"
        )
        prepared_usage = prediction_logic.get("prepared_tool_usage", {})
        if prepared_usage:
            usage = ", ".join(
                f"{tool}={count}" for tool, count in sorted(prepared_usage.items())
            )
            lines.append(f"- Tool selection counts: `{usage}`")
        lines.append(
            f"- Mech responses parsed: `{prediction_logic.get('mech_response_count', 0)}`"
        )
        if prediction_logic.get("avg_confidence") is not None:
            lines.append(
                f"- Average confidence: `{prediction_logic['avg_confidence']:.2f}`"
            )
        if prediction_logic.get("avg_info_utility") is not None:
            lines.append(
                f"- Average reported info utility: `{prediction_logic['avg_info_utility']:.2f}`"
            )
        if prediction_logic.get("prediction_accuracy") is not None:
            lines.append(
                f"- Prediction accuracy: `{prediction_logic['prediction_accuracy']:.2%}`"
            )
        if prediction_logic.get("prediction_accuracy_delta") is not None:
            lines.append(
                f"- Accuracy delta vs previous same-family session: `{prediction_logic['prediction_accuracy_delta']:+.2%}`"
            )
        if prediction_logic.get("brier") is not None:
            lines.append(f"- Brier score: `{prediction_logic['brier']:.6f}`")
        else:
            lines.append("- Brier score: `unavailable`")
        if prediction_logic.get("rmse") is not None:
            lines.append(f"- RMSE: `{prediction_logic['rmse']:.6f}`")
        else:
            lines.append("- RMSE: `unavailable`")
        settlement_tracker = prediction_logic.get("settlement_update_tracker", {})
        if settlement_tracker.get("likely_accuracy_static_due_to_no_settlement"):
            lines.append(
                "- Accuracy likely unchanged because no new settled wins/losses were visible."
            )
        lines.append("")

    sizing_logic = report.get("sizing_logic", {})
    if sizing_logic:
        lines.extend(["## Sizing Logic", ""])
        config = sizing_logic.get("config", {})
        lines.append(
            f"- Config: fixed_bet_size=`{config.get('fixed_bet_size')}`, max_bet_size=`{config.get('max_bet_size')}`"
        )
        runtime_activity = sizing_logic.get("runtime_strategy_activity", {})
        lines.append(
            f"- Runtime approved bets: `{len(runtime_activity.get('approved_bets', []))}`"
        )
        lines.append(
            f"- Runtime no-bet cycles: `{runtime_activity.get('no_bet_count', 0)}`"
        )
        audits = sizing_logic.get("runtime_log_wealth_audits", [])
        if audits:
            passed = sum(a["status"] == "pass" for a in audits)
            failed = sum(a["status"] == "fail" for a in audits)
            lines.append(f"- Runtime Kelly audit: pass=`{passed}`, fail=`{failed}`")
        if sizing_logic.get("avg_edge") is not None:
            lines.append(f"- Average edge: `{sizing_logic['avg_edge']:.6f}`")
        if sizing_logic.get("avg_ev") is not None:
            lines.append(f"- Average EV: `{sizing_logic['avg_ev']:.6f}`")
        if sizing_logic.get("avg_log_delta") is not None:
            lines.append(
                f"- Average log-wealth delta: `{sizing_logic['avg_log_delta']:.6f}`"
            )
        no_bet_reasons = sizing_logic.get("no_bet_reasons", [])
        for item in no_bet_reasons:
            explanation = expected_no_bet_by_timestamp.get(item.get("timestamp"), {})
            summary = explanation.get("summary")
            if summary:
                lines.append(f"- No-bet expectation: `{summary}`")
            side_expectations = explanation.get("side_expectations", {})
            yes_expectation = side_expectations.get("yes")
            no_expectation = side_expectations.get("no")
            if yes_expectation:
                lines.append(f"  expected_yes_behavior=`{yes_expectation}`")
            if no_expectation:
                lines.append(f"  expected_no_behavior=`{no_expectation}`")
        lines.append("")

    tool_analysis = report.get("tool_analysis", {})
    if tool_analysis:
        lines.extend(["## Tool Analysis", ""])
        lines.append(
            f"- Allowed tools: `{', '.join(tool_analysis.get('allowed_tools', [])) or 'n/a'}`"
        )
        if tool_analysis.get("prepared_tool_usage"):
            usage = ", ".join(
                f"{tool}={count}"
                for tool, count in sorted(tool_analysis["prepared_tool_usage"].items())
            )
            lines.append(f"- Prepared tool usage: `{usage}`")
        if tool_analysis.get("prediction_accuracy") is not None:
            lines.append(
                f"- Prediction accuracy: `{tool_analysis['prediction_accuracy']:.2%}`"
            )
        lines.append(
            f"- Mech responses parsed: `{tool_analysis.get('mech_response_count', 0)}`"
        )
        if tool_analysis.get("avg_confidence") is not None:
            lines.append(
                f"- Average mech confidence: `{tool_analysis['avg_confidence']:.2f}`"
            )
        if tool_analysis.get("avg_info_utility") is not None:
            lines.append(
                f"- Average mech info utility: `{tool_analysis['avg_info_utility']:.2f}`"
            )
        if tool_analysis.get("accuracy_store_summary"):
            for tool, summary in sorted(
                tool_analysis["accuracy_store_summary"].items()
            ):
                lines.append(
                    f"- Accuracy store updates for `{tool}`: "
                    f"winning=`{summary.get('winning', 0)}`, losing=`{summary.get('losing', 0)}`"
                )
        lines.append("")

    historical_tool_quality = report.get("historical_tool_quality", {})
    if historical_tool_quality:
        lines.extend(["## Historical Tool Quality", ""])
        if historical_tool_quality.get("prediction_accuracy") is not None:
            lines.append(
                f"- Prediction accuracy: `{historical_tool_quality['prediction_accuracy']:.2%}`"
            )
        if historical_tool_quality.get("prediction_accuracy_delta") is not None:
            lines.append(
                f"- Prediction accuracy delta vs previous session: `{historical_tool_quality['prediction_accuracy_delta']:+.2%}`"
            )
        elif not historical_tool_quality.get("comparison_is_comparable", True):
            lines.append(
                "- Prediction accuracy delta vs previous session: `not comparable across market families`"
            )
        lines.append(
            f"- Settled samples with probability+outcome available: `{historical_tool_quality.get('settled_samples', 0)}`"
        )
        if historical_tool_quality.get("brier") is not None:
            lines.append(f"- Brier score: `{historical_tool_quality['brier']:.6f}`")
        else:
            lines.append("- Brier score: `unavailable`")
        if historical_tool_quality.get("rmse") is not None:
            lines.append(
                f"- Root mean square error: `{historical_tool_quality['rmse']:.6f}`"
            )
        else:
            lines.append("- Root mean square error: `unavailable`")
        if historical_tool_quality.get("per_tool"):
            for tool, bucket in sorted(historical_tool_quality["per_tool"].items()):
                line = f"- `{tool}`: won=`{bucket.get('won', 0)}`, lost=`{bucket.get('lost', 0)}`"
                if bucket.get("brier") is not None:
                    line += (
                        f", brier=`{bucket['brier']:.6f}`, rmse=`{bucket['rmse']:.6f}`"
                    )
                lines.append(line)
        elif historical_tool_quality.get("accuracy_store_summary"):
            for tool, bucket in sorted(
                historical_tool_quality["accuracy_store_summary"].items()
            ):
                lines.append(
                    f"- `{tool}` settled updates: winning=`{bucket.get('winning', 0)}`, losing=`{bucket.get('losing', 0)}`"
                )
        lines.append("")

    settled_bet_outcomes = report.get("settled_bet_outcomes", {})
    if settled_bet_outcomes:
        lines.extend(["## Settled Bet Outcomes", ""])
        lines.append(
            f"- Resolved bets visible: `{settled_bet_outcomes.get('resolved_count', 0)}`"
        )
        counts = settled_bet_outcomes.get("outcome_counts", {})
        lines.append(
            f"- Outcomes: won=`{counts.get('won', 0)}`, lost=`{counts.get('lost', 0)}`"
        )
        if settled_bet_outcomes.get("avg_gross_multiple") is not None:
            lines.append(
                f"- Average payout / bet: `{settled_bet_outcomes['avg_gross_multiple']:.2f}x`"
            )
        if settled_bet_outcomes.get("avg_net_profit") is not None:
            lines.append(
                f"- Average net result: `{settled_bet_outcomes['avg_net_profit']:.2f}`"
            )
        for tool, bucket in sorted(settled_bet_outcomes.get("per_tool", {}).items()):
            line = f"- `{tool}`: won=`{bucket.get('won', 0)}`, lost=`{bucket.get('lost', 0)}`"
            if bucket.get("avg_gross_multiple") is not None:
                line += f", avg payout/bet=`{bucket['avg_gross_multiple']:.2f}x`"
            if bucket.get("avg_net_profit") is not None:
                line += f", avg net=`{bucket['avg_net_profit']:.2f}`"
            lines.append(line)
        lines.append("")

    clob_no_bet_diagnostics = report.get("polymarket_clob_no_bet_diagnostics", [])
    if clob_no_bet_diagnostics:
        lines.extend(["## Polymarket CLOB No-Bet Diagnostics", ""])
        for row in clob_no_bet_diagnostics[:5]:
            lines.append(
                f"- `{row.get('timestamp')}` side=`{row.get('side')}` "
                f"fallback_edge=`{row.get('fallback_edge'):+.4f}` "
                f"logged_g=`{row.get('logged_g_improvement'):.6f}` "
                f"best_ask_logged=`{row.get('best_ask_logged')}`"
            )
            lines.append(
                f"  unconstrained_b=`{row.get('unconstrained_spend'):.4f}` "
                f"unconstrained_ev=`{row.get('unconstrained_ev') if row.get('unconstrained_ev') is not None else 'n/a'}` "
                f"unconstrained_log_delta=`{row.get('unconstrained_log_delta'):.6f}`"
            )
            if row.get("live_min_order_size") is not None:
                lines.append(
                    f"  live_min_order_size_from_venue=`{row.get('live_min_order_size')}` "
                    f"logged_book_min_spend_for_live_min=`{row.get('logged_book_min_executable_spend_for_live_min_size')}` "
                    f"platform_constraint_blocks_trade=`{row.get('platform_constraint_blocks_trade')}`"
                )
                if row.get("venue_min_trade_valid") is False:
                    lines.append(
                        "  minimum_executable_order_result=`not wealth-valid at minimum executable size`"
                    )
                elif row.get("venue_min_trade_ev") is not None:
                    lines.append(
                        f"  minimum_executable_order_ev=`{row.get('venue_min_trade_ev'):.6f}` "
                        f"minimum_executable_order_log_delta=`{row.get('venue_min_trade_log_delta'):.6f}`"
                    )
            elif row.get("live_check_error"):
                lines.append(f"  live_check_error=`{row.get('live_check_error')}`")
            if row.get("question"):
                lines.append(f"  question=`{row.get('question')}`")
        lines.append("")

    market_profile = report.get("market_profile", {})
    if market_profile:
        lines.extend(["## Market Profile", ""])
        for market_type, bucket in sorted(market_profile.items()):
            lines.append(f"- `{market_type}`: count=`{bucket.get('count', 0)}`")
            tool_usage = bucket.get("tool_usage", {})
            if tool_usage:
                usage = ", ".join(
                    f"{tool}={count}" for tool, count in sorted(tool_usage.items())
                )
                lines.append(f"  tools=`{usage}`")
            if bucket.get("avg_confidence") is not None:
                lines.append(
                    f"  avg_confidence=`{bucket['avg_confidence']:.2f}` "
                    f"avg_edge=`{bucket['avg_edge']:.6f}` "
                    f"avg_ev=`{bucket['avg_ev']:.6f}`"
                )
            examples = bucket.get("example_questions", [])
            for question in examples[:2]:
                lines.append(f"  example=`{question}`")
        lines.append("")

    tools_market_analysis = report.get("tools_market_analysis", {})
    if tools_market_analysis:
        lines.extend(["## Tools / Market", ""])
        for tool, buckets in sorted(tools_market_analysis.items()):
            lines.append(f"- `{tool}`")
            for market_type, bucket in sorted(buckets.items()):
                line = f"  market_type=`{market_type}` count=`{bucket.get('count', 0)}`"
                if bucket.get("avg_confidence") is not None:
                    line += f" avg_confidence=`{bucket['avg_confidence']:.2f}`"
                if bucket.get("avg_edge") is not None:
                    line += f" avg_edge=`{bucket['avg_edge']:.6f}`"
                if bucket.get("avg_ev") is not None:
                    line += f" avg_ev=`{bucket['avg_ev']:.6f}`"
                lines.append(line)
                for question in bucket.get("example_questions", [])[:1]:
                    lines.append(f"  example=`{question}`")
        tools_market_summary = report.get("tools_market_summary", [])
        if tools_market_summary:
            lines.append("")
            lines.append("Summary:")
            for item in tools_market_summary:
                lines.append(f"- {item}")
        lines.append("")

    settlement_tracker = report.get("settlement_update_tracker", {})
    if settlement_tracker:
        lines.extend(["## Settlement Update Tracker", ""])
        lines.append(
            f"- Accuracy store updates observed: `{settlement_tracker.get('accuracy_store_updates', 0)}`"
        )
        settled_counts = settlement_tracker.get("settled_status_counts", {})
        lines.append(
            f"- Settled statuses visible: won=`{settled_counts.get('won', 0)}`, lost=`{settled_counts.get('lost', 0)}`"
        )
        lines.append(
            f"- New settlements visible in bundle: `{settlement_tracker.get('has_new_settlements')}`"
        )
        if settlement_tracker.get("likely_accuracy_static_due_to_no_settlement"):
            lines.append(
                "- Accuracy unchanged likely because no new settled wins/losses were visible."
            )
        lines.append("")

    cause_hints = report.get("cause_hints", [])
    if cause_hints:
        lines.extend(["## Cause Hints", ""])
        for hint in cause_hints:
            lines.append(f"- {hint}")
        lines.append("")

    lines.extend(["## Observations", ""])
    for observation in report.get("observations", []):
        lines.append(f"- {observation}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Path to a Pearl logs zip bundle.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory where summary files will be written.",
    )
    parser.add_argument(
        "--polymarket-live-check",
        action="store_true",
        help="For Polymarket bundles, query the live CLOB to inspect min_order_size platform constraints for no-bets.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the analyzer."""
    args = parse_args()
    bundle = args.bundle.expanduser().resolve()
    output_dir = args.output_dir

    sessions: List[SessionSummary] = []
    for name, lines in iter_zip_text_files(bundle):
        if name.endswith("_agent.log") or name.endswith("_prev_agent.log"):
            sessions.append(analyze_session(name, lines))

    report = build_overview(
        bundle, sessions, polymarket_live_check=args.polymarket_live_check
    )
    markdown = render_markdown(report)
    json_output = json.dumps(report, indent=2, sort_keys=True)

    if output_dir is None:
        print(markdown)
        print(json_output)
        return

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = bundle.stem
    (output_dir / f"{stem}_summary.md").write_text(markdown)
    (output_dir / f"{stem}_summary.json").write_text(json_output)
    print(f"Wrote reports to {output_dir}")


if __name__ == "__main__":
    main()
