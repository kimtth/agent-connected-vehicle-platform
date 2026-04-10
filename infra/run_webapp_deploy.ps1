[CmdletBinding()]
param(
    [string]$ResourceGroup = 'agentic-connected-vehicle',
    [string]$WebAppName = 'acvp-app-vb2dol',
    [string]$SourceDir = '..\vehicle',
    [string]$OutputZip = 'deploy.zip',
    [switch]$Async = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Error 'Azure CLI (az) not found. Install it and try again.'
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error 'uv not found. Install it and try again.'
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$sourcePath = Resolve-Path (Join-Path $scriptRoot $SourceDir)
$zipPath = Join-Path $sourcePath $OutputZip
$packageItems = @(
    'main.py',
    'pyproject.toml',
    'uv.lock',
    'requirements.txt',
    'agents',
    'apis',
    'models',
    'plugin',
    'public',
    'utils',
    'vehicle_azure'
)

Write-Output "Using source directory: $sourcePath"

Push-Location $sourcePath
try {
    Write-Output 'Refreshing lockfile and requirements.txt from pyproject.toml...'
    uv lock
    uv export --format requirements-txt --no-hashes -o requirements.txt

    if (Test-Path -Path $zipPath -PathType Leaf) {
        Remove-Item -Path $zipPath -Force
    }

    Write-Output "Creating deployment package: $zipPath"
    Compress-Archive -Path $packageItems -DestinationPath $zipPath -Force

    $startupCommand = 'gunicorn --bind=0.0.0.0 --timeout 600 -k uvicorn.workers.UvicornWorker main:app'
    Write-Output 'Ensuring web app startup command is set...'
    az webapp config set --name $WebAppName --resource-group $ResourceGroup --startup-file $startupCommand --output none

    Write-Output 'Deploying package to Azure App Service...'
    if ($Async) {
        az webapp deploy --resource-group $ResourceGroup --name $WebAppName --src-path $zipPath --type zip --async true
    }
    else {
        az webapp deploy --resource-group $ResourceGroup --name $WebAppName --src-path $zipPath --type zip
    }
}
finally {
    Pop-Location
}