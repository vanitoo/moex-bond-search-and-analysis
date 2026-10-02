param(
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$RunsRoot = Join-Path $ProjectRoot "runs"
New-Item -ItemType Directory -Force -Path $RunsRoot | Out-Null

$pattern = '^bond_\d{4}_\d{2}_\d{2}$'
$dirs = Get-ChildItem -LiteralPath $ProjectRoot -Directory |
    Where-Object { $_.Name -match $pattern }

if (-not $dirs) {
    Write-Host "В корне нет старых папок bond_YYYY_MM_DD. Миграция не требуется."
    exit 0
}

foreach ($dir in $dirs) {
    $target = Join-Path $RunsRoot $dir.Name
    if (Test-Path -LiteralPath $target) {
        Write-Warning "Пропуск $($dir.Name): $target уже существует."
        continue
    }

    if ($WhatIf) {
        Write-Host "[WhatIf] $($dir.FullName) -> $target"
        continue
    }

    Move-Item -LiteralPath $dir.FullName -Destination $target
    Write-Host "Перенесено: $($dir.Name) -> runs\$($dir.Name)"
}

Write-Host ""
Write-Host "Готово. Новые анализы тоже будут автоматически создаваться в runs\."
