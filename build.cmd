@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.cmd and install requirements-dev.txt and PyInstaller first.
  exit /b 1
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --noconsole --name MediaArchive ^
  --icon "%CD%\assets\app-icon.ico" ^
  --distpath "work\package-dist" --workpath "work\package-build" --specpath "work" ^
  --add-data "%CD%\app\static;app/static" --add-data "%CD%\assets;assets" ^
  --collect-all yt_dlp --collect-all gallery_dl ^
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on ^
  --hidden-import app.worker --hidden-import webview.platforms.edgechromium ^
  "%CD%\main.py" || exit /b 1
echo Built work\package-dist\MediaArchive\MediaArchive.exe
echo FFmpeg is not bundled; it is downloaded when needed.
