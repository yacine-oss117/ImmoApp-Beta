from __future__ import annotations

from pathlib import Path

from repo_layout import COMPOSE_YML, OPS_POLICY_ROOT

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    file_path = REPO_ROOT / path
    if not file_path.exists():
        raise SystemExit(f"verify_release_rollout_contract: missing required file {path}")
    return file_path.read_text(encoding="utf-8")


def main() -> int:
    compose = _read(COMPOSE_YML)
    docs = _read(OPS_POLICY_ROOT / "SLO_AND_RELEASE_GUARDRAILS.md")
    _read("scripts/release_canary.ps1")
    _read("scripts/release_rollback.ps1")

    required_compose_tokens = (
        "web:\n    image: ${IMMOAPP_APP_IMAGE:-immoapp-server:local}",
        "worker:\n    image: ${IMMOAPP_APP_IMAGE:-immoapp-server:local}",
        "beat:\n    image: ${IMMOAPP_APP_IMAGE:-immoapp-server:local}",
    )
    for token in required_compose_tokens:
        if token not in compose:
            raise SystemExit(
                "verify_release_rollout_contract: compose image contract missing token:\n"
                f"{token}"
            )

    required_doc_tokens = (
        "release_canary.ps1",
        "release_rollback.ps1",
    )
    for token in required_doc_tokens:
        if token not in docs:
            raise SystemExit(
                "verify_release_rollout_contract: rollout runbook is missing command reference "
                f"for {token}"
            )

    print("verify_release_rollout_contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
