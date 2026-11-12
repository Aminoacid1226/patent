# ============================================================================
# run.ps1 —— patent-monitor Skill 统一入口（自包含版本）
# ============================================================================
# 用法：
#
#   .trae\skills\patent-monitor\scripts\run.ps1              # 完整运行
#   .trae\skills\patent-monitor\scripts\run.ps1 -Diagnose    # 仅健康检查
#   .trae\skills\patent-monitor\scripts\run.ps1 -NoDownload  # 不下载 PDF
#   .trae\skills\patent-monitor\scripts\run.ps1 -Date 2026-11-10
#   .trae\skills\patent-monitor\scripts\run.ps1 -FullRebuild
#
# 首次使用前（重要！）：
#   Copy-Item .trae\skills\patent-monitor\scripts\config.example.yaml 
#             .trae\skills\patent-monitor\scripts\config.yaml
#   然后编辑 config.yaml → output.root 改成你想存放输出的目录
# ============================================================================

param(
    [switch]$Diagnose,
    [switch]$NoDownload,
    [switch]$FullRebuild,
    [string]$Date = "",
    [string]$Mode = "",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

# 定位 scripts 目录（所有 Python 文件都在这里）
$scriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "=== Patent Monitor Skill ===" -ForegroundColor Cyan
Write-Host "  Scripts: $scriptsDir"
Write-Host ""

# 检查 config.yaml（没有则提示复制）
$configPath = Join-Path $scriptsDir "config.yaml"
if (-not (Test-Path $configPath)) {
    $examplePath = Join-Path $scriptsDir "config.example.yaml"
    if (Test-Path $examplePath) {
        Write-Host "[SETUP] 未检测到 config.yaml，自动从 config.example.yaml 复制" -ForegroundColor Yellow
        Copy-Item $examplePath $configPath
        Write-Host "[SETUP] 已创建 config.yaml" -ForegroundColor Green
        Write-Host "[SETUP] ★ 建议编辑 output.root 改成你想存放输出的目录" -ForegroundColor Yellow
        Write-Host ""
    }
}

# 找 Python
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        & $candidate --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $pythonExe = $candidate
            break
        }
    } catch {}
}
if (-not $pythonExe) {
    Write-Host "[ERROR] 未找到 Python，请先安装 Python 3.9+" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $pythonExe" -ForegroundColor Green
Write-Host ""

Set-Location $scriptsDir

# 健康检查
if ($Diagnose) {
    Write-Host "[INFO] 运行健康检查 ..." -ForegroundColor Yellow
    & $pythonExe diagnose.py --config "$configPath"
    exit $LASTEXITCODE
}

# 主流程
$argsList = @("run_monitor.py", "--config", "$configPath")
if ($NoDownload)   { $argsList += "--no-download" }
if ($FullRebuild)  { $argsList += "--full-rebuild" }
if ($Date)         { $argsList += "--date"; $argsList += $Date }
if ($Mode)         { $argsList += "--mode"; $argsList += $Mode }
if ($Target)       { $argsList += "--target"; $argsList += $Target }

Write-Host "[INFO] 执行: $pythonExe $($argsList -join ' ')" -ForegroundColor Yellow
Write-Host ""

& $pythonExe @argsList
$exitCode = $LASTEXITCODE

Write-Host ""
switch ($exitCode) {
    0 { Write-Host "[OK] 专利监控完成 ✓" -ForegroundColor Green }
    1 { Write-Host "[WARN] 部分成功（某些检索源失败）" -ForegroundColor Yellow }
    2 { Write-Host "[ERROR] 执行失败" -ForegroundColor Red }
}

exit $exitCode
