param([Parameter(Mandatory)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Window capture tests require Visual Studio C++ tools and the Windows SDK.' }
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or !$vs) { throw 'Visual Studio C++ tools were not found.' }
Import-Module (Join-Path $vs 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64' | Out-Null
$compiler = (Get-Command cl.exe -CommandType Application).Source
$source = Join-Path $PSScriptRoot 'ComputerUseWindowCapture.cpp'
$library = Join-Path $OutputDirectory 'TroikaWindowCapture.dll'
$object = Join-Path $OutputDirectory 'TroikaWindowCapture.obj'
$imports = Join-Path $OutputDirectory 'TroikaWindowCapture.lib'
& $compiler /nologo /std:c++17 /EHsc /MT /O2 /W4 /WX /LD "/Fo$object" $source /link "/OUT:$library" "/IMPLIB:$imports" d3d11.lib dwmapi.lib oleaut32.lib runtimeobject.lib user32.lib
if ($LASTEXITCODE -ne 0) { throw 'Windows Graphics Capture build failed.' }
