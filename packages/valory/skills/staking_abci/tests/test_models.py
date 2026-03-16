# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for staking_abci models."""

import platform
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.staking_abci.models import StakingParams, get_store_path


class TestGetStorePath:
    """Tests for the get_store_path helper function."""

    def test_missing_store_path_raises(self) -> None:
        """Missing store_path key raises ValueError."""
        with pytest.raises(ValueError, match="path to the store must be provided"):
            get_store_path({})

    def test_empty_store_path_raises(self) -> None:
        """Empty string store_path raises ValueError."""
        with pytest.raises(ValueError, match="path to the store must be provided"):
            get_store_path({"store_path": ""})

    def test_non_directory_path_raises(self, tmp_path: Path) -> None:
        """A path that is a file (not a directory) raises ValueError."""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")
        with pytest.raises(ValueError, match="is not a directory or is not accessible"):
            get_store_path({"store_path": str(file_path)})

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        """A path that does not exist raises ValueError."""
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises(ValueError, match="is not a directory or is not accessible"):
            get_store_path({"store_path": str(nonexistent)})

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="chmod does not restrict permissions on Windows",
    )
    def test_non_writable_directory_raises(self, tmp_path: Path) -> None:
        """A directory without write permissions raises ValueError."""
        read_only_dir = tmp_path / "read_only"
        read_only_dir.mkdir()
        # Remove write permission
        read_only_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with pytest.raises(
                ValueError, match="is not a directory or is not accessible"
            ):
                get_store_path({"store_path": str(read_only_dir)})
        finally:
            # Restore permissions so pytest can clean up
            read_only_dir.chmod(stat.S_IRWXU)

    @pytest.mark.skipif(
        platform.system() == "Windows",
        reason="chmod does not restrict permissions on Windows",
    )
    def test_non_readable_directory_raises(self, tmp_path: Path) -> None:
        """A directory without read permissions raises ValueError."""
        no_read_dir = tmp_path / "no_read"
        no_read_dir.mkdir()
        # Remove read permission
        no_read_dir.chmod(stat.S_IWUSR | stat.S_IXUSR)
        try:
            with pytest.raises(
                ValueError, match="is not a directory or is not accessible"
            ):
                get_store_path({"store_path": str(no_read_dir)})
        finally:
            # Restore permissions so pytest can clean up
            no_read_dir.chmod(stat.S_IRWXU)

    def test_valid_directory_returns_path(self, tmp_path: Path) -> None:
        """A valid writable directory returns a Path object."""
        result = get_store_path({"store_path": str(tmp_path)})
        assert isinstance(result, Path)
        assert result == tmp_path


class TestStakingParamsInit:
    """Tests for StakingParams.__init__."""

    def test_init_sets_attributes(self, tmp_path: Path) -> None:
        """Test that StakingParams init sets all required attributes from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = StakingParams(
                skill_context=mock_skill_context,
                staking_contract_address="0xStaking",
                staking_interaction_sleep_time=30,
                mech_activity_checker_contract="0xMechChecker",
                store_path=str(tmp_path),
            )
        assert params.staking_contract_address == "0xStaking"
        assert params.staking_interaction_sleep_time == 30
        assert params.mech_activity_checker_contract == "0xMechChecker"
        assert params.store_path == tmp_path

    def test_init_calls_super(self, tmp_path: Path) -> None:
        """Test that StakingParams init calls BaseParams.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None) as mock_super:
            StakingParams(
                skill_context=mock_skill_context,
                staking_contract_address="0xStaking",
                staking_interaction_sleep_time=30,
                mech_activity_checker_contract="0xMechChecker",
                store_path=str(tmp_path),
            )
        mock_super.assert_called_once()

    def test_init_invalid_store_path_raises(self) -> None:
        """Test that StakingParams init raises ValueError for invalid store_path."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            with pytest.raises(ValueError, match="path to the store must be provided"):
                StakingParams(
                    skill_context=mock_skill_context,
                    staking_contract_address="0xStaking",
                    staking_interaction_sleep_time=30,
                    mech_activity_checker_contract="0xMechChecker",
                    store_path="",
                )
