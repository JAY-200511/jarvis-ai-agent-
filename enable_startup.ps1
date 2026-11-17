$ErrorActionPreference = 'Stop'
$startupFolder = [Environment]::GetFolderPath('Startup')
$launchScript = Join-Path $PSScriptRoot 'start_jarvis.bat'
$shortcutPath = Join-Path $startupFolder 'JARVIS.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launchScript
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Description = 'Start JARVIS when you sign in to Windows'
$shortcut.Save()
Write-Host 'JARVIS will start when your Windows account signs in.'
Write-Host 'To remove auto-start, delete this shortcut:'
Write-Host $shortcutPath
