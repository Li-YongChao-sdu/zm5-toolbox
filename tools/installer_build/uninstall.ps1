$ErrorActionPreference = 'SilentlyContinue'
$appName = '造五活动助手'
$dest = $PSScriptRoot

Get-Process -Name $appName | Stop-Process -Force

Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) ($appName + '.lnk')) -Force
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) ($appName + '.lnk')) -Force
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\zm5-toolbox' -Recurse -Force

# 由临时脚本延迟删除安装目录，避免卸载程序占用文件
$cleanup = Join-Path $env:TEMP ('zm5_uninstall_' + [guid]::NewGuid().ToString('N') + '.cmd')
$body = "@echo off`r`ntimeout /t 3 >nul`r`nrd /s /q `"$dest`"`r`ndel `"%~f0`"`r`n"
Set-Content -LiteralPath $cleanup -Value $body -Encoding Default
Start-Process -FilePath $cleanup -WindowStyle Hidden
