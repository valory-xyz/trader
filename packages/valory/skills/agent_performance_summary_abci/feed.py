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

"""The agent's feed: one append-only JSON-lines file of events and chat messages.

Pearl reads this file through the middleware, whether the agent runs or not,
so the line format is a contract: every line is a whole JSON object ending in
a newline, and a line that does not parse (a write cut short) is skipped.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
    POLYMARKET_MARKET_BASE_URL,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    PREDICT_BASE_URL,
)

FEED_FILE = "feed.jsonl"

KIND_EVENT = "event"
KIND_MESSAGE = "message"
ROLE_USER = "user"
ROLE_AGENT = "agent"

_READ_BLOCK_SIZE = 64 * 1024
_NEWLINE = b"\n"
# Handlers and behaviours both append; the lock keeps ids unique and lines whole.
_APPEND_LOCK = threading.Lock()

Field = Dict[str, str]
FeedEntry = Dict[str, Any]


class EventType(Enum):
    """The events the agent writes, with the title Pearl shows for each."""

    TRADE_PLACED = "trade_placed"
    MARKET_SKIPPED = "market_skipped"
    MARKET_RESOLVED = "market_resolved"
    PAYOUT_COLLECTED = "payout_collected"
    POSITIONS_SOLD = "positions_sold"
    CONFIG_CHANGED = "config_changed"

    @property
    def title(self) -> str:
        """Return the title shown on the event's card."""
        return _EVENT_TITLES[self]


_EVENT_TITLES = {
    EventType.TRADE_PLACED: "Placed a trade",
    EventType.MARKET_SKIPPED: "Skipped a market",
    EventType.MARKET_RESOLVED: "Market resolved",
    EventType.PAYOUT_COLLECTED: "Collected a payout",
    EventType.POSITIONS_SOLD: "Sold open positions",
    EventType.CONFIG_CHANGED: "Changed the configuration",
}


def field(label: str, value: str, url: Optional[str] = None) -> Field:
    """Build one display-ready field of an event card.

    :param label: the field's label.
    :param value: the field's value, as shown.
    :param url: an optional link for the value.
    :return: the field.
    """
    entry = {"label": label, "value": value}
    if url:
        entry["url"] = url
    return entry


def market_url(
    is_polymarket: bool, market_id: Optional[str], slug: Optional[str] = None
) -> Optional[str]:
    """Return the public page of a market, when it can be built.

    :param is_polymarket: whether the market is on Polymarket.
    :param market_id: the Omen market (FPMM) address.
    :param slug: the Polymarket market slug.
    :return: the URL, or ``None``.
    """
    if is_polymarket:
        return f"{POLYMARKET_MARKET_BASE_URL}/{slug}" if slug else None
    return f"{PREDICT_BASE_URL}/{market_id}" if market_id else None


def format_amount(amount: float, is_polymarket: bool, max_decimals: int = 2) -> str:
    """Format an amount in the agent's own token: pUSD on Polymarket, xDAI on Omen.

    :param amount: the amount, in whole tokens.
    :param is_polymarket: whether the agent trades on Polymarket.
    :param max_decimals: the most decimals to show; zeros past the second are dropped.
    :return: the display text.
    """
    text = f"{amount:,.{max_decimals}f}"
    if max_decimals > 2:
        whole, _, fraction = text.partition(".")
        text = f"{whole}.{fraction.rstrip('0').ljust(2, '0')}"
    if is_polymarket:
        return f"${text} pUSD"
    return f"{text} xDAI"


def format_percent(fraction: float) -> str:
    """Format a 0-1 fraction as a whole percentage.

    :param fraction: the fraction.
    :return: the display text.
    """
    return f"{round(fraction * 100)}%"


def format_date(timestamp: int) -> str:
    """Format a unix timestamp as a UTC day, e.g. ``12 Oct 2026``.

    :param timestamp: unix seconds.
    :return: the display text.
    """
    day = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return f"{day.day} {day.strftime('%b %Y')}"


def _parse(line: bytes) -> Optional[FeedEntry]:
    """Return the entry on a line, or ``None`` if the line is not a whole entry.

    :param line: the raw line, without its newline.
    :return: the entry, or ``None``.
    """
    try:
        entry = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if not isinstance(entry, dict):
        return None
    entry_id = entry.get("id")
    if isinstance(entry_id, bool) or not isinstance(entry_id, int):
        return None
    return entry


def _lines_newest_first(path: Path) -> Iterator[bytes]:
    """Yield the file's non-empty lines from the last to the first.

    Reads blocks from the end, so finding recent entries does not read the
    whole history.

    :param path: the feed file.
    :yield: each line, without its newline.
    """
    try:
        feed_file = open(path, "rb")  # pylint: disable=consider-using-with
    except FileNotFoundError:
        return
    with feed_file:
        position = feed_file.seek(0, os.SEEK_END)
        partial = b""
        while position > 0:
            size = min(_READ_BLOCK_SIZE, position)
            position -= size
            feed_file.seek(position)
            lines = (feed_file.read(size) + partial).split(_NEWLINE)
            # The first piece may be the end of a line that starts in the
            # previous block, so it waits for that block.
            partial = lines.pop(0)
            yield from (line for line in reversed(lines) if line)
        if partial:
            yield partial


