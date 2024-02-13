# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Custom objects for the trader ABCI application."""

from typing import Any

from packages.valory.skills.abstract_round_abci.models import BaseParams


class ParamsServerParams(BaseParams):
    """A model to represent the trader params."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.service_endpoint_base: str = self._ensure("service_endpoint_base", kwargs, str)
        self.update_secret: str = self._ensure("update_secret", kwargs, str)
        super().__init__(*args, **kwargs)
