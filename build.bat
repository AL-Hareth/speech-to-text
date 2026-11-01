@echo off
REM LectureScribe Windows build: clean venv -> hash-locked deps -> pip-audit -> ffmpeg -> PyInstaller
REM -> Inno Setup installer -> SHA256SUMS. Requires Python 3.12 (py launcher or set PYTHON=...).
setlocal enableextensions
cd /d "%~dp0"
if not defined PYTHON set "PYTHON=py -3.12"
if not defined LS_VERSION set "LS_VERSION=0.1.0"

echo === [1/7] clean virtual environment
if exist build\venv rmdir /s /q build\venv
if exist dist rmdir /s /q dist
%PYTHON% -m venv build\venv || goto :err
set "VPY=%CD%\build\venv\Scripts\python.exe"

echo === [2/7] install hash-locked dependencies
"%VPY%" -m pip install --disable-pip-version-check --no-deps --require-hashes -r requirements-build.txt || goto :err

echo === [3/7] security: pip-audit + bandit
"%VPY%" -m pip_audit -r requirements-build.txt --no-deps --disable-pip || goto :err
"%VPY%" -m bandit -q -r app || goto :err
"%VPY%" tools\security_scan.py || goto :err

echo === [4/7] ffmpeg (pinned, SHA256-verified)
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\get_ffmpeg.ps1 || goto :err

echo === [5/7] tests
set "QT_QPA_PLATFORM=offscreen"
set "PATH=%CD%\build\ffmpeg;%PATH%"
"%VPY%" -m pytest -q -p no:cacheprovider tests || goto :err
set "QT_QPA_PLATFORM="

echo === [6/7] PyInstaller
"%VPY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyi packaging\lecturescribe.spec || goto :err
copy /y build\ffmpeg\FFMPEG_LICENSE.txt dist\LectureScribe\ >nul 2>&1

echo === [7/7] Inno Setup installer
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (echo Inno Setup 6 not found & goto :err)
"%ISCC%" /Q packaging\installer.iss || goto :err

powershell -NoProfile -Command "Get-FileHash -Algorithm SHA256 dist\LectureScribe\LectureScribe.exe, dist\LectureScribe\lecturescribe-cli.exe, dist\installer\*.exe | ForEach-Object { $_.Hash.ToLower() + '  ' + (Resolve-Path -Relative $_.Path) } | Set-Content -Encoding ascii dist\SHA256SUMS.txt" || goto :err
type dist\SHA256SUMS.txt
echo BUILD OK
exit /b 0

:err
echo BUILD FAILED (errorlevel %errorlevel%)
exit /b 1