def _entries_newest_first(path: Path) -> Iterator[FeedEntry]:
    """Yield the parseable entries from the last to the first.

    :param path: the feed file.
    :yield: each entry.
    """
    for line in _lines_newest_first(path):
        entry = _parse(line)
        if entry is not None:
            yield entry


def _append(store_path: Path, body: Dict[str, Any], ts: Optional[int]) -> FeedEntry:
    """Append one entry with the next id and return it as written.

    :param store_path: the directory holding the feed.
    :param body: the entry without ``id`` and ``ts``.
    :param ts: unix seconds; now when ``None``.
    :return: the entry written.
    """
    path = store_path / FEED_FILE
    with _APPEND_LOCK:
        last = next(_entries_newest_first(path), None)
        entry: FeedEntry = {
            "id": 1 if last is None else last["id"] + 1,
            "ts": int(time.time()) if ts is None else ts,
            **body,
        }
        line = json.dumps(entry, separators=(",", ":")).encode("utf-8") + _NEWLINE
        with open(path, "a+b") as feed_file:
            if feed_file.seek(0, os.SEEK_END) > 0:
                feed_file.seek(-1, os.SEEK_END)
                # A cut last line stays its own (skipped) line, not the start of this one.
                if feed_file.read(1) != _NEWLINE:
                    line = _NEWLINE + line
            feed_file.write(line)
            feed_file.flush()
            os.fsync(feed_file.fileno())
    return entry


def append_event(
    store_path: Path,
    event_type: EventType,
    fields: List[Field],
    ts: Optional[int] = None,
) -> FeedEntry:
    """Append an event line.

    :param store_path: the directory holding the feed.
    :param event_type: the event.
    :param fields: the card's fields, in display order.
    :param ts: unix seconds; now when ``None``.
    :return: the entry written.
    """
    body = {
        "kind": KIND_EVENT,
        "type": event_type.value,
        "title": event_type.title,
        "fields": fields,
    }
    return _append(store_path, body, ts)


def record_event(
    store_path: Path,
    event_type: EventType,
    fields: List[Field],
    logger: Logger,
) -> None:
    """Append an event line; a failed write is logged, never raised.

    The feed only reports what the agent did, so it must not stop it.

    :param store_path: the directory holding the feed.
    :param event_type: the event.
    :param fields: the card's fields, in display order.
    :param logger: where to log a failed write.
    """
    try:
        append_event(store_path, event_type, fields)
    except OSError as e:
        logger.error(f"Could not write the {event_type.value} event to the feed: {e}")


def append_message(
    store_path: Path,
    role: str,
    text: str,
    client_id: Optional[str] = None,
    ts: Optional[int] = None,
) -> FeedEntry:
    """Append a chat message line.

    :param store_path: the directory holding the feed.
    :param role: ``user`` or ``agent``.
    :param text: the message.
    :param client_id: Pearl's id of the user message this line is or answers.
    :param ts: unix seconds; now when ``None``.
    :return: the entry written.
    """
    body: Dict[str, Any] = {"kind": KIND_MESSAGE, "role": role, "text": text}
    if client_id is not None:
        body["client_id"] = client_id
    return _append(store_path, body, ts)


def read_recent(store_path: Path, limit: int) -> List[FeedEntry]:
    """Return up to ``limit`` of the latest entries, oldest first.

    :param store_path: the directory holding the feed.
    :param limit: the most entries to return.
    :return: the entries.
    """
    entries: List[FeedEntry] = []
    for entry in _entries_newest_first(store_path / FEED_FILE):
        if len(entries) >= limit:
            break
        entries.append(entry)
    return entries[::-1]


def find_exchange(
    store_path: Path, client_id: str
) -> Tuple[Optional[FeedEntry], Optional[FeedEntry]]:
    """Return the user line with this ``client_id`` and the agent line answering it.

    :param store_path: the directory holding the feed.
    :param client_id: Pearl's id of the user message.
    :return: the user line and the reply, each ``None`` when not written.
    """
    needle = json.dumps(client_id).encode("utf-8")
    message: Optional[FeedEntry] = None
    reply: Optional[FeedEntry] = None
    for line in _lines_newest_first(store_path / FEED_FILE):
        # Most lines are not about this message, and parsing them all is the cost.
        if needle not in line:
            continue
        entry = _parse(line)
        if (
            entry is None
            or entry.get("kind") != KIND_MESSAGE
            or entry.get("client_id") != client_id
        ):
            continue
        if entry.get("role") == ROLE_AGENT and reply is None:
            reply = entry
        elif entry.get("role") == ROLE_USER:
            message = entry
            # The reply is always written after the message it answers.
            break
    return message, reply
