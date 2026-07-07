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

"""Trader-local reader for BalanceTracker.Deposit events.

Adds a helper on top of the same ABI as the vendored balance_tracker
contract, kept trader-local so trader's off-chain ROI accounting can read
per-Safe pre-deposit history without modifying the third-party vendored
package.
"""

from aea.configurations.base import PublicId

PUBLIC_ID = PublicId.from_str("valory/mech_prepaid_reader:0.1.0")
