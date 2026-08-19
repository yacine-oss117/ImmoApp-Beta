from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
DOCS_ARCHITECTURE_ROOT = DOCS_ROOT / "architecture"
DOCS_GUIDES_ROOT = DOCS_ROOT / "guides"
DOCS_PRODUCT_ROOT = DOCS_ROOT / "product"
DOCS_REFERENCE_ROOT = DOCS_ROOT / "reference"
DEPLOYMENT_ROOT = REPO_ROOT / "deployment"
COMPOSE_ROOT = DEPLOYMENT_ROOT / "compose"
DOCKER_ROOT = DEPLOYMENT_ROOT / "docker"
PROXY_ROOT = DEPLOYMENT_ROOT / "proxy"
ENV_TEMPLATE_ROOT = DEPLOYMENT_ROOT / "env"
ALEMBIC_ROOT = REPO_ROOT / "server" / "alembic"
ALEMBIC_CONFIG = REPO_ROOT / "server" / "alembic.ini"
OPS_ROOT = REPO_ROOT / "ops"
OPS_RUNBOOK_ROOT = OPS_ROOT / "runbooks"
OPS_POLICY_ROOT = OPS_ROOT / "policies"
TOOLS_ROOT = REPO_ROOT / "tools"
TOOLS_REFERENCE_ROOT = TOOLS_ROOT / "reference"
TOOLS_SECURITY_ROOT = TOOLS_ROOT / "security"
TLA_ROOT = TOOLS_ROOT / "tla"
TLA_SPEC_ROOT = TLA_ROOT / "specs"

COMPOSE_YML = COMPOSE_ROOT / "compose.yml"
COMPOSE_APP_YML = COMPOSE_ROOT / "compose.app.yml"
COMPOSE_WINDOWS_YML = COMPOSE_ROOT / "compose.windows.yml"
COMPOSE_PROD_YML = COMPOSE_ROOT / "compose.prod.yml"
COMPOSE_OBSERVABILITY_YML = COMPOSE_ROOT / "compose.observability.yml"
COMPOSE_PERF_YML = COMPOSE_ROOT / "compose.perf.yml"

DOCKERFILE = DOCKER_ROOT / "Dockerfile"
RUN_WEB_SH = DOCKER_ROOT / "run_web.sh"
SIGNOZ_ALERTS_CONFIG = DOCKER_ROOT / "signoz" / "provisioning" / "alerts.json"

ENV_EXAMPLE = ENV_TEMPLATE_ROOT / ".env.example"
ENV_PROD_EXAMPLE = ENV_TEMPLATE_ROOT / ".env.prod.example"
PIP_AUDIT_IGNORE = TOOLS_SECURITY_ROOT / "pip_audit_ignore.json"
IMAGE_SIGNATURES_MANIFEST = TOOLS_SECURITY_ROOT / "image_signatures.json"
SBOM_ROOT = TOOLS_SECURITY_ROOT / "sbom"
TLA_JAR = TLA_ROOT / "tla2tools.jar"

RESTORE_DRILL_RUNBOOK = OPS_RUNBOOK_ROOT / "RESTORE_DRILL_RUNBOOK.md"


def compose_file(name: str) -> Path:
    return COMPOSE_ROOT / name


def docker_file(*parts: str) -> Path:
    return DOCKER_ROOT.joinpath(*parts)


def proxy_file(name: str) -> Path:
    return PROXY_ROOT / name


def env_template_file(name: str) -> Path:
    return ENV_TEMPLATE_ROOT / name


def alembic_file(*parts: str) -> Path:
    return ALEMBIC_ROOT.joinpath(*parts)
