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
DEBUG_MODE="${9:-0}"
RELEASE_IMAGE_TAG="${10:-}"

cd "$REMOTE_PATH"

contains() {
  local needle="$1"
  shift
  for item in "$@"; do
    if [ "$item" = "$needle" ]; then
      return 0
    fi
  done
  return 1
}

ROLLBACK_IMAGE_ID="$(docker container inspect --format '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

docker load -i "$TAR_FILE" >/dev/null

if [ -n "$RELEASE_IMAGE_TAG" ]; then
  docker tag "$IMAGE_TAG" "$RELEASE_IMAGE_TAG"
fi

docker run -d --restart always \
  --name "$CONTAINER_NAME" \
  --env-file "$REMOTE_ENV_FILE" \
  -e "PERRY_DEBUG=$DEBUG_MODE" \
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
      -e "PERRY_DEBUG=0" \
      -v "$REMOTE_PATH/data:/data" \
      "$ROLLBACK_IMAGE_ID" >/dev/null
  fi
  exit 1
fi

CURRENT_IMAGE_ID="$(docker container inspect --format '{{.Image}}' "$CONTAINER_NAME" 2>/dev/null || true)"
KEEP_IDS=("$ROLLBACK_IMAGE_ID" "$CURRENT_IMAGE_ID")
KEEP_TAGS=("$IMAGE_NAME:latest")

mapfile -t ALL_TAGS < <(docker image ls "$IMAGE_NAME" --format '{{.Repository}}:{{.Tag}}')
ROLLING_TAGS=()
for tag in "${ALL_TAGS[@]}"; do
  if [ -z "$tag" ] || [ "$tag" = "$IMAGE_NAME:<none>" ]; then
    continue
  fi
  if [[ "$tag" == "$IMAGE_NAME:latest" ]] || [[ "$tag" == "$IMAGE_NAME:release-"* ]]; then
    if ! contains "$tag" "${KEEP_TAGS[@]}"; then
      KEEP_TAGS+=("$tag")
    fi
    continue
  fi
  if ! contains "$tag" "${ROLLING_TAGS[@]}"; then
    ROLLING_TAGS+=("$tag")
  fi
done

rolling_keep_count=0
for tag in "${ROLLING_TAGS[@]}"; do
  if [ "$rolling_keep_count" -ge "$RETAIN_RELEASES" ]; then
    break
  fi
  KEEP_TAGS+=("$tag")
  rolling_keep_count=$((rolling_keep_count + 1))
done

while IFS= read -r line; do
  [ -z "$line" ] && continue
  tag="${line%% *}"
  image_id="${line##* }"

  if [ "$tag" = "$IMAGE_NAME:<none>" ]; then
    if ! contains "$image_id" "${KEEP_IDS[@]}"; then
      docker image rm "$image_id" >/dev/null 2>&1 || true
    fi
    continue
  fi

  if contains "$tag" "${KEEP_TAGS[@]}"; then
    continue
  fi
  if contains "$image_id" "${KEEP_IDS[@]}"; then
    continue
  fi
  docker image rm "$tag" >/dev/null 2>&1 || true
done < <(docker image ls "$IMAGE_NAME" --format '{{.Repository}}:{{.Tag}} {{.ID}}')

docker image prune -f >/dev/null 2>&1 || true

KEEP_FROM=$((RETAIN_RELEASES + 1))
ls -1t "${IMAGE_NAME}"-*.tar 2>/dev/null | tail -n +"$KEEP_FROM" | xargs -r rm -f || true

echo "Deploy successful: $IMAGE_TAG (debug=$DEBUG_MODE)"
