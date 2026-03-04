# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains tests for the payloads of agent_performance_summary_abci."""

from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
    UpdateAchievementsPayload,
)


class TestFetchPerformanceDataPayload:
    """Tests for FetchPerformanceDataPayload."""

    def test_payload_vote_true(self) -> None:
        """Test FetchPerformanceDataPayload with vote=True."""
        payload = FetchPerformanceDataPayload(sender="sender", vote=True)
        assert payload.vote is True
        assert payload.sender == "sender"

    def test_payload_vote_false(self) -> None:
        """Test FetchPerformanceDataPayload with vote=False."""
        payload = FetchPerformanceDataPayload(sender="sender", vote=False)
        assert payload.vote is False

    def test_payload_data(self) -> None:
        """Test FetchPerformanceDataPayload data property."""
        payload = FetchPerformanceDataPayload(sender="sender", vote=True)
        assert payload.data == {"vote": True}

    def test_payload_from_json_roundtrip(self) -> None:
        """Test FetchPerformanceDataPayload JSON roundtrip."""
        payload = FetchPerformanceDataPayload(sender="sender", vote=True)
        restored = FetchPerformanceDataPayload.from_json(payload.json)
        assert restored == payload

    def test_payload_from_json_roundtrip_false(self) -> None:
        """Test FetchPerformanceDataPayload JSON roundtrip with vote=False."""
        payload = FetchPerformanceDataPayload(sender="sender", vote=False)
        restored = FetchPerformanceDataPayload.from_json(payload.json)
        assert restored == payload


class TestUpdateAchievementsPayload:
    """Tests for UpdateAchievementsPayload."""

    def test_payload_vote_true(self) -> None:
        """Test UpdateAchievementsPayload with vote=True."""
        payload = UpdateAchievementsPayload(sender="sender", vote=True)
        assert payload.vote is True
        assert payload.sender == "sender"

    def test_payload_vote_false(self) -> None:
        """Test UpdateAchievementsPayload with vote=False."""
        payload = UpdateAchievementsPayload(sender="sender", vote=False)
        assert payload.vote is False

    def test_payload_data(self) -> None:
        """Test UpdateAchievementsPayload data property."""
        payload = UpdateAchievementsPayload(sender="sender", vote=True)
        assert payload.data == {"vote": True}

    def test_payload_from_json_roundtrip(self) -> None:
        """Test UpdateAchievementsPayload JSON roundtrip."""
        payload = UpdateAchievementsPayload(sender="sender", vote=True)
        restored = UpdateAchievementsPayload.from_json(payload.json)
        assert restored == payload

    def test_payload_from_json_roundtrip_false(self) -> None:
        """Test UpdateAchievementsPayload JSON roundtrip with vote=False."""
        payload = UpdateAchievementsPayload(sender="sender", vote=False)
        restored = UpdateAchievementsPayload.from_json(payload.json)
        assert restored == payload
