[CmdletBinding()]
param(
    [string]$ResourceGroup = 'agentic-connected-vehicle',
    [string]$TemplateFile = 'deploy.bicep',
    [string]$ParamsFile = 'params.prod.json',
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error 'Azure CLI (az) not found. Install it and try again.'
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$templatePath = Join-Path $scriptRoot $TemplateFile
$paramsPath = Join-Path $scriptRoot $ParamsFile

if (-not (Test-Path -Path $templatePath -PathType Leaf)) {
    Write-Error "Template file not found: $templatePath"
    exit 1
}

if (-not (Test-Path -Path $paramsPath -PathType Leaf)) {
    Write-Error "Parameters file not found: $paramsPath"
    exit 1
}

# Ensure the caller is logged in
$currentAccountJson = az account show --output json 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($currentAccountJson)) {
    Write-Error 'Not logged in. Run "az login" first.'
    exit 1
}

$currentAccount = $currentAccountJson | ConvertFrom-Json
Write-Output "Using tenant $($currentAccount.tenantId), subscription $($currentAccount.id) ($($currentAccount.name))"

$deploymentVerb = if ($ValidateOnly) { 'validate' } else { 'create' }

Write-Output "Running az deployment group $deploymentVerb against resource group $ResourceGroup..."

az deployment group $deploymentVerb `
    --resource-group $ResourceGroup `
    --template-file $templatePath `
    --parameters @$paramsPath

if ($LASTEXITCODE -ne 0) {
    Write-Error "Deployment $deploymentVerb failed."
    exit $LASTEXITCODE
}

Write-Output "Deployment $deploymentVerb completed successfully."
