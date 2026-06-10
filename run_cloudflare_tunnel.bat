@echo off
REM Туннель HTTPS до локального сервера (для камеры Safari на телефоне).
REM Установите cloudflared и добавьте в PATH:
REM https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

where cloudflared >nul 2>&1
if errorlevel 1 (
  echo [Ошибка] cloudflared не найден в PATH.
  exit /b 1
)

echo Туннель к http://%HOST%:%PORT%
echo После запуска откройте выданную ссылку https://... на телефоне.
echo Сервер уже должен слушать порт %PORT% (Parking Eye / uvicorn).
echo.

cloudflared tunnel --url http://%HOST%:%PORT%
