SHELL := /usr/bin/env bash

.PHONY: help install-deps install start stop restart status health doctor set-vnc-password validate

help:
	@echo "Hermes Shared Browser targets"
	@echo ""
	@echo "  make install-deps       Install Debian/Ubuntu package dependencies"
	@echo "  make install            Install systemd user units and generate config"
	@echo "  make start              Enable and start all services"
	@echo "  make stop               Stop all services"
	@echo "  make restart            Restart all services"
	@echo "  make status             Show systemd service status"
	@echo "  make health             Run health/security checks"
	@echo "  make doctor             Alias for health"
	@echo "  make set-vnc-password   Prompt for a VNC password and store it locally"
	@echo "  make validate           Validate scripts and systemd unit syntax"

install-deps:
	./scripts/install-debian-packages.sh

install:
	./scripts/install-systemd-user.sh

start:
	systemctl --user enable --now hermes-browser-xvfb.service
	systemctl --user enable --now hermes-browser-chromium.service
	systemctl --user enable --now hermes-browser-vnc.service
	systemctl --user enable --now hermes-browser-novnc.service

stop:
	-systemctl --user stop hermes-browser-novnc.service hermes-browser-vnc.service hermes-browser-chromium.service hermes-browser-xvfb.service

restart:
	systemctl --user restart hermes-browser-xvfb.service
	systemctl --user restart hermes-browser-chromium.service
	systemctl --user restart hermes-browser-vnc.service
	systemctl --user restart hermes-browser-novnc.service

status:
	systemctl --user --no-pager --lines=30 status hermes-browser-xvfb.service hermes-browser-chromium.service hermes-browser-vnc.service hermes-browser-novnc.service

health doctor:
	./scripts/check-health.sh

set-vnc-password:
	./scripts/set-vnc-password.sh

validate:
	bash -n scripts/*.sh
	systemd-analyze --user verify systemd/user/*.service
	git diff --check
