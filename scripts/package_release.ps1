[CmdletBinding()]
param(
    [string]$Version = "dev",
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"

$skillName = "codex-ghost-chat-cleanup"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputRoot = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    [System.IO.Path]::GetFullPath($OutputDirectory)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
}
$safeVersion = $Version -replace "[^0-9A-Za-z._-]", "-"
$archiveName = "$skillName-$safeVersion.zip"
$archivePath = Join-Path $outputRoot $archiveName
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("$skillName-package-" + [guid]::NewGuid().ToString("N"))
$packageRoot = Join-Path $temporaryRoot $skillName

$runtimeFiles = @(
    "SKILL.md",
    "agents\openai.yaml",
    "scripts\catalog_cleanup.py",
    "install.ps1",
    "README.md",
    "LICENSE",
    "VERSION"
)

try {
    New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

    foreach ($relativePath in $runtimeFiles) {
        $source = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Required release file is missing: $source"
        }

        $destination = Join-Path $packageRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination
    }

    New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $archivePath -CompressionLevel Optimal -Force

    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $checksumPath = Join-Path $outputRoot "SHA256SUMS.txt"
    Set-Content -LiteralPath $checksumPath -Value "$hash  $archiveName" -Encoding utf8NoBOM

    Write-Host "Created release archive: $archivePath"
    Write-Host "Created checksum file: $checksumPath"
}
finally {
    $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
    $systemTemporaryRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if (
        (Test-Path -LiteralPath $resolvedTemporaryRoot) -and
        $resolvedTemporaryRoot.StartsWith($systemTemporaryRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path $resolvedTemporaryRoot -Leaf).StartsWith("$skillName-package-")
    ) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
