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

# pylint: skip-file
# mypy: ignore-errors
# type: ignore
# isort: skip_file

"""PyInstaller entry point of the agent runner binary.

A copy of open-aea-helpers' ``bin_template.py`` that also registers the
``prestart-check`` command, so ``--help`` lists it for Pearl to detect.
"""

import os
import sys
from pathlib import Path

import aea.configurations.validation as validation_module

# Patch for PyInstaller: redirect config paths to the frozen bundle root.
validation_module._CUR_DIR = Path(sys._MEIPASS) / validation_module._CUR_DIR
validation_module._SCHEMAS_DIR = os.path.join(validation_module._CUR_DIR, "schemas")

# These imports ensure PyInstaller bundles the required modules.
from aea.cli.core import cli  # noqa: E402, F401
from aea.crypto.registries.base import *  # noqa: E402, F401, F403
from aea.mail.base_pb2 import DESCRIPTOR  # noqa: E402, F401
from aea_ledger_cosmos.cosmos import *  # noqa: E402, F401, F403
from aea_ledger_ethereum.ethereum import *  # noqa: E402, F401, F403
from google.protobuf.descriptor_pb2 import FileDescriptorProto  # noqa: E402, F401

from prestart_check import prestart_check  # noqa: E402

cli.add_command(prestart_check)

if __name__ == "__main__":
    cli(prog_name="aea")  # pragma: no cover
