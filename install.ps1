#Requires -Version 7.0  # ConvertFrom-Json -AsHashtable 等是 PS7 语法；5.1 会得到清晰报错，而不是写出带 BOM 的 settings.json
# ============================================================
# install.ps1 —— DataAnalysis 数据分析智能体 安装 / 卸载（幂等）
#
# 安装：pwsh -File install.ps1
# 卸载：pwsh -File install.ps1 -Uninstall
#
# 设计要点：
# - skills 用 junction 装到 ~/.claude/skills/（指针不复制：脚本 parents[3]
#   解析跟随链接回到仓库根，config/memory/runs 照常可用；改仓库代码即时生效，
#   无需重装）
# - hooks 合并进 ~/.claude/settings.json：先备份、JSON 合并不覆盖，
#   保留用户已有配置（框架「保留已有配置与知识」要求）
# - 幂等：跑两遍零变化；卸载只删自己建的东西（junction 与 hooks 键），
#   connection.ini 与 runs/ 数据保留
# - 前置检查：hooks 由仓库 .venv 的 Python 承载（安装脚本不创建 venv），
#   venv 缺失时跳过 hooks 注册并提示，补上后重跑安装即可补齐
# ============================================================

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillsTarget = Join-Path $env:USERPROFILE ".claude\skills"
$SettingsPath = Join-Path $env:USERPROFILE ".claude\settings.json"
$SettingsBak = Join-Path $env:USERPROFILE ".claude\settings.json.bak-datagent"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"


function Test-Junction([string]$Path) {
    if (-not (Test-Path $Path)) { return $false }
    return ((Get-Item $Path -Force).LinkType -eq "Junction")
}


function Get-HookEntries {
    # 本插件注册的两个事件钩子（command 用绝对路径：用户级 settings 无项目占位符）
    return @(
        @{ event = "SessionEnd"; command = $VenvPython
           args = @((Join-Path $RepoRoot "hooks\session_evolution.py"), "--enqueue") },
        @{ event = "SessionStart"; command = $VenvPython
           args = @((Join-Path $RepoRoot "hooks\session_evolution.py"), "--process") }
    )
}


function Read-SettingsJson {
    if (-not (Test-Path $SettingsPath)) { return @{} }
    try {
        $raw = Get-Content $SettingsPath -Raw -Encoding UTF8
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        return $raw | ConvertFrom-Json -AsHashtable
    } catch {
        Write-Host "警告：settings.json 解析失败，备份后新建一份。" -ForegroundColor Yellow
        return $null
    }
}


function Write-SettingsJson($settings) {
    $json = $settings | ConvertTo-Json -Depth 12
    Set-Content $SettingsPath -Value $json -Encoding UTF8
}


