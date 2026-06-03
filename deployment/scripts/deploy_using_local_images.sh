#!/usr/bin/env bash
# Deploy using existing images from Docker Hub or local tarballs.
# Also provisions Azure resources (AKS, ACR) if running for the first time.
# Usage: deploy_using_local_images.sh [TAG] [IMAGE_DIR] [DOCKERHUB_REPO]
set -euo pipefail

# ---------- USER-TUNABLE PARAMETERS ----------
RESOURCE_GROUP="${RESOURCE_GROUP:-fl-rg}"
LOCATION="${LOCATION:-japanwest}"
AKS_NAME="${AKS_NAME:-fl-aks}"
ACR_NAME="${ACR_NAME:-flacr$RANDOM}"
NODE_COUNT="${NODE_COUNT:-3}"
NODE_SIZE="${NODE_SIZE:-Standard_B2as_v2}"
TAG="${1:-${TAG:-v1}}"
SPLIT_TYPE="${SPLIT_TYPE:-non_iid}"
FL_ROUNDS="${FL_ROUNDS:-40}"
IMAGE_DIR="${2:-./image-cache}"
DOCKERHUB_REPO="${3:-${DOCKERHUB_REPO:-}}"
REPO_URL="${REPO_URL:-https://github.com/anhkiet-dao/Project_NT114.git}"
WORKDIR="${WORKDIR:-$PWD/Project_NT114}"
# ----------------------------------------

IMAGES=(fl-server fl-client fl-blockchain fl-zkp-node)

echo "==> 1/7 az login (will prompt if not already logged in)"
az account show >/dev/null 2>&1 || az login

echo "==> 2/7 Resource group + ACR + AKS"
az group create -n "$RESOURCE_GROUP" -l "$LOCATION" -o none
az acr create  -n "$ACR_NAME" -g "$RESOURCE_GROUP" --sku Basic --admin-enabled true -o none
az aks  create -n "$AKS_NAME" -g "$RESOURCE_GROUP" \
  --node-count "$NODE_COUNT" --node-vm-size "$NODE_SIZE" \
  --enable-managed-identity --attach-acr "$ACR_NAME" \
  --generate-ssh-keys -o none

az aks get-credentials -n "$AKS_NAME" -g "$RESOURCE_GROUP" --overwrite-existing
REGISTRY="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
export REGISTRY TAG SPLIT_TYPE FL_ROUNDS

echo "==> 3/7 Prepare source (clone if needed)"
if [ ! -d "$WORKDIR" ]; then
  git clone "$REPO_URL" "$WORKDIR"
fi

# Drop our deployment overlay into the source tree so Dockerfiles can find it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
cp -R "$DEPLOY_DIR" "$WORKDIR/deployment"
cp "$DEPLOY_DIR/docker/requirements.txt" "$WORKDIR/requirements.txt"

echo "==> 4/7 Apply fixes to source"
bash "$SCRIPT_DIR/apply-fixes.sh" "$WORKDIR"
cd "$WORKDIR"

echo "==> 5/7 Prepare images"
if [ -n "$DOCKERHUB_REPO" ]; then
  echo "Using Docker Hub repo: $DOCKERHUB_REPO (kubectl will pull images on demand)"
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

echo "==> 6/7 Render manifests and apply"
mkdir -p /tmp/k8s-rendered
for f in deployment/k8s/*.yaml; do
  envsubst '$REGISTRY $TAG $SPLIT_TYPE $FL_ROUNDS' < "$f" > "/tmp/k8s-rendered/$(basename "$f")"
  if [ -n "$DOCKERHUB_REPO" ]; then
    # force images to point to Docker Hub repo
    sed -i -E "s|image:\s+.*/([a-zA-Z0-9_\-]+):${TAG}|image: ${DOCKERHUB_REPO}/\1:${TAG}|g" "/tmp/k8s-rendered/$(basename "$f")"
    # ensure imagePullPolicy allows pulling from Docker Hub
    sed -i -E "s/imagePullPolicy:\s*(Never|IfNotPresent|Always|.*)/imagePullPolicy: IfNotPresent/" "/tmp/k8s-rendered/$(basename "$f")" || true
  else
    # strip registry and set imagePullPolicy to Never so kube uses local images
    sed -i -E "s|image:\s.*/([a-zA-Z0-9_\-]+):${TAG}|image: \1:${TAG}|g" "/tmp/k8s-rendered/$(basename "$f")"
    sed -i -E "s/imagePullPolicy:\s*(IfNotPresent|Always|.*)/imagePullPolicy: Never/" "/tmp/k8s-rendered/$(basename "$f")" || true
  fi
done

kubectl apply -f /tmp/k8s-rendered/00-namespaces.yaml
kubectl apply -f /tmp/k8s-rendered/10-ipfs.yaml
kubectl apply -f /tmp/k8s-rendered/20-blockchain.yaml

echo "==> 7/7 Wait for blockchain and deploy aggregator+clients"
kubectl -n blockchain rollout status statefulset/geth --timeout=15m
kubectl -n blockchain rollout status deploy/zkp-node --timeout=5m
kubectl -n blockchain wait --for=condition=complete job/contract-migrate --timeout=15m \
  || { echo "migration failed"; kubectl -n blockchain logs job/contract-migrate; exit 1; }

kubectl apply -f /tmp/k8s-rendered/30-server.yaml
kubectl -n aggregation rollout status deploy/fl-server --timeout=5m
kubectl apply -f /tmp/k8s-rendered/40-clients.yaml

echo
echo "Deployment complete."
echo "Cluster:  $AKS_NAME  ($RESOURCE_GROUP)"
echo "Watch:    kubectl get pods -A -w"
echo "Logs:     kubectl -n aggregation logs -f deploy/fl-server"
