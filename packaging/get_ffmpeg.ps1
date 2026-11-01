# Download a pinned FFmpeg build over HTTPS, verify SHA256, extract ffmpeg.exe to build\ffmpeg\.
# FFMPEG_SHA256 empty = first run (trust-on-first-use): the hash is printed so it can be pinned below.
$ErrorActionPreference = "Stop"
$Version = "8.1.2"
$Url = "https://github.com/GyanD/codexffmpeg/releases/download/$Version/ffmpeg-$Version-essentials_build.zip"
$Sha256 = "$env:FFMPEG_SHA256_OVERRIDE"
if (-not $Sha256) { $Sha256 = "" }   # <- pin here after the first CI run
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "build\ffmpeg"
$Zip = Join-Path $Root "build\ffmpeg.zip"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if (-not $Url.StartsWith("https://")) { throw "ffmpeg URL must be HTTPS" }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
$Actual = (Get-FileHash -Algorithm SHA256 $Zip).Hash.ToLower()
Write-Host "ffmpeg zip SHA256: $Actual"
if ($Sha256 -and ($Actual -ne $Sha256.ToLower())) { throw "ffmpeg SHA256 mismatch (expected $Sha256)" }
if (-not $Sha256) { Write-Warning "ffmpeg hash not pinned yet (TOFU). Pin: $Actual" }
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
