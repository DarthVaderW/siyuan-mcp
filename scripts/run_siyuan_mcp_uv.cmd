@echo off
setlocal

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "VENV=%ROOT%\.venv-local"
set "TEMP=%ROOT%\.tmp"
set "TMP=%ROOT%\.tmp"
set "TMPDIR=%ROOT%\.tmp"
set "UV_CACHE_DIR=%ROOT%\.uv-cache"
set "PYTHONPATH=%ROOT%\scripts\python_sitecustomize"
set "UV_EXE=uv.exe"

if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe" (
  set "UV_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
)

if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%UV_CACHE_DIR%" mkdir "%UV_CACHE_DIR%"

pushd "%ROOT%"
"%UV_EXE%" run python -m siyuan_research_mcp.server
popd
