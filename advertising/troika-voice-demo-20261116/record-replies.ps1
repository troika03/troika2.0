Add-Type -AssemblyName System.Speech
$ErrorActionPreference = 'Stop'
$scriptFile = Join-Path $PSScriptRoot 'replies.json'
$spec = Get-Content -Raw -Encoding UTF8 -LiteralPath $scriptFile | ConvertFrom-Json
$folder = Join-Path $PSScriptRoot 'materials/voice'
New-Item -ItemType Directory -Path $folder -Force | Out-Null
foreach ($part in $spec.segments) {
    $speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    try {
        $culture = [Globalization.CultureInfo]::GetCultureInfo('ru-RU')
        $speaker.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::Female,
            [System.Speech.Synthesis.VoiceAge]::Adult, 0, $culture)
        if ($speaker.Voice.Culture.Name -ne $culture.Name) {
            throw 'Russian speech voice is not installed.'
        }
        $speaker.Rate = 2
        $speaker.SetOutputToWaveFile((Join-Path $folder ($part.id + '.wav')))
        $speaker.Speak($part.text)
    } finally {
        $speaker.Dispose()
    }
}
