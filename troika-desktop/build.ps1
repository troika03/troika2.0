param([switch]$Test, [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
if (!(Test-Path -LiteralPath $compiler)) { throw 'Install the Windows .NET Framework 4.8 developer tools.' }
$output = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root 'build' }
New-Item -ItemType Directory -Path $output -Force | Out-Null
& python (Join-Path (Split-Path $root) 'scripts\provision_windows_voice_id.py')
if ($LASTEXITCODE -ne 0) { throw 'Offline voice identity asset provisioning failed.' }
Copy-Item -LiteralPath (Join-Path $root 'assets') -Destination $output -Recurse -Force
$references = @('System.dll','System.Core.dll','System.Windows.Forms.dll','System.Drawing.dll','System.Net.Http.dll','System.Web.Extensions.dll','System.Security.dll','System.IO.Compression.dll','System.IO.Compression.FileSystem.dll','WPF\WindowsBase.dll','WPF\PresentationCore.dll','WPF\PresentationFramework.dll','WPF\UIAutomationClient.dll','WPF\UIAutomationTypes.dll','System.Xaml.dll') | ForEach-Object { '/reference:' + (Join-Path $framework $_) }
$sources = Get-ChildItem -LiteralPath (Join-Path $root 'src') -Filter '*.cs' | ForEach-Object { $_.FullName }
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /utf8output ('/win32manifest:' + (Join-Path $root 'app.manifest')) ('/out:' + (Join-Path $output 'TroikaDesktop.exe')) $references $sources
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
Copy-Item -LiteralPath (Join-Path $root 'TroikaDesktop.exe.config') -Destination $output -Force
if ($Test) {
    $testSources = @('OwnApi.cs','Json.cs','ApiClient.cs','LocalStore.cs','Voice.cs','Development.cs','DevelopmentRelay.cs','DevelopmentWorkflow.cs') | ForEach-Object { Join-Path $root ('src\' + $_) }
    $testSources += Join-Path $root 'tests\DesktopTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'DesktopTests.exe')) $references $testSources
    if ($LASTEXITCODE -ne 0) { throw 'Test build failed.' }
    & (Join-Path $output 'DesktopTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed.' }
    $capabilityTestSources = @('OwnApi.cs','LocalStore.cs','Json.cs','ApiClient.cs','CapabilityCatalogueService.cs') | ForEach-Object { Join-Path $root ('src\' + $_) }
    $capabilityTestSources += Join-Path $root 'tests\CapabilityCatalogueTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'CapabilityCatalogueTests.exe')) $references $capabilityTestSources
    if ($LASTEXITCODE -ne 0) { throw 'Capability catalogue test build failed.' }
    & (Join-Path $output 'CapabilityCatalogueTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Capability catalogue tests failed.' }
    $appearanceSource = Join-Path $root 'tests\DesktopAppearanceTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'DesktopAppearanceTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references $appearanceSource
    if ($LASTEXITCODE -ne 0) { throw 'Appearance test build failed.' }
    & (Join-Path $output 'DesktopAppearanceTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Appearance tests failed.' }
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'BillingTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\BillingTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Billing test build failed.' }
    & (Join-Path $output 'BillingTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Billing tests failed.' }
}
if ($Test) {
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'OwnApiTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\OwnApiTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Personal API test build failed.' }
    & (Join-Path $output 'OwnApiTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Personal API tests failed.' }
}
if ($Test) {
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'AutopilotTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\AutopilotTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Autopilot test build failed.' }
    & (Join-Path $output 'AutopilotTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Autopilot tests failed.' }
}
Write-Output ('Built: ' + (Join-Path $output 'TroikaDesktop.exe'))
if ($Test) {
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'VoiceIdentityTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\VoiceIdentityTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Voice identity test build failed.' }
    & (Join-Path $output 'VoiceIdentityTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Voice identity tests failed.' }
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'VoiceIdentityUiTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\VoiceIdentityUiTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Voice identity UI test build failed.' }
    & (Join-Path $output 'VoiceIdentityUiTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Voice identity UI tests failed.' }
}
if ($Test) {
    $computerUseSources = @('Json.cs','ComputerUseSession.cs','ComputerUseExecutor.cs','ComputerUseAgent.cs','ComputerUsePrototypeWindow.cs') | ForEach-Object { Join-Path $root ('src\' + $_) }
    $computerUseSources += Join-Path $root 'tests\ComputerUsePrototypeTests.cs'
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'ComputerUsePrototypeTests.exe')) $references $computerUseSources
    if ($LASTEXITCODE -ne 0) { throw 'Computer Use prototype test build failed.' }
    & (Join-Path $output 'ComputerUsePrototypeTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Computer Use prototype tests failed.' }
    & $compiler /nologo /target:exe /platform:x64 /utf8output ('/out:' + (Join-Path $output 'DesignReferenceTests.exe')) ('/reference:' + (Join-Path $output 'TroikaDesktop.exe')) $references (Join-Path $root 'tests\DesignReferenceTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Design reference test build failed.' }
    & (Join-Path $output 'DesignReferenceTests.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Design reference tests failed.' }
}
