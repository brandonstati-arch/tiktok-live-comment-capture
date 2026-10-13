@echo off
title Captura de comentarios - TikTok LIVE
cd /d "%~dp0"

echo ============================================================
echo   CAPTURA DE COMENTARIOS - TIKTOK LIVE
echo ============================================================
echo.

REM --- 1. Localizar Python -------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
  echo [ERROR] No se encontro Python en el sistema.
  echo.
  echo   Instala Python 3.10 o superior desde:
  echo   https://www.python.org/downloads/
  echo.
  echo   IMPORTANTE: durante la instalacion marca la casilla
  echo   "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
echo [1/3] Python detectado:
%PY% --version

REM --- 2. Entorno virtual --------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [2/3] Creando entorno virtual .venv ^(solo la primera vez^) ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] No se pudo crear el entorno virtual.
    pause
    exit /b 1
  )
) else (
  echo [2/3] Entorno virtual listo.
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM --- 3. Dependencias -----------------------------------------
"%VENV_PY%" -c "import TikTokLive, flask, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo [3/3] Instalando dependencias ^(solo la primera vez, puede tardar un minuto^) ...
  "%VENV_PY%" -m pip install --upgrade pip --quiet
  "%VENV_PY%" -m pip install TikTokLive flask openpyxl
  if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la instalacion de dependencias.
    echo         Comprueba tu conexion a internet y vuelve a intentarlo.
    pause
    exit /b 1
  )
) else (
  echo [3/3] Dependencias listas.
)

echo.
echo ------------------------------------------------------------
echo  Arrancando la aplicacion. El navegador se abrira solo.
echo  Para cerrar, pulsa Ctrl+C en esta ventana.
echo ------------------------------------------------------------
echo.

"%VENV_PY%" app.py --port 5000

echo.
echo La aplicacion se ha detenido.
pause
