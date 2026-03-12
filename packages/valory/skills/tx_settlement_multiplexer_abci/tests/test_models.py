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

"""Tests for tx_settlement_multiplexer_abci models."""

from unittest.mock import MagicMock, patch

from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.tx_settlement_multiplexer_abci.models import (
    TxSettlementMultiplexerParams,
)


class TestTxSettlementMultiplexerParamsInit:
    """Tests for TxSettlementMultiplexerParams.__init__."""

    def test_init_sets_attributes(self) -> None:
        """Test that TxSettlementMultiplexerParams init sets all required attributes from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = TxSettlementMultiplexerParams(
                skill_context=mock_skill_context,
                agent_balance_threshold=1000,
                refill_check_interval=60,
            )
        assert params.agent_balance_threshold == 1000
        assert params.refill_check_interval == 60

    def test_init_calls_super(self) -> None:
        """Test that TxSettlementMultiplexerParams init calls BaseParams.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None) as mock_super:
            TxSettlementMultiplexerParams(
                skill_context=mock_skill_context,
                agent_balance_threshold=1000,
                refill_check_interval=60,
            )
        mock_super.assert_called_once()