function Install-DataAgent {
    Write-Host "=== 安装 DataAnalysis 智能体 ==="
    Write-Host "仓库根：$RepoRoot"
    New-Item -ItemType Directory -Force $SkillsTarget | Out-Null

    # ---- 0. 前置检查：hooks 由仓库 .venv 的 Python 承载（安装脚本不负责创建） ----
    $VenvOk = Test-Path $VenvPython
    if (-not $VenvOk) {
        Write-Host "  [警告] 未找到 $VenvPython" -ForegroundColor Yellow
        Write-Host "         hooks 需要仓库虚拟环境：请先按 README「快速开始」创建 venv 并安装依赖。"
        Write-Host "         本次跳过 hooks 注册；venv 就绪后重跑安装即可补齐（幂等）。"
    }

    # ---- 1. skills junction ----
    foreach ($name in @("analysis", "database-query")) {
        $link = Join-Path $SkillsTarget $name
        $target = Join-Path $RepoRoot "skills\$name"
        if (Test-Junction $link) {
            Write-Host "  [跳过] junction 已存在：$name"
        } elseif (Test-Path $link) {
            Write-Host "  [警告] $link 已存在且不是链接（真实目录），不动它。" -ForegroundColor Yellow
        } else {
            New-Item -ItemType Junction -Path $link -Target $target | Out-Null
            Write-Host "  [安装] junction：$name -> $target"
        }
    }

    # ---- 2. hooks 合并进用户级 settings.json（需 venv 就绪） ----
    if ($VenvOk) {
        $settings = Read-SettingsJson
        if ($null -eq $settings) {
            # 原文件损坏：备份后重建
            Copy-Item $SettingsPath $SettingsBak -Force
            $settings = @{}
        }
        $hooks = @{}
        if ($settings.ContainsKey("hooks") -and $null -ne $settings["hooks"]) {
            $hooks = $settings["hooks"]
        }
        $changed = $false
        foreach ($entry in Get-HookEntries) {
            $ev = $entry.event
            $evHooks = @()
            if ($hooks.ContainsKey($ev)) { $evHooks = @($hooks[$ev]) }
            $exists = $false
            foreach ($grp in $evHooks) {
                foreach ($h in @($grp.hooks)) {
                    if ($h.command -eq $entry.command -and $h.args[0] -eq $entry.args[0]) {
                        $exists = $true
                    }
                }
            }
            if (-not $exists) {
                if (-not (Test-Path $SettingsBak)) {
                    Copy-Item $SettingsPath $SettingsBak -Force -ErrorAction SilentlyContinue
                }
                $newGroup = @{ hooks = @(@{ type = "command"; command = $entry.command
                                            args = $entry.args; timeout = 30 }) }
                $evHooks += $newGroup
                $hooks[$ev] = $evHooks
                $changed = $true
            }
        }
        if ($changed) {
            $settings["hooks"] = $hooks
            Write-SettingsJson $settings
            Write-Host "  [安装] hooks 合并进 $SettingsPath"
            if (Test-Path $SettingsBak) { Write-Host "         （原配置已备份到 $SettingsBak）" }
        } else {
            Write-Host "  [跳过] hooks 已注册"
        }
    } else {
        Write-Host "  [跳过] hooks 注册：venv 缺失（见上方警告）"
    }

    # ---- 3. connection.ini 模板 ----
    $connIni = Join-Path $RepoRoot "config\connection.ini"
    if (Test-Path $connIni) {
        Write-Host "  [跳过] config/connection.ini 已存在"
    } else {
        Copy-Item (Join-Path $RepoRoot "config\connection.ini.example") $connIni
        Write-Host "  [安装] 已复制 connection.ini.example -> connection.ini（请填入 data_agent 密码）"
    }

    Write-Host ""
    Write-Host "安装完成。新开 Claude Code 会话即可使用 analysis / database-query 技能。"
}


function Uninstall-DataAgent {
    Write-Host "=== 卸载 DataAnalysis 智能体 ==="

    # ---- 1. 删 junction（只删 ~/.claude/skills 下的链接，不碰真实目录） ----
    foreach ($name in @("analysis", "database-query")) {
        $link = Join-Path $SkillsTarget $name
        if (Test-Junction $link) {
            Remove-Item $link -Force
            Write-Host "  [卸载] 移除 junction：$name"
        } else {
            Write-Host "  [跳过] 无 junction：$name"
        }
    }

    # ---- 2. 移除 hooks 键（保留用户其它配置） ----
    if (Test-Path $SettingsPath) {
        $settings = Read-SettingsJson
        if ($null -ne $settings) {
            $hooks = @{}
            if ($settings.ContainsKey("hooks") -and $null -ne $settings["hooks"]) {
                $hooks = $settings["hooks"]
            }
            if ($hooks.Count -gt 0) {
                foreach ($entry in Get-HookEntries) {
                    $ev = $entry.event
                    if ($hooks.ContainsKey($ev)) {
                        $kept = @()
                        foreach ($grp in @($hooks[$ev])) {
                            $mine = $false
                            foreach ($h in @($grp.hooks)) {
                                # 与安装侧判重口径一致（command + args[0]），避免误删用户自己的同解释器钩子
                                if ($h.command -eq $entry.command -and $h.args[0] -eq $entry.args[0]) { $mine = $true }
                            }
                            if (-not $mine) { $kept += $grp }
                        }
                        if ($kept.Count -eq 0) { $hooks.Remove($ev) } else { $hooks[$ev] = $kept }
                    }
                }
                if ($hooks.Count -eq 0) { $settings.Remove("hooks") } else { $settings["hooks"] = $hooks }
                Write-SettingsJson $settings
                Write-Host "  [卸载] hooks 键已从 settings.json 移除"
            } else {
                Write-Host "  [跳过] settings.json 无 hooks 键"
            }
        }
    }

    Write-Host "  [保留] config/connection.ini 与 runs/ 数据不删除"
    Write-Host "卸载完成。"
}


if ($Uninstall) { Uninstall-DataAgent } else { Install-DataAgent }
