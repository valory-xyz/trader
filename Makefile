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
	gitleaks detect --report-format json --report-path leak_report

# generate abci docstrings
# update copyright headers
# generate latest hashes for updated packages
.PHONY: generators
generators: clean-cache fix-abci-app-specs
	tox -e abci-docstrings
	tomte format-copyright --author valory --exclude-part abci --exclude-part http_client --exclude-part http_server --exclude-part ipfs --exclude-part ledger --exclude-part p2p_libp2p_client --exclude-part erc20 --exclude-part gnosis_safe --exclude-part gnosis_safe_proxy_factory --exclude-part mech --exclude-part mech_marketplace --exclude-part multisend --exclude-part service_registry --exclude-part protocols --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part mech_interact_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part websocket_client --exclude-part contract_subscription --exclude-part agent_registry
	autonomy packages lock
	tox -e fix-doc-hashes

.PHONY: common-checks-1
common-checks-1:
	tomte check-copyright --author valory --exclude-part abci --exclude-part http_client --exclude-part http_server --exclude-part ipfs --exclude-part ledger --exclude-part p2p_libp2p_client --exclude-part erc20 --exclude-part gnosis_safe --exclude-part gnosis_safe_proxy_factory --exclude-part mech --exclude-part mech_marketplace --exclude-part multisend --exclude-part service_registry --exclude-part protocols --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part mech_interact_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part websocket_client --exclude-part contract_subscription -	tomte format-copyright --author valory --exclude-part abci --exclude-part http_client --exclude-part http_server --exclude-part ipfs --exclude-part ledger --exclude-part p2p_libp2p_client --exclude-part erc20 --exclude-part gnosis_safe --exclude-part gnosis_safe_proxy_factory --exclude-part mech --exclude-part mech_marketplace --exclude-part multisend --exclude-part service_registry --exclude-part protocols --exclude-part abstract_abci --exclude-part abstract_round_abci --exclude-part mech_interact_abci --exclude-part registration_abci --exclude-part reset_pause_abci --exclude-part termination_abci --exclude-part transaction_settlement_abci --exclude-part websocket_client --exclude-part contract_subscription --exclude-part agent_registry
	tomte check-doc-links
	tox -p -e check-hash -e check-packages -e check-doc-hashes -e analyse-service

.PHONY: common-checks-2
common-checks-2:
	tox -e check-abci-docstrings
	tox -e check-abciapp-specs
	tox -e check-dependencies
	tox -e check-handlers

.PHONY: all-checks
all-checks: format code-checks security generators common-checks-1 common-checks-2

.PHONY: fix-abci-app-specs
fix-abci-app-specs:
	autonomy analyse fsm-specs --update --app-class StakingAbciApp --package packages/valory/skills/staking_abci
	autonomy analyse fsm-specs --update --app-class MarketManagerAbciApp --package packages/valory/skills/market_manager_abci
	autonomy analyse fsm-specs --update --app-class DecisionMakerAbciApp --package packages/valory/skills/decision_maker_abci
	autonomy analyse fsm-specs --update --app-class TraderAbciApp --package packages/valory/skills/trader_abci
	autonomy analyse fsm-specs --update --app-class TxSettlementMultiplexerAbciApp --package packages/valory/skills/tx_settlement_multiplexer_abci
	echo "Successfully validated abcis!"

protolint_install:
	GO111MODULE=on GOPATH=~/go go get -u -v github.com/yoheimuta/protolint/cmd/protolint@v0.27.0


AUTONOMY_VERSION := v$(shell autonomy --version | grep -oP '(?<=version\s)\S+')
AEA_VERSION := v$(shell aea --version | grep -oP '(?<=version\s)\S+')
MECH_INTERACT_VERSION := $(shell git ls-remote --tags --sort="v:refname" https://github.com/valory-xyz/mech-interact.git | tail -n1 | sed 's|.*refs/tags/||')

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



.PHONY: poetry-install
poetry-install: 

	PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry install
	PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring poetry run pip install --upgrade --force-reinstall setuptools==59.5.0  # fix for KeyError: 'setuptools._distutils.compilers'

.PHONY: build-agent-runner
build-agent-runner: poetry-install  agent
	poetry run pyinstaller \
	--collect-data eth_account \
	--collect-all aea \
	--collect-all autonomy \
	--collect-all aea_ledger_ethereum \
	--collect-all aea_ledger_cosmos \
	--collect-all aea_ledger_ethereum_flashbots \
	--hidden-import aea_ledger_ethereum \
	--hidden-import aea_ledger_cosmos \
	--hidden-import aea_ledger_ethereum_flashbots \
	$(shell poetry run python get_pyinstaller_dependencies.py) \
	--onefile pyinstaller/trader_bin.py \
	--name agent_runner_bin
	./dist/agent_runner_bin --version 
	

.PHONY: build-agent-runner-mac
build-agent-runner-mac: poetry-install  agent
	poetry run pyinstaller \
	--collect-data eth_account \
	--collect-all aea \
	--collect-all autonomy \
	--collect-all aea_ledger_ethereum \
	--collect-all aea_ledger_cosmos \
	--collect-all aea_ledger_ethereum_flashbots \
	--hidden-import aea_ledger_ethereum \
	--hidden-import aea_ledger_cosmos \
	--hidden-import aea_ledger_ethereum_flashbots \
	$(shell poetry run python get_pyinstaller_dependencies.py) \
	--onefile pyinstaller/trader_bin.py \
	--codesign-identity "${SIGN_ID}" \
	--name agent_runner_bin
	./dist/agent_runner_bin 1>/dev/null
	./dist/agent_runner_bin --version


./hash_id: ./packages/packages.json
	cat ./packages/packages.json | jq -r '.dev | to_entries[] | select(.key | startswith("agent/")) | .value' > ./hash_id

./agent_id: ./packages/packages.json
	cat ./packages/packages.json | jq -r '.dev | to_entries[] | select(.key | startswith("agent/")) | .key | sub("^agent/"; "")' > ./agent_id

./agent:  poetry-install ./hash_id
	@if [ ! -d "agent" ]; then \
		poetry run autonomy -s fetch --remote `cat ./hash_id` --alias agent; \
	fi \


./agent.zip: ./agent
	zip -r ./agent.zip ./agent

./agent.tar.gz: ./agent
	tar czf ./agent.tar.gz ./agent

./agent/ethereum_private_key.txt: ./agent
	poetry run bash -c "cd ./agent; autonomy  -s generate-key ethereum; autonomy  -s add-key ethereum ethereum_private_key.txt; autonomy -s issue-certificates;"


# Configuration
TIMEOUT := 20
COMMAND := cd ./agent && SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_STORE_PATH=/tmp ../dist/agent_runner_bin -s run
SEARCH_STRING := Starting AEA


# Determine OS and set appropriate options
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    # macOS specific settings
    MKTEMP = mktemp -t tmp
else ifeq ($(OS),Windows_NT)
    # Windows specific settings
    MKTEMP = echo $$(cygpath -m "$$(mktemp -t tmp.XXXXXX)")
else
    # Linux and other Unix-like systems
    MKTEMP = mktemp
endif

.PHONY: check-agent-runner
check-agent-runner:
	python check_agent_runner.py
