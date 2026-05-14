#!/usr/bin/env bash
set -euo pipefail

# Usage: save_images_from_acr.sh <ACR_NAME> [TAG] [OUT_DIR] [DOCKERHUB_REPO]
# Example: save_images_from_acr.sh myacr v1 ./image-cache mydockerhubuser

ACR_NAME="${1:-${ACR_NAME:-}}"
if [ -z "$ACR_NAME" ]; then
  echo "Usage: $0 <ACR_NAME> [TAG] [OUT_DIR] [DOCKERHUB_REPO]" >&2
  exit 2
fi

TAG="${2:-${TAG:-v1}}"
OUT_DIR="${3:-./image-cache}"
DOCKERHUB_REPO="${4:-${DOCKERHUB_REPO:-}}"   # e.g. myuser

IMAGES=(fl-server fl-client fl-blockchain)
mkdir -p "$OUT_DIR"

echo "Logging in to ACR: $ACR_NAME"
az acr login -n "$ACR_NAME"

for img in "${IMAGES[@]}"; do
  FQIN="$ACR_NAME.azurecr.io/$img:$TAG"
  TARFILE="$OUT_DIR/${img}_${TAG}.tar"
  echo "Pulling $FQIN..."
  docker pull "$FQIN"
  echo "Saving $FQIN -> $TARFILE"
  docker save -o "$TARFILE" "$FQIN"

  if [ -n "$DOCKERHUB_REPO" ]; then
    HUB_TAG="$DOCKERHUB_REPO/$img:$TAG"
    echo "Tagging $FQIN -> $HUB_TAG"
    docker tag "$FQIN" "$HUB_TAG"
    echo "Pushing $HUB_TAG (ensure you ran 'docker login' to Docker Hub)"
    docker push "$HUB_TAG"
  fi
done

echo "Saved images to $OUT_DIR"
if [ -n "$DOCKERHUB_REPO" ]; then
  echo "Also pushed images to Docker Hub under $DOCKERHUB_REPO/*:$TAG"
fi
