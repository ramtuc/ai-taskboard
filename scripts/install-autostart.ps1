<#
.SYNOPSIS
  ai-taskboard をログオン時に非表示で自動起動するタスクを、タスク スケジューラに登録する。
.DESCRIPTION
  何も付けずに実行すると、登録する内容（ドライラン）を表示したあと確認プロンプトを出し、Y で登録する。
  -WhatIf を付けると表示だけで何も登録しない。-Confirm:$false で確認を省略する。
  タスクは「自分（今ログオンしているユーザー）が自分のログオン時に」起動し、パスワードは保存しない
  （LogonType = Interactive）。実体は wscript.exe が scripts\serve-hidden.vbs を非表示で動かし、
  その中で uv（絶対パスを渡す）が taskboard serve を起動する。ログは data\logs\serve.log。
  解除は scripts\uninstall-autostart.ps1。
.PARAMETER TaskName
  タスク名（既定 ai-taskboard）。
.PARAMETER Port
  待ち受けポート（既定 8765。serve-hidden.vbs に /port: として渡す）。
.EXAMPLE
  .\scripts\install-autostart.ps1 -WhatIf      # ドライラン（何も登録しない）
.EXAMPLE
  .\scripts\install-autostart.ps1              # 内容を見て Y → 登録
.LINK
  https://learn.microsoft.com/powershell/module/scheduledtasks/register-scheduledtask
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$TaskName = 'ai-taskboard',
    [ValidateRange(1, 65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks

$root    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vbs     = Join-Path $root 'scripts\serve-hidden.vbs'
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$logFile = Join-Path $root 'data\logs\serve.log'
$userId  = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path $vbs)) { throw "見つかりません: $vbs" }
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uvCmd) { throw 'uv が PATH にありません。https://docs.astral.sh/uv/getting-started/installation/' }
$uv = $uvCmd.Source

# wscript //B: バッチモード（スクリプトエラーのダイアログを出さない） //Nologo: バナー抑止
$argument = "//B //Nologo `"$vbs`" /uv:`"$uv`" /port:$Port"

$action    = New-ScheduledTaskAction -Execute $wscript -Argument $argument -WorkingDirectory $root
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $userId
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$description = "ai-taskboard Web UI (http://127.0.0.1:$Port/) をログオン時に非表示で起動する。" +
               "登録: scripts\install-autostart.ps1  解除: scripts\uninstall-autostart.ps1  停止: scripts\stop.cmd"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "== 登録する内容（ドライラン表示） ==" -ForegroundColor Cyan
Write-Host ("  タスク名        : {0}" -f $TaskName)
Write-Host ("  既存タスク      : {0}" -f $(if ($null -eq $existing) { 'なし（新規登録）' } else { "あり（状態 $($existing.State)）→ 上書き" }))
Write-Host ("  実行ユーザー    : {0}  （LogonType Interactive・パスワード保存なし・RunLevel Limited）" -f $userId)
Write-Host ("  トリガー        : {0} のログオン時" -f $userId)
Write-Host ("  実行ファイル    : {0}" -f $wscript)
Write-Host ("  引数            : {0}" -f $argument)
Write-Host ("  作業ディレクトリ: {0}" -f $root)
Write-Host ("  uv の絶対パス   : {0}" -f $uv)
Write-Host ("  ログ            : {0}" -f $logFile)
Write-Host ("  実行時間の上限  : {0}  （PT0S = 無制限。既定の 3 日で止められない）" -f $settings.ExecutionTimeLimit)
Write-Host ("  失敗時の再試行  : {0} 回・間隔 {1}" -f $settings.RestartCount, $settings.RestartInterval)
Write-Host ("  多重起動        : {0}  （起動中なら新しいインスタンスを無視）" -f $settings.MultipleInstances)
Write-Host ("  バッテリー      : バッテリー駆動でも起動する {0} ／ バッテリーに切替わっても止めない {1}" -f (-not $settings.DisallowStartIfOnBatteries), (-not $settings.StopIfGoingOnBatteries))
Write-Host ''

if ($PSCmdlet.ShouldProcess("タスク スケジューラ: $TaskName", 'Register-ScheduledTask（ログオン時の自動起動を登録）')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description $description -Force | Out-Null
    Write-Host "登録しました: $TaskName" -ForegroundColor Green
    Write-Host "  確認      : Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
    Write-Host "  今すぐ試す: Start-ScheduledTask -TaskName $TaskName   → http://127.0.0.1:$Port/healthz"
    Write-Host "  停止      : scripts\stop.cmd   解除: scripts\uninstall-autostart.ps1"
} else {
    Write-Host "登録していません。" -ForegroundColor Yellow
}
