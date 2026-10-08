param([switch]$Test, [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Install the Windows .NET Framework 4.8 developer tools.' }
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'build' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
$references = @('System.dll','System.Core.dll','System.Net.Http.dll','System.Web.Extensions.dll','System.Security.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll','WPF\WindowsBase.dll','WPF\PresentationCore.dll','WPF\PresentationFramework.dll','System.Xaml.dll') | ForEach-Object { '/reference:' + (Join-Path $framework $_) }
$sources = Get-ChildItem -LiteralPath (Join-Path $root 'src') -Filter '*.cs' | ForEach-Object { $_.FullName }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /utf8output ('/win32manifest:' + (Join-Path $root 'app.manifest')) ('/out:' + (Join-Path $output 'TroikaDesktop.exe')) $references $sources
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
Copy-Item -LiteralPath (Join-Path $root 'TroikaDesktop.exe.config') -Destination $output -Force
if ($Test) {
    $testSources = @('Json.cs','ApiClient.cs','LocalStore.cs','Voice.cs','Development.cs') | ForEach-Object { Join-Path $root ('src\' + $_) }
    $testSources += Join-Path $root 'tests\DesktopTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'DesktopTests.exe')) $references $testSources
    if ($LASTEXITCODE -ne 0) { throw 'Test build failed.' }
    & (Join-Path $output 'DesktopTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed.' }
    $capabilityTestSources = @('Json.cs','ApiClient.cs','CapabilityCatalogueService.cs') | ForEach-Object { Join-Path $root ('src\' + $_) }
    $capabilityTestSources += Join-Path $root 'tests\CapabilityCatalogueTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'CapabilityCatalogueTests.exe')) $references $capabilityTestSources
    if ($LASTEXITCODE -ne 0) { throw 'Capability catalogue test build failed.' }
    & (Join-Path $output 'CapabilityCatalogueTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Capability catalogue tests failed.' }
}
Write-Output ('Built: ' + (Join-Path $output 'TroikaDesktop.exe'))
