$ErrorActionPreference = 'Stop'
$appName = '造五活动助手'
$version = '1.01'
$src = Join-Path $PSScriptRoot 'app'
$dest = Join-Path $env:LOCALAPPDATA $appName
$exe = Join-Path $dest ($appName + '.exe')

if (-not (Test-Path (Join-Path $src ($appName + '.exe')))) {
    throw '安装包不完整：缺少主程序'
}

Get-Process -Name $appName -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 覆盖旧版本程序文件，保留账号与界面设置
Get-ChildItem -LiteralPath $dest -Force |
    Where-Object { $_.Name -notin @('accounts', 'account.local.json', 'ui_settings.json') } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $src '*') -Destination $dest -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $dest -Force

# 卸载入口
$uninstallCmd = "@echo off`r`ncd /d `"%TEMP%`"`r`npowershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"%~dp0uninstall.ps1`"`r`nexit`r`n"
Set-Content -LiteralPath (Join-Path $dest '卸载.cmd') -Value $uninstallCmd -Encoding ASCII

# 桌面与开始菜单快捷方式
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnkPath = Join-Path $folder ($appName + '.lnk')
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $exe
    $lnk.WorkingDirectory = $dest
    $lnk.IconLocation = "$exe,0"
    $lnk.Description = $appName
    $lnk.Save()
}

# 当前用户的卸载信息
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\zm5-toolbox'
New-Item -Path $key -Force | Out-Null
$sizeKb = [int](((Get-ChildItem -LiteralPath $dest -Recurse -File | Measure-Object Length -Sum).Sum) / 1KB)
Set-ItemProperty -Path $key -Name DisplayName -Value $appName
Set-ItemProperty -Path $key -Name DisplayVersion -Value $version
Set-ItemProperty -Path $key -Name Publisher -Value 'zm5-toolbox'
Set-ItemProperty -Path $key -Name InstallLocation -Value $dest
Set-ItemProperty -Path $key -Name DisplayIcon -Value ($exe + ',0')
Set-ItemProperty -Path $key -Name UninstallString -Value ('"' + (Join-Path $dest '卸载.cmd') + '"')
Set-ItemProperty -Path $key -Name QuietUninstallString -Value ('powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $dest 'uninstall.ps1') + '"')
New-ItemProperty -Path $key -Name NoModify -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name NoRepair -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $key -Name EstimatedSize -Value $sizeKb -PropertyType DWord -Force | Out-Null

Start-Process -FilePath $exe -WorkingDirectory $dest
