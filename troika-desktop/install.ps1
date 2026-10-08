param([string]$SourceDirectory = (Join-Path $PSScriptRoot 'build'), [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\TroikaDesktop'))
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($SourceDirectory)
$executable = Join-Path $source 'TroikaDesktop.exe'
if (!(Test-Path -LiteralPath $executable)) { throw 'Build TroikaDesktop.exe first.' }
$digest = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.Substring(0, 12).ToLowerInvariant()
$destination = Join-Path ([IO.Path]::GetFullPath($InstallDirectory)) ('releases\' + $digest)
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('TroikaDesktop.exe', 'TroikaDesktop.exe.config')) {
    $target = Join-Path $destination $name
    $inputFile = Join-Path $source $name
    $same = (Test-Path -LiteralPath $target) -and ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $inputFile -Algorithm SHA256).Hash)
    if (!$same) { Copy-Item -LiteralPath $inputFile -Destination $target -Force }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination $destination -Force
Copy-Item -LiteralPath (Join-Path (Split-Path $PSScriptRoot) 'LICENSE') -Destination $destination -Force
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Тройка ПК.lnk'))
$shortcut.TargetPath = Join-Path $destination 'TroikaDesktop.exe'
$shortcut.WorkingDirectory = $destination
$shortcut.Description = 'Тройка — самостоятельный клиент для Windows'
$shortcut.Save()
Write-Output ('Installed: ' + $shortcut.TargetPath)
