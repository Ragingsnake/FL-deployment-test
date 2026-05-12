#!/usr/bin/env bash
# =============================================================================
# One-shot deployment script for Azure Cloudshell.
# Provisions: AKS cluster + ACR, builds 3 Docker images, deploys all manifests.
# =============================================================================
set -euo pipefail

# ---------- USER-TUNABLE PARAMETERS ----------
RESOURCE_GROUP="${RESOURCE_GROUP:-fl-rg}"
LOCATION="${LOCATION:-southeastasia}"
AKS_NAME="${AKS_NAME:-fl-aks}"
ACR_NAME="${ACR_NAME:-flacr$RANDOM}"          # must be globally unique
NODE_COUNT="${NODE_COUNT:-3}"
NODE_SIZE="${NODE_SIZE:-Standard_B2ps_v2}"
TAG="${TAG:-v1}"
REPO_URL="${REPO_URL:-https://github.com/anhkiet-dao/Project_NT114.git}"
WORKDIR="${WORKDIR:-$PWD/Project_NT114}"
# ---------------------------------------------

echo "==> 1/8 az login (will prompt if not already logged in)"
az account show >/dev/null 2>&1 || az login

echo "==> 2/8 Resource group + ACR + AKS"
az group create -n "$RESOURCE_GROUP" -l "$LOCATION" -o none
az acr create  -n "$ACR_NAME" -g "$RESOURCE_GROUP" --sku Basic --admin-enabled true -o none
az aks  create -n "$AKS_NAME" -g "$RESOURCE_GROUP" \
  --node-count "$NODE_COUNT" --node-vm-size "$NODE_SIZE" \
  --enable-managed-identity --attach-acr "$ACR_NAME" \
  --generate-ssh-keys -o none

az aks get-credentials -n "$AKS_NAME" -g "$RESOURCE_GROUP" --overwrite-existing
REGISTRY="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
export REGISTRY TAG

echo "==> 3/8 Clone source"
if [ ! -d "$WORKDIR" ]; then
  git clone "$REPO_URL" "$WORKDIR"
fi

# Drop our deployment overlay into the source tree so Dockerfiles can find it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
cp -R "$DEPLOY_DIR" "$WORKDIR/deployment"
cp "$DEPLOY_DIR/docker/requirements.txt" "$WORKDIR/requirements.txt"

# Apply source fixes (env-var driven endpoints)
echo "==> 4/8 Patching hardcoded endpoints in source"
bash "$SCRIPT_DIR/apply-fixes.sh" "$WORKDIR"

echo "==> 5/8 Build & push images via ACR Tasks (no local docker required)"
cd "$WORKDIR"
az acr build -r "$ACR_NAME" -t "fl-server:$TAG"     -f deployment/docker/Dockerfile.server     .
az acr build -r "$ACR_NAME" -t "fl-client:$TAG"     -f deployment/docker/Dockerfile.client     .
az acr build -r "$ACR_NAME" -t "fl-blockchain:$TAG" -f deployment/docker/Dockerfile.blockchain .

echo "==> 6/8 Render manifests with REGISTRY/TAG and apply"
mkdir -p /tmp/k8s-rendered
for f in deployment/k8s/*.yaml; do
  envsubst < "$f" > "/tmp/k8s-rendered/$(basename "$f")"
done
kubectl apply -f /tmp/k8s-rendered/00-namespaces.yaml
kubectl apply -f /tmp/k8s-rendered/10-ipfs.yaml
kubectl apply -f /tmp/k8s-rendered/20-blockchain.yaml

echo "==> 7/8 Wait for blockchain RPC and run contract migration"
kubectl -n blockchain rollout status statefulset/geth --timeout=5m
kubectl -n blockchain wait --for=condition=complete job/contract-migrate --timeout=10m \
  || { echo "migration failed"; kubectl -n blockchain logs job/contract-migrate; exit 1; }

echo "==> 8/8 Deploy aggregator + clients"
kubectl apply -f /tmp/k8s-rendered/30-server.yaml
kubectl -n aggregation rollout status deploy/fl-server --timeout=5m
kubectl apply -f /tmp/k8s-rendered/40-clients.yaml

echo
echo "============================================================"
echo "  Deployment complete."
echo "  Cluster:  $AKS_NAME  ($RESOURCE_GROUP)"
echo "  Registry: $REGISTRY"
echo "  Watch:    kubectl get pods -A -w"
echo "  Logs:     kubectl -n aggregation logs -f deploy/fl-server"
echo "  See deployment/TROUBLESHOOTING.md for next steps."
echo "============================================================"
