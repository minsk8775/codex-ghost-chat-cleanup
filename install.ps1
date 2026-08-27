[CmdletBinding()]
param(
    [string]$DestinationRoot = (Join-Path $env:USERPROFILE ".codex\skills"),
    [switch]$Replace
)

$ErrorActionPreference = "Stop"

$skillName = "codex-ghost-chat-cleanup"
$source = [System.IO.Path]::GetFullPath($PSScriptRoot)
$destinationRootFull = [System.IO.Path]::GetFullPath($DestinationRoot)
$target = Join-Path $destinationRootFull $skillName

$requiredFiles = @(
    (Join-Path $source "SKILL.md"),
    (Join-Path $source "agents\openai.yaml"),
    (Join-Path $source "scripts\catalog_cleanup.py")
)

foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required package file is missing: $requiredFile"
    }
}

if ($source.TrimEnd('\') -eq $target.TrimEnd('\')) {
    Write-Host "The repository is already located at the default skill path: $target"
    Write-Host "Restart Codex to load the skill."
    return
}

New-Item -ItemType Directory -Path $destinationRootFull -Force | Out-Null

$backup = $null
if (Test-Path -LiteralPath $target) {
    if (-not $Replace) {
        throw "The skill is already installed at '$target'. Run again with -Replace to back it up and install this copy."
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $backup = "$target.backup-$timestamp"
    Move-Item -LiteralPath $target -Destination $backup
}

New-Item -ItemType Directory -Path $target | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "agents") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "scripts") | Out-Null

Copy-Item -LiteralPath (Join-Path $source "SKILL.md") -Destination (Join-Path $target "SKILL.md")
Copy-Item -LiteralPath (Join-Path $source "agents\openai.yaml") -Destination (Join-Path $target "agents\openai.yaml")
Copy-Item -LiteralPath (Join-Path $source "scripts\catalog_cleanup.py") -Destination (Join-Path $target "scripts\catalog_cleanup.py")

foreach ($installedFile in @(
    (Join-Path $target "SKILL.md"),
    (Join-Path $target "agents\openai.yaml"),
    (Join-Path $target "scripts\catalog_cleanup.py")
)) {
    if (-not (Test-Path -LiteralPath $installedFile -PathType Leaf)) {
        throw "Installation verification failed; missing: $installedFile"
    }
}

Write-Host "Installed '$skillName' to: $target"
if ($backup) {
    Write-Host "Previous installation backup: $backup"
}
Write-Host "Restart Codex to load the skill."
