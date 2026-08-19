from __future__ import annotations

from pathlib import Path


def test_stack_compose_hydration_supports_approle_and_path_normalization() -> None:
    text = Path("scripts/stack.ps1").read_text(encoding="utf-8")
    required_tokens = (
        "function Resolve-OpenBaoReadPath",
        "function Resolve-OpenBaoAppRoleToken",
        "function Sync-LocalSecrets",
        'Get-EnvValueFromFile -Path $EnvFilePath -Name "BAO_APPROLE_FILE"',
        'Invoke-RestMethod -Method Post -Uri "$Addr/v1/auth/approle/login"',
        '$readUri = "$addr/v1/$readPath"',
        "Set-ComposeEnvFromBootstrapFile -EnvFilePath $EnvFile",
        'if ($Action -in @("build-app", "db-prepare", "up-app", "up", "up-full", "up-prod", "preflight-prod", "restart-app", "sync-secrets", "provision-alerts")) {',
        'Invoke-Compose ($base + @("up", "-d", "--force-recreate", "openbao-init"))',
        'Invoke-Compose ($base + @("up", "-d", "--force-recreate", "openbao-seed"))',
        '"sync-secrets"',
    )
    for token in required_tokens:
        assert token in text

def test_bootstrap_env_assertion_array_wraps_zero_or_one_issue_results() -> None:
    text = Path("scripts/common.ps1").read_text(encoding="utf-8")
    assert "$issues = @(Get-ImmoAppEnvPlaceholderIssues -EnvFilePath $EnvFilePath)" in text

