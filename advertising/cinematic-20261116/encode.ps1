param(
    [string]$FrameDirectory = (Join-Path $PSScriptRoot 'frames'),
    [string]$FallbackDirectory = $env:TROIKA_RESUME_FRAME_DIR
)

$ErrorActionPreference = 'Stop'
$sourceMix = Join-Path $PSScriptRoot 'audio-premaster.wav'
$untrimmed = Join-Path $PSScriptRoot 'Troika-untrimmed.mp4'
$film = Join-Path $PSScriptRoot 'Troika-Cinematic-1080p.mp4'
$videoFilter = 'scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p'
$encoderArgs = @(
    '-hide_banner', '-loglevel', 'error', '-stats', '-y',
    '-f', 'image2pipe', '-framerate', '60000/1001', '-c:v', 'png', '-i', 'pipe:0', '-i', $sourceMix,
    '-map', '0:v:0', '-map', '1:a:0', '-frames:v', '724',
    '-vf', $videoFilter, '-c:v', 'libx264', '-preset', 'medium', '-crf', '17',
    '-bf', '0', '-g', '120', '-pix_fmt', 'yuv420p',
    '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1',
    '-colorspace', 'bt709', '-color_range', 'tv',
    '-af', 'volume=1.26dB', '-c:a', 'aac', '-b:a', '320k', '-ar', '48000',
    '-video_track_timescale', '60000', '-movie_timescale', '60000',
    '-movflags', '+faststart', '-use_editlist', '1',
    '-metadata', 'title=Тройка', '-metadata', 'comment=Music: Rising Forest by Diego Nava (Mixkit)',
    $untrimmed
)
& python (Join-Path $PSScriptRoot 'frame_pipe.py') $FrameDirectory ($FallbackDirectory ?? '') @encoderArgs
if ($LASTEXITCODE -ne 0) { throw 'Encoding failed' }

& python (Join-Path $PSScriptRoot 'trim_mp4.py') $untrimmed $film
if ($LASTEXITCODE -ne 0) { throw 'Presentation trim failed' }

$result = & ffprobe -v error -count_frames -show_entries 'stream=codec_name,width,height,pix_fmt,avg_frame_rate,duration,nb_read_frames,sample_rate:format=duration' -of json $film | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Could not verify rendered film' }
$video, $audio = $result.streams
if (
    $video.codec_name -ne 'h264' -or $video.width -ne 1920 -or $video.height -ne 1080 -or
    $video.pix_fmt -ne 'yuv420p' -or $video.avg_frame_rate -ne '60000/1001' -or
    $video.nb_read_frames -ne '724' -or $video.duration -ne '12.075000' -or
    $audio.codec_name -ne 'aac' -or $audio.duration -ne '12.075000' -or
    $result.format.duration -ne '12.075000'
) {
    throw ($result | ConvertTo-Json -Depth 6)
}
$result | ConvertTo-Json -Depth 6
