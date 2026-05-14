#!/usr/bin/env bash
set -euo pipefail


# Usage: deploy_using_local_images.sh [TAG] [IMAGE_DIR] [DOCKERHUB_REPO]
# If DOCKERHUB_REPO is provided (e.g. myuser), the script will pull
# images from Docker Hub (myuser/fl-server:TAG etc) and update manifests
# to point to those images. Otherwise it will load local tarballs from IMAGE_DIR.

TAG="${1:-${TAG:-v1}}"
IMAGE_DIR="${2:-./image-cache}"
DOCKERHUB_REPO="${3:-${DOCKERHUB_REPO:-}}"

IMAGES=(fl-server fl-client fl-blockchain)

if [ -n "$DOCKERHUB_REPO" ]; then
  echo "Pulling images from Docker Hub under $DOCKERHUB_REPO"
  for img in "${IMAGES[@]}"; do
    FQIN="$DOCKERHUB_REPO/$img:$TAG"
    echo "Pulling $FQIN"
    docker pull "$FQIN"
  done
else
  if [ ! -d "$IMAGE_DIR" ]; then
    echo "Image dir $IMAGE_DIR not found" >&2
    exit 2
  fi
  echo "Loading images from $IMAGE_DIR"
  for tar in "$IMAGE_DIR"/*_${TAG}.tar; do
    [ -e "$tar" ] || continue
    echo "Loading $tar"
    docker load -i "$tar"
  done
fi

echo "Rendering manifests"
mkdir -p /tmp/k8s-rendered-local
for f in deployment/k8s/*.yaml; do
  envsubst '$TAG' < "$f" > "/tmp/k8s-rendered-local/$(basename "$f")"
  if [ -n "$DOCKERHUB_REPO" ]; then
    # force images to point to Docker Hub repo
    sed -i -E "s|image:\s+.*/([a-zA-Z0-9_\-]+):${TAG}|image: ${DOCKERHUB_REPO}/\1:${TAG}|g" "/tmp/k8s-rendered-local/$(basename "$f")"
    # ensure imagePullPolicy allows pulling from Docker Hub
    sed -i -E "s/imagePullPolicy:\s*(Never|IfNotPresent|Always|.*)/imagePullPolicy: IfNotPresent/" "/tmp/k8s-rendered-local/$(basename "$f")" || true
  else
    # strip registry and set imagePullPolicy to Never so kube uses local images
    sed -i -E "s|image:\s.*/([a-zA-Z0-9_\-]+):${TAG}|image: \1:${TAG}|g" "/tmp/k8s-rendered-local/$(basename "$f")"
    sed -i -E "s/imagePullPolicy:\s*(IfNotPresent|Always|.*)/imagePullPolicy: Never/" "/tmp/k8s-rendered-local/$(basename "$f")" || true
  fi
done

echo "Applying rendered manifests"
kubectl apply -f /tmp/k8s-rendered-local/00-namespaces.yaml
kubectl apply -f /tmp/k8s-rendered-local/10-ipfs.yaml
kubectl apply -f /tmp/k8s-rendered-local/20-blockchain.yaml
kubectl apply -f /tmp/k8s-rendered-local/30-server.yaml
kubectl apply -f /tmp/k8s-rendered-local/40-clients.yaml

echo "Deploy using local/DockerHub images complete. Watch pods with: kubectl get pods -A -w"
