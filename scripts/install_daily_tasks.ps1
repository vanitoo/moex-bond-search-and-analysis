param(
    [Parameter(Mandatory=$true)][string]$Portfolio,
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$FullTime = "08:30",
    [string]$MiddayTime = "13:00",
    [string]$EveningTime = "18:30",
    [double]$Amount = 50000
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Runner = Join-Path $ProjectRoot "daily_runner.py"
$Config = Join-Path $ProjectRoot "configs\gui_active.json"

if (-not (Test-Path $Python)) { throw "Python venv не найден: $Python" }
if (-not (Test-Path $Runner)) { throw "daily_runner.py не найден: $Runner" }

function Install-DailyTask([string]$Name, [string]$Mode, [string]$Time) {
    $arguments = '"{0}" {1} --portfolio "{2}" --config "{3}" --amount {4}' -f $Runner, $Mode, $Portfolio, $Config, $Amount
    $action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Description "MOEX Bond Lab autopilot: $Mode for $Portfolio" -Force | Out-Null
    Write-Host "OK: $Name -> $Mode at $Time"
}

$SafePortfolio = ($Portfolio -replace '[^a-zA-Zа-яА-Я0-9_.-]+', '_')
Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Full" "full" $FullTime
Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Midday" "monitor" $MiddayTime
Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Evening" "monitor" $EveningTime

Write-Host ""
Write-Host "Установлены три ежедневные задачи для портфеля '$Portfolio'."
Write-Host "Изменить расписание можно повторным запуском этого скрипта с другими -FullTime/-MiddayTime/-EveningTime."
