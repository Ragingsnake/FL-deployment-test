#!/usr/bin/env bash
# =============================================================================
# Quick fix: rebuild blockchain image with correct platform architecture
# =============================================================================
set -euo pipefail

echo "==> Detecting ACR and source directory"
ACR_NAME="${ACR_NAME:-$(az acr list --query '[0].name' -o tsv)}"
RESOURCE_GROUP="${RESOURCE_GROUP:-$(az acr show -n "$ACR_NAME" --query resourceGroup -o tsv)}"
TAG="${TAG:-v1}"

echo "==> Using ACR: $ACR_NAME in $RESOURCE_GROUP"

# Find the source directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Building blockchain image with platform linux/amd64"
cd "$WORKDIR"
az acr build \
  -r "$ACR_NAME" \
  -t "fl-blockchain:$TAG" \
  -f deployment/docker/Dockerfile.blockchain \
  --platform linux/amd64 \
  .

echo "==> Restarting blockchain pod to use new image"
kubectl -n blockchain delete pod geth-0

echo "==> Waiting for pod to restart"
kubectl -n blockchain wait --for=condition=ready pod/geth-0 --timeout=5m

echo "==> Success! Blockchain pod is running."
kubectl -n blockchain get pods
