SHELL := /bin/bash
ROOT_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

.PHONY: doctor setup test submit reset destroy ssh-web ssh-db ssh-comms help

help: ## Show available commands
	@echo ""
	@echo "=============================================="
	@echo "  STARFALL DEFENCE CORPS ACADEMY"
	@echo "  MOS 4: Eyes Everywhere"
	@echo "=============================================="
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'
	@echo ""

doctor: ## Check your machine is mission-ready (Docker, ports, tools)
	@bash $(ROOT_DIR)/scripts/doctor.sh

setup: ## Deploy the fleet + central collector (3 nodes, telemetry dark)
	@bash $(ROOT_DIR)/scripts/setup-lab.sh

test: ## Ask ARIA to verify telemetry actually reaches the collector
	@bash $(ROOT_DIR)/scripts/check-work.sh

submit: ## Submit your work for ARIA review (branch, commit, push, PR)
	@bash $(ROOT_DIR)/scripts/submit.sh

reset: ## Destroy and rebuild the fleet + collector
	@bash $(ROOT_DIR)/scripts/reset-lab.sh

destroy: ## Tear down everything (containers, keys, venv, range state)
	@bash $(ROOT_DIR)/scripts/destroy-lab.sh

ssh-web: ## SSH into sdc-web (fleet node)
	@ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i workspace/.ssh/cadet_key cadet@localhost -p 2221

ssh-db: ## SSH into sdc-db (fleet node)
	@ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i workspace/.ssh/cadet_key cadet@localhost -p 2222

ssh-comms: ## SSH into sdc-comms (fleet node)
	@ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i workspace/.ssh/cadet_key cadet@localhost -p 2223
