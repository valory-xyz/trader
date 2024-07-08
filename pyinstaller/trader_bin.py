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

"""Script for building the AEA responsible for running the trader."""
import os
import sys
from pathlib import Path
import aea.configurations.validation as validation_module

# patch for the _CUR_DIR value
# we need this because pyinstaller generated binaries handle paths differently
validation_module._CUR_DIR = Path(sys._MEIPASS) / validation_module._CUR_DIR
validation_module._SCHEMAS_DIR = os.path.join(validation_module._CUR_DIR, "schemas")

from aea.cli.core import cli
from google.protobuf.descriptor_pb2 import FileDescriptorProto
from aea.mail.base_pb2 import DESCRIPTOR
from multiaddr.codecs.idna import to_bytes as _
from multiaddr.codecs.uint16be import to_bytes as _
from aea_ledger_ethereum.ethereum import *
from aea_ledger_cosmos.cosmos import *
from aea.crypto.registries.base import *

if __name__ == "__main__":
    cli(prog_name="aea")  # pragma: no cover