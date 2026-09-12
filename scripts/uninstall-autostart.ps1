<#
.SYNOPSIS
  install-autostart.ps1 で登録したログオン時自動起動のタスクを解除する。
.DESCRIPTION
  登録内容を表示したあと確認プロンプトを出し、Y で Unregister-ScheduledTask する。
  -WhatIf で表示のみ。動作中のサーバーは止めない（止めるのは scripts\stop.cmd）。
.PARAMETER TaskName
  タスク名（既定 ai-taskboard）。
.EXAMPLE
  .\scripts\uninstall-autostart.ps1
.LINK
  https://learn.microsoft.com/powershell/module/scheduledtasks/unregister-scheduledtask
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [string]$TaskName = 'ai-taskboard'
)
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "タスク '$TaskName' は登録されていません。何もしません。" -ForegroundColor Yellow
    exit 0
}
Write-Host ''
Write-Host "== 解除するタスク ==" -ForegroundColor Cyan
Write-Host ("  タスク        : {0}{1}  （状態 {2}）" -f $task.TaskPath, $task.TaskName, $task.State)
Write-Host ("  実行ファイル  : {0}" -f $task.Actions[0].Execute)
Write-Host ("  引数          : {0}" -f $task.Actions[0].Arguments)
Write-Host ''

if ($PSCmdlet.ShouldProcess("タスク スケジューラ: $TaskName", 'Unregister-ScheduledTask（ログオン時の自動起動を解除）')) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "解除しました: $TaskName" -ForegroundColor Green
    Write-Host "  動作中のサーバーは止めていません。止めるには scripts\stop.cmd"
} else {
    Write-Host "解除していません。" -ForegroundColor Yellow
}
