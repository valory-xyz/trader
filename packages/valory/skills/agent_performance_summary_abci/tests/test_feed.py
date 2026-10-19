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

"""Tests for the feed file."""

import json
import threading
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci import feed
from packages.valory.skills.agent_performance_summary_abci.feed import (
    EventType,
    FEED_FILE,
    append_event,
    append_message,
    field,
    find_exchange,
    format_amount,
    format_date,
    format_percent,
    market_url,
    read_recent,
    record_event,
)


def _lines(store_path: Path) -> List[Any]:
    """Return the file's lines, parsed."""
    return [
        json.loads(line)
        for line in (store_path / FEED_FILE).read_text().splitlines()
        if line
    ]


class TestAppend:
    """Appending entries."""

    def test_event_line_is_display_ready(self, tmp_path: Path) -> None:
        """An event line carries its type, title and fields as written."""
        fields = [field("Market", "Will it rain?", "https://x/1"), field("Reason", "r")]
        entry = append_event(tmp_path, EventType.MARKET_SKIPPED, fields, ts=100)
        assert entry == {
            "id": 1,
            "ts": 100,
            "kind": "event",
            "type": "market_skipped",
            "title": "Skipped a market",
            "fields": [
                {"label": "Market", "value": "Will it rain?", "url": "https://x/1"},
                {"label": "Reason", "value": "r"},
            ],
        }
        assert _lines(tmp_path) == [entry]

    def test_message_line_carries_client_id_only_when_given(
        self, tmp_path: Path
    ) -> None:
        """A message without a client id has no ``client_id`` key."""
        user = append_message(tmp_path, "user", "hi", client_id="c1", ts=5)
        agent = append_message(tmp_path, "agent", "hello", ts=6)
        assert user == {
            "id": 1,
            "ts": 5,
            "kind": "message",
            "role": "user",
            "text": "hi",
            "client_id": "c1",
        }
        assert "client_id" not in agent
        assert _lines(tmp_path) == [user, agent]

    def test_every_line_ends_with_a_newline(self, tmp_path: Path) -> None:
        """Lines are whole: the file ends with a newline after each append."""
        append_message(tmp_path, "user", "a")
        append_message(tmp_path, "user", "b")
        raw = (tmp_path / FEED_FILE).read_bytes()
        assert raw.endswith(b"\n")
        assert raw.count(b"\n") == 2

    def test_ids_increase_from_the_last_line(self, tmp_path: Path) -> None:
        """The next id follows the last written one, across restarts of the writer."""
        (tmp_path / FEED_FILE).write_text(json.dumps({"id": 41, "ts": 1}) + "\n")
        assert append_message(tmp_path, "user", "a")["id"] == 42
        assert append_message(tmp_path, "user", "b")["id"] == 43

    def test_cut_last_line_is_kept_apart_from_the_next(self, tmp_path: Path) -> None:
        """A line cut mid-write does not merge with the next one."""
        path = tmp_path / FEED_FILE
        path.write_text(json.dumps({"id": 1, "ts": 1}) + "\n" + '{"id": 2, "ts"')
        entry = append_message(tmp_path, "user", "after")
        assert entry["id"] == 2
        lines = path.read_text().splitlines()
        assert lines[1] == '{"id": 2, "ts"'
        assert json.loads(lines[2]) == entry

    def test_concurrent_appends_get_unique_ids(self, tmp_path: Path) -> None:
        """Appends from several threads never share an id."""

        def write() -> None:
            for _ in range(10):
                append_message(tmp_path, "user", "x")

        threads = [threading.Thread(target=write) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert [entry["id"] for entry in _lines(tmp_path)] == list(range(1, 41))

    def test_default_ts_is_now(self, tmp_path: Path) -> None:
        """Without a timestamp the entry is stamped with the current time."""
        with patch.object(feed.time, "time", return_value=1234.9):
            assert append_message(tmp_path, "user", "x")["ts"] == 1234


class TestRecordEvent:
    """The behaviours' writer, which must never raise."""

    def test_writes_the_event(self, tmp_path: Path) -> None:
        """A successful write appends one line."""
        logger = MagicMock()
        record_event(tmp_path, EventType.CONFIG_CHANGED, [], logger)
        assert _lines(tmp_path)[0]["type"] == "config_changed"
        logger.error.assert_not_called()

    def test_failed_write_is_logged(self, tmp_path: Path) -> None:
        """A write failure is logged and swallowed."""
        logger = MagicMock()
        record_event(tmp_path / "missing", EventType.CONFIG_CHANGED, [], logger)
        logger.error.assert_called_once()

    def test_unserialisable_field_is_logged(self, tmp_path: Path) -> None:
        """A field that cannot be written as JSON is logged and swallowed."""
        logger = MagicMock()
        fields = [{"label": "Amount", "value": object()}]
        record_event(tmp_path, EventType.CONFIG_CHANGED, fields, logger)  # type: ignore[list-item]
        logger.error.assert_called_once()
        assert not (tmp_path / FEED_FILE).exists()


class TestRead:
    """Reading recent entries."""

    def test_missing_file_reads_empty(self, tmp_path: Path) -> None:
        """No file means no entries."""
        assert read_recent(tmp_path, 10) == []
        assert find_exchange(tmp_path, "c") == (None, None)

    def test_returns_latest_oldest_first(self, tmp_path: Path) -> None:
        """The latest ``limit`` entries come back in file order."""
        for text in "abcde":
            append_message(tmp_path, "user", text)
        assert [e["text"] for e in read_recent(tmp_path, 3)] == ["c", "d", "e"]

    def test_skips_unparseable_lines(self, tmp_path: Path) -> None:
        """Garbage, non-objects, bad ids and a cut last line are skipped."""
        path = tmp_path / FEED_FILE
        path.write_text(
            "\n".join(
                [
                    json.dumps({"id": 1, "ts": 1, "text": "ok"}),
                    "not json",
                    "[1, 2]",
                    json.dumps({"id": "2"}),
                    json.dumps({"id": True}),
                    json.dumps({"id": 3, "ts": 3, "text": "ok too"}),
                    '{"id": 4, "te',
                ]
            )
        )
        assert [e["id"] for e in read_recent(tmp_path, 10)] == [1, 3]

    def test_blank_first_line_is_skipped(self, tmp_path: Path) -> None:
        """An empty line at the start of the file is not an entry."""
        (tmp_path / FEED_FILE).write_text("\n" + json.dumps({"id": 1, "ts": 1}) + "\n")
        assert [e["id"] for e in read_recent(tmp_path, 10)] == [1]

    def test_reads_across_blocks(self, tmp_path: Path) -> None:
        """Lines spanning the read block boundary are read whole."""
        with patch.object(feed, "_READ_BLOCK_SIZE", 7):
            for text in ["first", "second line", "third"]:
                append_message(tmp_path, "user", text)
            assert [e["text"] for e in read_recent(tmp_path, 10)] == [
                "first",
                "second line",
                "third",
            ]


class TestFindExchange:
    """Finding the lines of an answered message."""

    def test_finds_message_and_reply(self, tmp_path: Path) -> None:
        """The user line and the agent line with its client id are found."""
        append_message(tmp_path, "user", "other", client_id="c0")
        message = append_message(tmp_path, "user", "q", client_id="c1")
        append_event(tmp_path, EventType.TRADE_PLACED, [])
        reply = append_message(tmp_path, "agent", "a", client_id="c1")
        append_message(tmp_path, "agent", "a0", client_id="c0")
        assert find_exchange(tmp_path, "c1") == (message, reply)

    def test_unanswered_message_has_no_reply(self, tmp_path: Path) -> None:
        """A message whose answer failed has only its user line."""
        message = append_message(tmp_path, "user", "q", client_id="c1")
        assert find_exchange(tmp_path, "c1") == (message, None)

    def test_latest_reply_wins(self, tmp_path: Path) -> None:
        """Were a message answered twice, the latest reply is returned."""
        message = append_message(tmp_path, "user", "q", client_id="c1")
        append_message(tmp_path, "agent", "first", client_id="c1")
        latest = append_message(tmp_path, "agent", "second", client_id="c1")
        assert find_exchange(tmp_path, "c1") == (message, latest)

    def test_ignores_lines_that_only_mention_the_id(self, tmp_path: Path) -> None:
        """A line that contains the id in its text is not the message."""
        append_message(tmp_path, "user", 'about "c1"', client_id="c2")
        (tmp_path / FEED_FILE).open("a").write('{"client_id": "c1", "id": \n')
        assert find_exchange(tmp_path, "c1") == (None, None)


class TestFormatting:
    """Display helpers."""

    @pytest.mark.parametrize(
        "amount, is_polymarket, expected",
        [
            (2, True, "$2.00 pUSD"),
            (1234.567, True, "$1,234.57 pUSD"),
            (0.5, False, "0.50 xDAI"),
        ],
    )
    def test_format_amount(
        self, amount: float, is_polymarket: bool, expected: str
    ) -> None:
        """Amounts are in the agent's own token."""
        assert format_amount(amount, is_polymarket) == expected

    @pytest.mark.parametrize(
        "amount, expected",
        [
            (0.025, "0.025 xDAI"),
            (1.5, "1.50 xDAI"),
            (1234.000001, "1,234.000001 xDAI"),
        ],
    )
    def test_format_amount_with_more_decimals(
        self, amount: float, expected: str
    ) -> None:
        """Past two decimals, only the significant ones are shown."""
        assert format_amount(amount, False, max_decimals=6) == expected

    def test_format_percent(self) -> None:
        """A fraction is a whole percentage."""
        assert format_percent(0.926) == "93%"

    def test_format_date(self) -> None:
        """A timestamp is a UTC day without a leading zero."""
        assert format_date(1791763200) == "12 Oct 2026"
        assert format_date(1788912000) == "9 Sep 2026"

    @pytest.mark.parametrize(
        "is_polymarket, market_id, slug, expected",
        [
            (True, "1", "will-it-rain", "https://polymarket.com/market/will-it-rain"),
            (True, "1", None, None),
            (False, "0xabc", None, "https://predict.olas.network/questions/0xabc"),
            (False, None, None, None),
        ],
    )
    def test_market_url(
        self, is_polymarket: bool, market_id: Any, slug: Any, expected: Any
    ) -> None:
        """Polymarket links need the slug; Omen links the market address."""
        assert market_url(is_polymarket, market_id, slug) == expected

    def test_field_omits_empty_url(self) -> None:
        """A field without a link has no ``url`` key."""
        assert field("Market", "m", None) == {"label": "Market", "value": "m"}

    def test_every_event_has_a_title(self) -> None:
        """Each event type maps to its card title."""
        assert {event.title for event in EventType} == {
            "Placed a trade",
            "Skipped a market",
            "Market resolved",
            "Collected a payout",
            "Sold open positions",
            "Changed the configuration",
        }
