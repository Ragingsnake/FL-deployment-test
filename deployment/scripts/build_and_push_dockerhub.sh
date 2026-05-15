#!/usr/bin/env bash
set -euo pipefail


# 1) Đặt biến WORKDIR (nếu khác, chỉnh lại)
# WORKDIR=~/Project_NT114

# 2) Copy overlay deployment của bạn vào source (nếu chưa)
# cp -R ~/deployment "$WORKDIR/deployment"

# 3) Copy file requirements cho Docker build context
# cp ~/deployment/docker/requirements.txt "$WORKDIR/requirements.txt"

# 4) Chạy script sửa code (inject PoA middleware, thay biến env, ...)
# bash ~/deployment/scripts/apply-fixes.sh "$WORKDIR"

# 5) Chuyển vào thư mục source trước khi build
# cd "$WORKDIR"

# 6) Build & push lên Docker Hub (hoặc gọi script build/push đã tạo)
# Ví dụ dùng script bạn đã thêm:
# ./deployment/scripts/build_and_push_dockerhub.sh <your-dockerhub-user> v1 linux/amd64
# (hoặc chạy thủ công: docker build / docker push; nhớ docker login trước)

# Build local images and push to Docker Hub
# Usage: build_and_push_dockerhub.sh DOCKERHUB_REPO [TAG] [PLATFORM]
# Example: ./build_and_push_dockerhub.sh myuser v1 linux/amd64

DOCKERHUB_REPO="${1:-}" 
if [ -z "$DOCKERHUB_REPO" ]; then
  echo "Usage: $0 DOCKERHUB_REPO [TAG] [PLATFORM]" >&2
  exit 2
fi

TAG="${2:-v1}"
PLATFORM="${3:-linux/amd64}"
BUILD_CTX="$(pwd)"

IMAGES=(fl-server fl-client fl-blockchain)

echo "Building and pushing images to Docker Hub: $DOCKERHUB_REPO (tag=$TAG, platform=$PLATFORM)"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker CLI not found. Install Docker and login with 'docker login' then retry." >&2
  exit 3
fi

# Prefer buildx if available
USE_BUILDX=0
if docker buildx version >/dev/null 2>&1; then
  USE_BUILDX=1
fi

for img in "${IMAGES[@]}"; do
  DOCKER_TAG="$DOCKERHUB_REPO/$img:$TAG"
  DOCKERFILE="deployment/docker/Dockerfile.$(echo $img | sed 's/fl-//')"
  # Special-case mapping: fl-blockchain -> Dockerfile.blockchain
  if [ "$img" = "fl-blockchain" ]; then
    DOCKERFILE="deployment/docker/Dockerfile.blockchain"
  elif [ "$img" = "fl-server" ]; then
    DOCKERFILE="deployment/docker/Dockerfile.server"
  elif [ "$img" = "fl-client" ]; then
    DOCKERFILE="deployment/docker/Dockerfile.client"
  fi

  echo "\n--- Building $img -> $DOCKER_TAG using $DOCKERFILE"

  if [ $USE_BUILDX -eq 1 ]; then
    echo "Using docker buildx to build and push $DOCKER_TAG"
    docker buildx build --platform "$PLATFORM" -f "$DOCKERFILE" -t "$DOCKER_TAG" --push "$BUILD_CTX"
  else
    echo "buildx not available — doing local docker build and push"
    docker build -f "$DOCKERFILE" -t "$DOCKER_TAG" "$BUILD_CTX"
    docker push "$DOCKER_TAG"
  fi
done

echo "\nAll images pushed to Docker Hub under $DOCKERHUB_REPO with tag $TAG"
