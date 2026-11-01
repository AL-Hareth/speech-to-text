# Download a pinned FFmpeg build over HTTPS, verify SHA256, extract ffmpeg.exe to build\ffmpeg\.
# The SHA256 below was recorded from the first CI download (2026-11-01); any mismatch aborts the build.
$ErrorActionPreference = "Stop"
$Version = "8.1.2"
$Url = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/ffmpeg-$Version-essentials_build.zip"
$Sha256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "build\ffmpeg"
$Zip = Join-Path $Root "build\ffmpeg.zip"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if (-not $Url.StartsWith("https://")) { throw "ffmpeg URL must be HTTPS" }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
$Actual = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
Write-Host "ffmpeg zip SHA256: $Actual"
if ($Actual -ne $Sha256) { throw "ffmpeg SHA256 mismatch (expected $Sha256)" }
$Tmp = Join-Path $Root "build\ffmpeg_x"
if (Test-Path $Tmp) { Remove-Item -Recurse -Force $Tmp }
Expand-Archive -Path $Zip -DestinationPath $Tmp
$Exe = Get-ChildItem -Path $Tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (-not $Exe) { throw "ffmpeg.exe not found in archive" }
Copy-Item $Exe.FullName (Join-Path $Out "ffmpeg.exe") -Force
$Lic = Get-ChildItem -Path $Tmp -Recurse -Filter LICENSE* | Select-Object -First 1
if ($Lic) { Copy-Item $Lic.FullName (Join-Path $Out "FFMPEG_LICENSE.txt") -Force }
Remove-Item -Recurse -Force $Tmp, $Zip
& (Join-Path $Out "ffmpeg.exe") -hide_banner -version | Select-Object -First 1
