#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="$1"
REMOTE_ENV_FILE="$2"
REMOTE_PATH="$3"
TAR_FILE="$4"
IMAGE_TAG="$5"
HEALTHCHECK_WAIT_SEC="$6"
IMAGE_NAME="$7"
RETAIN_RELEASES="$8"

cd "$REMOTE_PATH"

ROLLBACK_IMAGE_ID="$(docker container inspect --format '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

docker load -i "$TAR_FILE"

docker run -d --restart always \
  --name "$CONTAINER_NAME" \
  --env-file "$REMOTE_ENV_FILE" \
  -v "$REMOTE_PATH/data:/data" \
  "$IMAGE_TAG" >/dev/null

sleep "$HEALTHCHECK_WAIT_SEC"

RUNNING_STATE="$(docker inspect --format '{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null || echo false)"
if [ "$RUNNING_STATE" != "true" ]; then
  echo "New container failed health check. Rolling back."
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if [ -n "$ROLLBACK_IMAGE_ID" ]; then
    docker run -d --restart always \
      --name "$CONTAINER_NAME" \
      --env-file "$REMOTE_ENV_FILE" \
      -v "$REMOTE_PATH/data:/data" \
      "$ROLLBACK_IMAGE_ID" >/dev/null
  fi
  exit 1
fi

KEEP_FROM=$((RETAIN_RELEASES + 1))
ls -1t "${IMAGE_NAME}"-*.tar 2>/dev/null | tail -n +"$KEEP_FROM" | xargs -r rm -f || true

echo "Deploy successful: $IMAGE_TAG"

