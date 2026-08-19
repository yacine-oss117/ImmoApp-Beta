ENV_FILE ?= C:/ProgramData/ImmoApp/config/.env.local
EXTRA_COMPOSE_FILES ?=
PSHELL ?= powershell
DEPLOYMENT_ROOT ?= deployment
COMPOSE_ROOT ?= $(DEPLOYMENT_ROOT)/compose
.DEFAULT_GOAL := help

POWERSHELL_BYPASS = $(PSHELL) -NoProfile -ExecutionPolicy Bypass -File
CHECKS_ENTRY = $(POWERSHELL_BYPASS) checks.ps1
RUN_SERVER_ENTRY = $(POWERSHELL_BYPASS) scripts/run_server.ps1
RUN_CLIENT_ENTRY = $(POWERSHELL_BYPASS) scripts/run_client.ps1
PROVISION_SIGNOZ_ALERTS_ENTRY = $(POWERSHELL_BYPASS) scripts/provision_signoz_alerts.ps1
SETUP_TLA_ENTRY = $(POWERSHELL_BYPASS) scripts/setup_tla.ps1
OTEL_DOCKER_ENV = OTEL_EXPORTER_OTLP_ENDPOINT_DOCKER=http://otel-collector:4318 OTEL_EXPORTER_OTLP_PROTOCOL_DOCKER=http/protobuf

DC_BASE = docker compose --project-directory . --env-file $(ENV_FILE) -f $(COMPOSE_ROOT)/compose.yml $(EXTRA_COMPOSE_FILES)
DC_APP = $(DC_BASE) -f $(COMPOSE_ROOT)/compose.app.yml
DC_FULL = $(DC_APP) -f $(COMPOSE_ROOT)/compose.observability.yml
DC_OBS = $(DC_BASE) -f $(COMPOSE_ROOT)/compose.observability.yml

.PHONY: help up up-infra build-app db-prepare up-app up-full down ps logs logs-infra logs-full restart-app signoz-up signoz-down signoz-health signoz-provision-alerts signoz-provision-alerts-dryrun tla-setup tla-ready check check-fast check-pr check-full check-nightly run-server run-client run-server-error run-client-error

help:
	@echo "ImmoApp Docker targets"
	@echo ""
	@echo "Core:"
	@echo "  make up               # infra + app build + db prepare + app start"
	@echo "  make up-infra         # db/rabbitmq/valkey/minio/clamav/caddy only"
	@echo "  make up-app           # web/worker/beat only"
	@echo "  make db-prepare       # run schema/security prepare command"
	@echo "  make down             # stop all stacks (core/app/obs)"
	@echo "  make ps               # show running containers"
	@echo "  make logs             # follow app logs (web/worker/beat)"
	@echo "  make logs-infra       # follow infra logs"
	@echo ""
	@echo "Optional:"
	@echo "  make up-full          # core + app + observability"
	@echo "  make logs-full        # logs for full stack"
	@echo "  make restart-app      # restart web/worker/beat"
	@echo "  make signoz-up        # observability stack only (SigNoz + OTEL)"
	@echo "  make signoz-down      # stop observability stack only"
	@echo "  make signoz-health    # verify SigNoz/OTEL endpoints are reachable"
	@echo "  make signoz-provision-alerts        # upsert SigNoz channels/rules from config"
	@echo "  make signoz-provision-alerts-dryrun # print SigNoz alert actions without mutating"
	@echo "  make tla-setup        # install/fetch TLC prerequisites (Java + tools/tla/tla2tools.jar)"
	@echo "  make tla-ready        # verify TLC prerequisites without running waves"
	@echo "  make check            # run PR lane checks (default)"
	@echo "  make check-fast       # lint/format only"
	@echo "  make check-pr         # lint + types + unit tests"
	@echo "  make check-full       # PR lane + integration + security"
	@echo "  make check-nightly    # full lane + heavy nightly suites"
	@echo "  make run-server       # run local Django server (blocking)"
	@echo "  make run-client       # run local desktop client (blocking)"
	@echo "  make run-server-error # run local Django server with ERROR-only logs"
	@echo "  make run-client-error # run local client with ERROR-only logs"
	@echo ""
	@echo "Examples:"
	@echo "  make up"
	@echo "  make up EXTRA_COMPOSE_FILES='-f deployment/compose/compose.windows.yml'"
	@echo "  make up-full EXTRA_COMPOSE_FILES='-f deployment/compose/compose.windows.yml'"

up-infra:
	$(DC_BASE) up -d db rabbitmq valkey minio minio-init clamav openbao

build-app:
	$(DC_APP) build web

db-prepare:
	$(DC_APP) run --rm web python server/manage.py immoapp_db_prepare

up-app:
	$(DC_APP) up -d openbao openbao-init openbao-seed
	$(DC_APP) up -d --force-recreate web worker beat caddy

up: up-infra build-app db-prepare up-app

up-full:
	$(OTEL_DOCKER_ENV) $(DC_FULL) up -d db rabbitmq valkey minio minio-init clamav openbao zookeeper-1 clickhouse schema-migrator-sync signoz otel-collector
	$(OTEL_DOCKER_ENV) $(DC_FULL) build web
	$(OTEL_DOCKER_ENV) $(DC_FULL) up -d openbao-init openbao-seed
	$(OTEL_DOCKER_ENV) $(DC_FULL) run --rm web python server/manage.py immoapp_db_prepare
	$(OTEL_DOCKER_ENV) $(DC_FULL) up -d --force-recreate web worker beat caddy

down:
	$(DC_FULL) down --remove-orphans

ps:
	$(DC_FULL) ps

logs:
	$(DC_APP) logs -f --tail=200 web worker beat

logs-infra:
	$(DC_BASE) logs -f --tail=200 db rabbitmq valkey minio clamav openbao openbao-init openbao-seed

logs-full:
	$(DC_FULL) logs -f --tail=200

restart-app:
	$(DC_APP) up -d openbao openbao-init openbao-seed
	$(DC_APP) up -d --force-recreate web worker beat caddy

signoz-up:
	$(DC_OBS) up -d

signoz-down:
	$(DC_OBS) down --remove-orphans

signoz-health:
	python scripts/verify_observability_stack.py

signoz-provision-alerts:
	$(PROVISION_SIGNOZ_ALERTS_ENTRY) -EnvFile $(ENV_FILE)

signoz-provision-alerts-dryrun:
	$(PROVISION_SIGNOZ_ALERTS_ENTRY) -EnvFile $(ENV_FILE) -DryRun

tla-setup:
	$(SETUP_TLA_ENTRY) -InstallJava

tla-ready:
	python scripts/verify_tlc_ready.py

check:
	$(CHECKS_ENTRY) -Stage pr

check-fast:
	$(CHECKS_ENTRY) -Stage fast

check-pr:
	$(CHECKS_ENTRY) -Stage pr

check-full:
	$(CHECKS_ENTRY) -Stage full

check-nightly:
	$(CHECKS_ENTRY) -Stage nightly

run-server:
	$(RUN_SERVER_ENTRY)

run-client:
	$(RUN_CLIENT_ENTRY)

run-server-error:
	$(RUN_SERVER_ENTRY) -ErrorOnly

run-client-error:
	$(RUN_CLIENT_ENTRY) -ErrorOnly
