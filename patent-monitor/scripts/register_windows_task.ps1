# ============================================================================
# register_windows_task.ps1 —— 一键注册 Windows 定时任务
# ============================================================================
#
# 使用方式（在 PowerShell 中执行，需要管理员权限）：
#
#   .\register_windows_task.ps1                    # 每周一 08:00（默认）
#   .\register_windows_task.ps1 -Weekday 1 -Hour 8 -Minute 0
#   .\register_windows_task.ps1 -Weekly -Weekday 1
#   .\register_windows_task.ps1 -Daily -Hour 23    # 每天 23:00
#   .\register_windows_task.ps1 -RunNow            # 注册后立即运行一次
#
# 查看任务：Get-ScheduledTask -TaskName "多靶点专利监控"
# 手动运行：Start-ScheduledTask -TaskName "多靶点专利监控"
# 删除任务：Unregister-ScheduledTask -TaskName "多靶点专利监控" -Confirm:$false
#
# ============================================================================

param(
    [ValidateSet("Daily", "Weekly")]
    [string]$ScheduleType = "Weekly",

    # 周几：1=周一, 2=周二, ..., 7=周日
    [int]$Weekday = 1,

    [int]$Hour = 8,
    [int]$Minute = 0,

    [string]$TaskName = "多靶点专利监控",

    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

# ── 定位脚本所在目录 ──────────────────────────────────────────────
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonDir = Split-Path -Parent $scriptDir

# ── 找 Python 可执行文件 ──────────────────────────────────────────
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $result = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $candidate
            Write-Host "[OK] 找到 Python: $candidate ($result)" -ForegroundColor Green
            break
        }
    } catch {}
}
if (-not $pythonExe) {
    Write-Host "[ERROR] 未找到 Python，请先安装并添加到 PATH" -ForegroundColor Red
    exit 1
}

# ── 检查配置文件 ──────────────────────────────────────────────────
$configPath = Join-Path $scriptDir "config.yaml"
if (-not (Test-Path $configPath)) {
    $examplePath = Join-Path $scriptDir "config.example.yaml"
    Write-Host "[WARN] config.yaml 不存在，使用 config.example.yaml" -ForegroundColor Yellow
    Write-Host "       建议复制并修改: copy config.example.yaml config.yaml" -ForegroundColor Yellow
    # 不阻断，继续执行
}

# ── 构建触发条件 ──────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "注册 Windows 定时任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if ($ScheduleType -eq "Weekly") {
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek ([DayOfWeek]$Weekday) `
        -At ("{0:D2}:{1:D2}" -f $Hour, $Minute)
    $descWeekday = @("周日","周一","周二","周三","周四","周五","周日")[$Weekday % 7]
    Write-Host "触发: 每周$descWeekday $("{0:D2}:{1:D2}" -f $Hour, $Minute)"
} else {
    $trigger = New-ScheduledTaskTrigger `
        -Daily `
        -At ("{0:D2}:{1:D2}" -f $Hour, $Minute)
    Write-Host "触发: 每天 $("{0:D2}:{1:D2}" -f $Hour, $Minute)"
}

# ── 构建 Action ──────────────────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "run_monitor.py --config `"$configPath`"" `
    -WorkingDirectory $scriptDir

# ── 任务设置 ─────────────────────────────────────────────────────
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# ── 先卸载同名旧任务（如果存在）─────────────────────────────────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] 已存在同名任务，先卸载旧版本" -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── 注册 ──────────────────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "多靶点（TSHR/APJ/PCSK9/CYP51）创新药专利自动监控，Python 脚本路径: $scriptDir" `
    -RunLevel Highest

Write-Host ""
Write-Host "[OK] 定时任务 '$TaskName' 注册成功" -ForegroundColor Green
Write-Host "    Python:   $pythonExe"
Write-Host "    工作目录: $scriptDir"
Write-Host "    配置:     $configPath"
Write-Host ""
Write-Host "常用操作:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName '$TaskName'        查看状态"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'      立即运行"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName'  卸载"

# ── 立即运行 ──────────────────────────────────────────────────────
if ($RunNow) {
    Write-Host ""
    Write-Host "[INFO] 触发立即运行 ..." -ForegroundColor Yellow
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "[OK] 已触发，请在任务计划程序查看进度" -ForegroundColor Green
}
