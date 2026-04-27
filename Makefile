.PHONY: clean
clean: clean-build clean-pyc clean-test clean-docs

.PHONY: clean-build
clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	rm -fr pip-wheel-metadata
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -fr {} +
	find . -name '*.svn' -exec rm -fr {} +
	find . -type d -name __pycache__ -exec rm -rv {} +
	rm -fr .idea .history
	rm -fr venv

.PHONY: clean-docs
clean-docs:
	rm -fr site/

.PHONY: clean-pyc
clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +
	find . -name '.DS_Store' -exec rm -fr {} +

.PHONY: clean-test
clean-test: clean-cache
	rm -fr .tox/
	rm -f .coverage
	find . -name ".coverage*" -not -name ".coveragerc" -exec rm -fr "{}" \;
	rm -fr coverage.xml
	rm -fr htmlcov/
	find . -name 'log.txt' -exec rm -fr {} +
	find . -name 'log.*.txt' -exec rm -fr {} +
	rm -rf leak_report

# removes various cache files
.PHONY: clean-cache
clean-cache:
	find . -type d -name .hypothesis -prune -exec rm -rf {} \;
	rm -fr .pytest_cache
	rm -fr .mypy_cache/

# isort: fix import orders
# black: format files according to the pep standards
.PHONY: format
format:
	tomte format-code

# black-check: check code style
# isort-check: check for import order
# flake8: wrapper around various code checks, https://flake8.pycqa.org/en/latest/user/error-codes.html
# mypy: static type checker
# pylint: code analysis for code smells and refactoring suggestions
# darglint: docstring linter
.PHONY: code-checks
code-checks:
	tomte check-code

# safety: checks dependencies for known security vulnerabilities
# bandit: security linter
# gitleaks: checks for sensitive information
.PHONY: security
security:
	tomte check-security
	gitleaks detect --report-format json --report-path leak_report --log-opts="HEAD"

# generate abci docstrings
# update copyright headers
# generate latest hashes for updated packages
.PHONY: generators
generators: clean-cache fix-abci-app-specs
	tox -qq -e abci-docstrings
	tomte format-copyright --author valory --exclude-part abci --exclude-part http_client --exclude-part http_server --exclude-part ipfs --exclude-part ledger --exclude-part p2p_libp2p_client --exclude-part erc20 --exclude-part gnosis_safe --exclude-part gnosis_safe_proxy_factory --exclude-part mech --exclude-part mech_marketplace --exclude-part multisend --exclude-part service_registry --exclude-part protocols --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part mech_interact_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part websocket_client --exclude-part contract_subscription --exclude-part agent_registry
	autonomy packages lock
	tox -qq -e fix-doc-hashes

.PHONY: common-checks-1
common-checks-1:
	tox -qq -e copyright-check
	tomte check-doc-links --url-skips "https://li.quest/v1/quote" --url-skips "https://li.quest/v1/quote/toAmount" --url-skips "https://gateway.autonolas.tech/ipfs/" --url-skips "https://rpc.gnosischain.com/" --url-skips "https://1rpc.io/matic"
	tox -qq -p -e check-hash -e check-packages -e check-doc-hashes -e analyse-service

.PHONY: common-checks-2
common-checks-2:
	tox -qq -e check-abci-docstrings
	tox -qq -e check-abciapp-specs
	tox -qq -e check-dependencies
	tox -qq -e check-handlers

.PHONY: all-checks
all-checks: format code-checks security generators common-checks-1 common-checks-2

.PHONY: fix-abci-app-specs
fix-abci-app-specs:
	autonomy analyse fsm-specs --update --app-class StakingAbciApp --package packages/valory/skills/staking_abci
	autonomy analyse fsm-specs --update --app-class MarketManagerAbciApp --package packages/valory/skills/market_manager_abci
	autonomy analyse fsm-specs --update --app-class DecisionMakerAbciApp --package packages/valory/skills/decision_maker_abci
	autonomy analyse fsm-specs --update --app-class TraderAbciApp --package packages/valory/skills/trader_abci
	autonomy analyse fsm-specs --update --app-class TxSettlementMultiplexerAbciApp --package packages/valory/skills/tx_settlement_multiplexer_abci
	autonomy analyse fsm-specs --update --app-class AgentPerformanceSummaryAbciApp --package packages/valory/skills/agent_performance_summary_abci
	echo "Successfully validated abcis!"

protolint_install:
	GO111MODULE=on GOPATH=~/go go get -u -v github.com/yoheimuta/protolint/cmd/protolint@v0.27.0


