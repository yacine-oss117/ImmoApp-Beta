Set-StrictMode -Version Latest

function Get-HubManagerAuthorizationBaseUrl {
    param([string]$RequestedBaseUrl = "")

    $canonical = (Get-ImmoAppHubBaseUrl -PreferLan).TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($RequestedBaseUrl)) {
        return $canonical
    }
    $requested = $RequestedBaseUrl.Trim().TrimEnd("/")
    try {
        $canonicalUri = [Uri]$canonical
        $requestedUri = [Uri]$requested
    }
    catch {
        throw "hub_owner_authorization_base_url_invalid|Hub authorization URL is invalid."
    }
    if (
        $canonicalUri.Scheme -ne $requestedUri.Scheme -or
        $canonicalUri.Host -ne $requestedUri.Host -or
        $canonicalUri.Port -ne $requestedUri.Port
    ) {
        throw "hub_owner_authorization_base_url_mismatch|Hub authorization must use the saved Hub front door."
    }
    return $canonical
}

function Confirm-ImmoAppHubOwnerAuthorizationWithHub {
    param(
        [Parameter(Mandatory = $true)]$Evidence,
        [Parameter(Mandatory = $true)][string]$ExpectedAction,
        [Parameter(Mandatory = $true)][string]$ExpectedScope,
        [string]$HubBaseUrl = ""
    )

    $base = Get-HubManagerAuthorizationBaseUrl -RequestedBaseUrl $HubBaseUrl
    $endpoint = "$base/api/v1/hub-manager/authorizations/consume/"
    $requestPayload = [ordered]@{
        evidence_nonce = [string](Get-ImmoAppObjectValue -Data $Evidence -Name "evidence_nonce")
        action = $ExpectedAction
        hub_id = [string](Get-ImmoAppObjectValue -Data $Evidence -Name "hub_id")
    }
    if ([string]::IsNullOrWhiteSpace($requestPayload.evidence_nonce)) {
        throw "hub_owner_authorization_nonce_missing|Hub owner authorization evidence has no grant nonce."
    }
    if (
        (Get-ImmoAppRuntimeRootSource) -eq "test_programdata_root" -and
        $env:IMMOAPP_ALLOW_TEST_OWNER_AUTHORIZATION_CONFIRMATION -eq "1" -and
        [string](Get-ImmoAppObjectValue -Data $Evidence -Name "test_confirmation_status") -eq "GO"
    ) {
        return $Evidence
    }
    try {
        $response = Invoke-RestMethod `
            -Method Post `
            -Uri $endpoint `
            -ContentType "application/json" `
            -Body ($requestPayload | ConvertTo-Json -Compress) `
            -TimeoutSec 12
    }
    catch {
        throw "hub_owner_authorization_not_confirmed|The running Hub did not confirm owner/admin authorization."
    }
    if (
        [string](Get-ImmoAppObjectValue -Data $response -Name "proof_result") -ne "GO" -or
        [string](Get-ImmoAppObjectValue -Data $response -Name "owner_authorization_status") -ne "GO"
    ) {
        throw "hub_owner_authorization_not_confirmed|The running Hub rejected owner/admin authorization."
    }
    foreach ($field in @(
        "action",
        "authorization_scope",
        "authorized_role",
        "hub_id",
        "hub_identity_sha256",
        "hub_state_manifest_sha256",
        "hub_state_install_lineage"
    )) {
        if (
            [string](Get-ImmoAppObjectValue -Data $response -Name $field) -ne
            [string](Get-ImmoAppObjectValue -Data $Evidence -Name $field)
        ) {
            throw "hub_owner_authorization_confirmation_mismatch|Hub authorization confirmation did not match the evidence file."
        }
    }
    if ([string](Get-ImmoAppObjectValue -Data $response -Name "action") -ne $ExpectedAction) {
        throw "hub_owner_authorization_action_invalid|Hub authorization confirmation has the wrong action."
    }
    if ([string](Get-ImmoAppObjectValue -Data $response -Name "authorization_scope") -ne $ExpectedScope) {
        throw "hub_owner_authorization_scope_invalid|Hub authorization confirmation has the wrong scope."
    }
    return $response
}
