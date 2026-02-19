@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ===== User-configurable settings =====
set "IMAGE_NAME=assistant-perry"
set "CONTAINER_NAME=perry"
set "REMOTE_USER=root"
set "REMOTE_HOST=2.server.barykin.de"
set "REMOTE_PATH=~/projects/perry"
set "REMOTE_KEY=C:\Users\baryk\.ssh\id_ed25519_strato_no"
set "REMOTE_ENV_FILE=%REMOTE_PATH%/.env"
set "HEALTHCHECK_WAIT_SEC=8"
set "RETAIN_RELEASES=5"

set "EXIT_CODE=0"
set "TAR_FILE="

call :log "[1/6] Preflight checks"
call :require_command docker || goto :fail
call :require_command ssh || goto :fail
call :require_command scp || goto :fail

if not exist "%REMOTE_KEY%" (
  call :error "Missing SSH key: %REMOTE_KEY%"
  goto :fail
)

ssh -i "%REMOTE_KEY%" %REMOTE_USER%@%REMOTE_HOST% "bash -lc \"set -euo pipefail; command -v docker > /dev/null 2>&1; mkdir -p '%REMOTE_PATH%' '%REMOTE_PATH%/data'; test -f '%REMOTE_ENV_FILE%'\""
if errorlevel 1 (
  call :error "Remote preflight failed (docker/path/.env check)."
  goto :fail
)

for /f %%i in ('git rev-parse --short HEAD 2^>NUL') do set "GIT_SHA=%%i"
if not defined GIT_SHA set "GIT_SHA=nogit"

for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString(\"yyyyMMdd-HHmmss\")"') do set "BUILD_TS=%%i"
if not defined BUILD_TS (
  call :error "Failed to build timestamp."
  goto :fail
)

set "RELEASE_TAG=%GIT_SHA%-%BUILD_TS%"
set "IMAGE_TAG=%IMAGE_NAME%:%RELEASE_TAG%"
set "TAR_FILE=%IMAGE_NAME%-%RELEASE_TAG%.tar"
set /a RETAIN_RELEASES_PLUS_ONE=%RETAIN_RELEASES%+1

call :log "[2/6] Build image: %IMAGE_TAG%"
docker build --tag "%IMAGE_TAG%" --tag "%IMAGE_NAME%:latest" .
if errorlevel 1 (
  call :error "Docker build failed."
  goto :fail
)

call :log "[3/6] Save image tar: %TAR_FILE%"
docker save -o "%TAR_FILE%" "%IMAGE_TAG%"
if errorlevel 1 (
  call :error "Docker save failed."
  goto :fail
)

call :log "[4/6] Upload tar to remote host"
scp -i "%REMOTE_KEY%" "%TAR_FILE%" %REMOTE_USER%@%REMOTE_HOST%:%REMOTE_PATH%/
if errorlevel 1 (
  call :error "SCP upload failed."
  goto :fail
)

call :log "[5/6] Deploy and health-check with rollback"
ssh -i "%REMOTE_KEY%" %REMOTE_USER%@%REMOTE_HOST% "bash -lc \"set -euo pipefail; cd '%REMOTE_PATH%'; ROLLBACK_IMAGE_ID=\$(docker container inspect --format='{{.Image}}' '%CONTAINER_NAME%' 2>/dev/null || true); if docker container inspect '%CONTAINER_NAME%' >/dev/null 2>&1; then docker stop '%CONTAINER_NAME%' >/dev/null 2>&1 || true; docker rm '%CONTAINER_NAME%' >/dev/null 2>&1 || true; fi; docker load -i '%TAR_FILE%'; docker run -d --restart always --name '%CONTAINER_NAME%' --env-file '%REMOTE_ENV_FILE%' -v '%REMOTE_PATH%/data:/data' '%IMAGE_TAG%' >/dev/null; sleep %HEALTHCHECK_WAIT_SEC%; RUNNING_STATE=\$(docker inspect --format='{{.State.Running}}' '%CONTAINER_NAME%' 2>/dev/null || echo false); if [ \"\$RUNNING_STATE\" != \"true\" ]; then echo 'New container failed health check. Rolling back.'; docker rm '%CONTAINER_NAME%' >/dev/null 2>&1 || true; if [ -n \"\$ROLLBACK_IMAGE_ID\" ]; then docker run -d --restart always --name '%CONTAINER_NAME%' --env-file '%REMOTE_ENV_FILE%' -v '%REMOTE_PATH%/data:/data' \"\$ROLLBACK_IMAGE_ID\" >/dev/null; fi; exit 1; fi; ls -1t %IMAGE_NAME%-*.tar 2>/dev/null | tail -n +%RETAIN_RELEASES_PLUS_ONE% | xargs -r rm -f; echo 'Deploy successful: %IMAGE_TAG%';\""
if errorlevel 1 (
  call :error "Remote deployment failed."
  goto :fail
)

call :log "[6/6] Cleanup local artifact"
if exist "%TAR_FILE%" del /q "%TAR_FILE%"

call :log "Deployment completed successfully."
goto :end

:fail
set "EXIT_CODE=1"
if defined TAR_FILE if exist "%TAR_FILE%" del /q "%TAR_FILE%" >NUL 2>&1
call :error "Deployment failed."
goto :end

:require_command
where %~1 >NUL 2>&1
if errorlevel 1 (
  call :error "Missing required command: %~1"
  exit /b 1
)
exit /b 0

:log
echo %~1
exit /b 0

:error
echo [ERROR] %~1
exit /b 0

:end
endlocal & exit /b %EXIT_CODE%
