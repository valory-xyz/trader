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

"""Tests proving PREDICT-769: local accuracy store not updated for Polystrat.

Level 1 – the data has nowhere to travel:
  The payload that carries bet-placement results must include a `utilized_tools`
  field so that the conditionId→tool mapping can be propagated through the round
  and into synchronized data.  Without this field the mapping is simply lost.

Level 2 – the round must persist the mapping:
  Even if the payload carries a `utilized_tools` value,
  ``PolymarketBetPlacementRound.end_block`` must explicitly read that value out
  of the payload tuple and write it back into ``synchronized_data``.  On the
  original code only ``cached_signed_orders`` was persisted; ``utilized_tools``
  was silently dropped.
"""

import dataclasses
import json
from typing import Any, Dict, cast
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONDITION_ID = "0xdeadbeefdeadbeefdeadbeefdeadbeef"
MECH_TOOL = "prediction-offline"
UTILIZED_TOOLS_JSON = json.dumps({CONDITION_ID: MECH_TOOL}, sort_keys=True)


# ---------------------------------------------------------------------------
# Level 1: Payload must have a `utilized_tools` field
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementPayloadCarriesUtilizedTools:
    """Prove that PolymarketBetPlacementPayload carries a utilized_tools field.

    The original code was missing this field entirely, making it impossible to
    propagate the conditionId->tool mapping needed to update the accuracy store
    at redemption time.
    """

    def test_payload_accepts_utilized_tools_kwarg(self) -> None:
        """Payload must accept utilized_tools at construction."""
        # This would raise TypeError on the original code because the dataclass
        # had no such field.
        payload = PolymarketBetPlacementPayload(
            sender="agent",
            event=Event.BET_PLACEMENT_DONE.value,
            cached_signed_orders="{}",
            utilized_tools=UTILIZED_TOOLS_JSON,
        )
        assert payload.utilized_tools == UTILIZED_TOOLS_JSON

    def test_payload_utilized_tools_defaults_to_none(self) -> None:
        """utilized_tools is optional and defaults to None (no tools info for failed bets)."""
        payload = PolymarketBetPlacementPayload(
            sender="agent",
            event=Event.BET_PLACEMENT_FAILED.value,
        )
        assert payload.utilized_tools is None

    def test_payload_utilized_tools_is_part_of_data_dict(self) -> None:
        """utilized_tools must appear in payload.data so it is included in the consensus value broadcast to other agents."""
        payload = PolymarketBetPlacementPayload(
            sender="agent",
            event=Event.BET_PLACEMENT_DONE.value,
            cached_signed_orders="{}",
            utilized_tools=UTILIZED_TOOLS_JSON,
        )
        # payload.data is the dict that gets serialised for consensus.
        # Without this key the round can never see the value.
        assert "utilized_tools" in payload.data
        assert payload.data["utilized_tools"] == UTILIZED_TOOLS_JSON

    def test_payload_is_a_dataclass_field(self) -> None:
        """utilized_tools must be a proper dataclass field (not a runtime attribute)."""
        field_names = {
            f.name for f in dataclasses.fields(PolymarketBetPlacementPayload)
        }
        assert "utilized_tools" in field_names, (
            "PolymarketBetPlacementPayload is missing the 'utilized_tools' dataclass field. "
            "Without it the conditionId→tool mapping cannot be carried through consensus."
        )


# ---------------------------------------------------------------------------
# Level 2: Round must persist utilized_tools to synchronized data
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementRoundPersistsUtilizedTools:
    """Prove that PolymarketBetPlacementRound.end_block writes utilized_tools into synchronized data when the payload contains a non-None value.

    The original end_block only saved cached_signed_orders; utilized_tools was
    silently discarded after every successful bet placement.
    """

    def _make_round(self) -> PolymarketBetPlacementRound:
        """Build a minimal round instance."""
        synced_data = MagicMock(spec=SynchronizedData)
        synced_data.update.return_value = synced_data
        context = MagicMock()
        return PolymarketBetPlacementRound(
            synchronized_data=synced_data, context=context
        )

    def test_utilized_tools_written_to_synced_data_on_success(self) -> None:
        """When the consensus payload has utilized_tools set, end_block must persist them so the redeem behaviour can later look up which tool was used for each conditionId.

        On the original code this assertion fails because end_block never called
        synced_data.update(utilized_tools=...).
        """
        round_ = self._make_round()

        # Payload tuple order matches dataclass field order (excluding sender).
        # Post-fix fields: tx_submitter, tx_hash, mocking_mode, event, cached_signed_orders, utilized_tools
        # The round must read event from [-3], cached_orders from [-2], utilized_tools from [-1].
        payload_values = (
            None,  # tx_submitter
            None,  # tx_hash
            False,  # mocking_mode
            Event.BET_PLACEMENT_DONE.value,  # event
            "{}",  # cached_signed_orders
            UTILIZED_TOOLS_JSON,  # utilized_tools  ← new field
        )

        with patch.object(
            PolymarketBetPlacementRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=payload_values,
        ):
            # We need super().end_block() to return something non-None.
            with patch(
                "packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement.TxPreparationRound.end_block",
                return_value=(round_.synchronized_data, Event.BET_PLACEMENT_DONE),
            ):
                result = round_.end_block()

        assert result is not None, "end_block returned None unexpectedly"
        synced_data_out, event_out = result

        # The round must have called .update(utilized_tools=UTILIZED_TOOLS_JSON)
        # at some point.  Collect all kwargs passed to every .update() call.
        all_update_kwargs: Dict[str, Any] = {}
        update_mock = cast(MagicMock, round_.synchronized_data.update)
        for call in update_mock.call_args_list:
            all_update_kwargs.update(call.kwargs)

        assert "utilized_tools" in all_update_kwargs, (
            "PolymarketBetPlacementRound.end_block never called "
            "synchronized_data.update(utilized_tools=...). "
            "The conditionId→tool mapping is silently dropped after every bet."
        )
        assert all_update_kwargs["utilized_tools"] == UTILIZED_TOOLS_JSON

    def test_utilized_tools_not_written_when_none(self) -> None:
        """When utilized_tools is None (e.g. a failed placement) end_block must NOT overwrite the existing utilized_tools in synchronized data."""
        round_ = self._make_round()

        # Post-fix 6-element tuple; utilized_tools is None for a failed placement.
        payload_values = (
            None,
            None,
            False,
            Event.BET_PLACEMENT_FAILED.value,
            None,  # cached_signed_orders
            None,  # utilized_tools – None for failed placement
        )

        with patch.object(
            PolymarketBetPlacementRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=payload_values,
        ):
            with patch(
                "packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement.TxPreparationRound.end_block",
                return_value=(round_.synchronized_data, Event.BET_PLACEMENT_FAILED),
            ):
                round_.end_block()

        # Verify .update() was never called with utilized_tools
        update_mock = cast(MagicMock, round_.synchronized_data.update)
        for call in update_mock.call_args_list:
            assert "utilized_tools" not in call.kwargs, (
                "end_block must not overwrite utilized_tools when the payload "
                "carries None (i.e. the bet did not succeed)."
            )
