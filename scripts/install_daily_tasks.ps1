param(
    [Parameter(Mandatory=$true)][string]$Portfolio,
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$MorningTime = "08:30",
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

function Install-DailyTask([string]$Name, [string]$Time) {
    $arguments = '"{0}" monitor --portfolio "{1}" --config "{2}" --amount {3}' -f $Runner, $Portfolio, $Config, $Amount
    $action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Description "MOEX Bond Lab portfolio monitor for $Portfolio" -Force | Out-Null
    Write-Host "OK: $Name -> monitor at $Time"
}

$SafePortfolio = ($Portfolio -replace '[^a-zA-Zа-яА-Я0-9_.-]+', '_')

# Remove the old daily FULL task if it exists. Full market scanning is now a manual/monthly action.
$OldFullTask = "MOEX Bond Lab - $SafePortfolio - Full"
if (Get-ScheduledTask -TaskName $OldFullTask -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $OldFullTask -Confirm:$false
    Write-Host "Removed old daily full-scan task: $OldFullTask"
}

Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Morning" $MorningTime
Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Midday" $MiddayTime
Install-DailyTask "MOEX Bond Lab - $SafePortfolio - Evening" $EveningTime

Write-Host ""
Write-Host "Установлены три ежедневные задачи мониторинга портфеля '$Portfolio'."
Write-Host "Полный поиск по рынку больше НЕ запускается ежедневно. Его запускайте вручную примерно раз в месяц."
Write-Host "Каждый monitor-run обновляет рынок, новости, рейтинговые события и спреды к ОФЗ только для бумаг портфеля."