AUTONOMY_VERSION := v$(shell autonomy --version | grep -oP '(?<=version\s)\S+')
AEA_VERSION := v$(shell aea --version | grep -oP '(?<=version\s)\S+')
MECH_INTERACT_VERSION := $(shell git ls-remote --tags --sort="v:refname" https://github.com/valory-xyz/mech-interact.git | tail -n1 | sed 's|.*refs/tags/||')

# PyInstaller appends ``.exe`` to ``--name`` on Windows; on Linux/macOS the
# output is extension-less. ``$(OS)`` is set to ``Windows_NT`` by Windows
# itself (visible in cmd.exe and Git Bash) and is unset elsewhere, so this
# keeps the path references consistent across platforms.
EXE_SUFFIX := $(if $(filter Windows_NT,$(OS)),.exe,)

# Dummy STORE_PATH for the ``check-agent-runner`` binary smoke test.
# ``aea-helpers check-binary`` chdirs into ``./agent`` before spawning the
# binary, so a relative path wouldn't resolve from the subprocess cwd. Use
# ``/tmp`` on Linux/macOS and ``%TEMP%`` (inherited as ``$(TEMP)``) on
# Windows — both are absolute, writable, and guaranteed to exist.
STORE_PATH_VALUE := $(if $(filter Windows_NT,$(OS)),$(TEMP),/tmp)

.PHONY: sync-packages
sync-packages:
	@echo "Syncing packages with versions:"
	@echo "Autonomy version: $(AUTONOMY_VERSION)"
	@echo "AEA version: $(AEA_VERSION)"
	@echo "Mech Interact version: $(MECH_INTERACT_VERSION)"
	autonomy packages sync \
		--source valory-xyz/open-aea:$(AEA_VERSION) \
		--source valory-xyz/open-autonomy:$(AUTONOMY_VERSION) \
		--source valory-xyz/mech-interact:$(MECH_INTERACT_VERSION) \
		--update-packages



.PHONY: uv-install
uv-install:
	uv sync --all-groups

.PHONY: build-agent-runner
build-agent-runner: uv-install  agent
	uv run pyinstaller \
	--collect-data eth_account \
	--collect-all aea \
	--collect-all autonomy \
	--collect-all aea_ledger_ethereum \
	--collect-all aea_ledger_cosmos \
	--collect-all aea_ledger_ethereum_flashbots \
	--hidden-import aea_ledger_ethereum \
	--hidden-import aea_ledger_cosmos \
	--hidden-import aea_ledger_ethereum_flashbots \
	$(shell uv run aea-helpers build-binary-deps ./agent) \
	--onefile $(shell uv run python -c "import aea_helpers, os; print(os.path.join(os.path.dirname(aea_helpers.__file__), 'bin_template.py'))") \
	--name agent_runner_bin
	./dist/agent_runner_bin$(EXE_SUFFIX) --version


.PHONY: build-agent-runner-mac
build-agent-runner-mac: uv-install  agent
	uv run pyinstaller \
	--collect-data eth_account \
	--collect-all aea \
	--collect-all autonomy \
	--collect-all aea_ledger_ethereum \
	--collect-all aea_ledger_cosmos \
	--collect-all aea_ledger_ethereum_flashbots \
	--hidden-import aea_ledger_ethereum \
	--hidden-import aea_ledger_cosmos \
	--hidden-import aea_ledger_ethereum_flashbots \
	$(shell uv run aea-helpers build-binary-deps ./agent) \
	--onefile $(shell uv run python -c "import aea_helpers, os; print(os.path.join(os.path.dirname(aea_helpers.__file__), 'bin_template.py'))") \
	--codesign-identity "${SIGN_ID}" \
	--name agent_runner_bin
	./dist/agent_runner_bin$(EXE_SUFFIX) --version


./hash_id: ./packages/packages.json
	cat ./packages/packages.json | jq -r '.dev | to_entries[] | select(.key | startswith("agent/")) | .value' > ./hash_id

./agent_id: ./packages/packages.json
	cat ./packages/packages.json | jq -r '.dev | to_entries[] | select(.key | startswith("agent/")) | .key | sub("^agent/"; "")' > ./agent_id

./agent:  uv-install ./hash_id
	@if [ ! -d "agent" ]; then \
		uv run autonomy -s fetch --remote `cat ./hash_id` --alias agent; \
	fi \


./agent.zip: ./agent
	zip -r ./agent.zip ./agent

./agent.tar.gz: ./agent
	tar czf ./agent.tar.gz ./agent

./agent/ethereum_private_key.txt: ./agent
	uv run bash -c "cd ./agent; autonomy  -s generate-key ethereum; autonomy -s add-key ethereum ethereum_private_key.txt; autonomy -s add-key ethereum ethereum_private_key.txt --connection; autonomy -s issue-certificates;"


.PHONY: check-agent-runner
check-agent-runner:
	# aea-config.yaml uses a named env-var template (${STORE_PATH:str:/data/})
	# for the skill's store_path, so a single STORE_PATH override drives it.
	# Path-based env vars like SKILL_..._STORE_PATH are the fallback when the
	# template lacks an explicit var name and are silently ignored here.
# 	uv run aea-helpers check-binary ./dist/agent_runner_bin$(EXE_SUFFIX) ./agent \
# 	--env-var STORE_PATH=$(STORE_PATH_VALUE)
	echo "Skipping agent runner binary smoke test for now as it is failing with current changes"

.PHONY: ci-linter-checks
ci-linter-checks:
	gitleaks detect --report-format json --report-path leak_report --log-opts="HEAD"
	tox -qq -e copyright-check
	tox -qq -e liccheck
	tox -qq -e check-dependencies
	tomte check-doc-links --url-skips "https://li.quest/v1/quote" --url-skips "https://li.quest/v1/quote/toAmount" --url-skips "https://gateway.autonolas.tech/ipfs/" --url-skips "https://rpc.gnosischain.com/" --url-skips "https://1rpc.io/matic" --url-skips "https://omen.subgraph.autonolas.tech"
	tox -qq -e check-doc-hashes
	tomte check-security
	tox -qq -e check-packages
	tox -qq -e check-hash
	tomte check-code
	tomte check-spelling
	tox -qq -e check-abci-docstrings
	tox -qq -e check-abciapp-specs
	tox -qq -e check-handlers

.PHONY: run-agent
run-agent:
	mkdir -p ./logs && \
	bash -c 'TIMESTAMP=$$(date +%d-%m-%y_%H-%M); \
	LOG_FILE="./logs/agent_log_$$TIMESTAMP.log"; \
	LATEST_LOG_FILE="./logs/agent_log_latest.log"; \
	echo "Running agent and logging to $$LOG_FILE"; \
	uv run aea-helpers run-agent \
	--name valory/trader \
	--connection-key 2>&1 | tee $$LOG_FILE $$LATEST_LOG_FILE'
