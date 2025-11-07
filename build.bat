@echo off
set IMAGE_NAME=assistant-perry
set TAR_FILE=assistant-perry.tar
set REMOTE_USER=root
set REMOTE_HOST=2.server.barykin.de
set REMOTE_PATH=~/projects/perry
set REMOTE_KEY=C:\Users\baryk\.ssh\id_ed25519_strato_no
REM Build Docker image
docker build --tag %IMAGE_NAME% .

REM Save Docker image to tar file
docker save -o %TAR_FILE% %IMAGE_NAME%

REM Copy tar file to remote server
scp -i %REMOTE_KEY% %TAR_FILE% %REMOTE_USER%@%REMOTE_HOST%:%REMOTE_PATH%

REM Run remote commands: load image and restart container
ssh -i %REMOTE_KEY% %REMOTE_USER%@%REMOTE_HOST% "cd %REMOTE_PATH% && docker load -i %TAR_FILE% && docker stop perry || true && docker rm perry || true && docker run -d --restart always --name perry -v %REMOTE_PATH%/data:/data %IMAGE_NAME%"

REM Clean up local tar file
del %TAR_FILE%
