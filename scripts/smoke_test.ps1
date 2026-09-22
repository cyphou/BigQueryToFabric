[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Inventory = "tests/fixtures/gcp_ecosystem_project.json",

    [Parameter(Position = 1)]
    [string]$Output = "artifacts/assessment-smoke"
)

$ErrorActionPreference = "Stop"

function Invoke-BqToFabric {
    param([string[]]$Arguments)

    & bqtofabric @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "bqtofabric $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $Inventory -PathType Leaf)) {
    throw "Inventory file was not found: $Inventory"
}

$planOutput = Join-Path $Output "plan"
$projectOutput = Join-Path $Output "project"

Invoke-BqToFabric @("validate", $Inventory)
Invoke-BqToFabric @("inventory", $Inventory)
Invoke-BqToFabric @("assess", $Inventory)
Invoke-BqToFabric @("map", $Inventory)
Invoke-BqToFabric @("plan", $Inventory, "--output", $planOutput)
Invoke-BqToFabric @("generate", $Inventory, "--output", $projectOutput)
Invoke-BqToFabric @("manifest-verify", (Join-Path $projectOutput "fabric/deployment-manifest.json"))
Invoke-BqToFabric @("deployment-check", (Join-Path $projectOutput "fabric"))

Write-Host "Smoke test completed: $projectOutput"
