#!/usr/bin/env bash
set -euo pipefail

# One-shot deploy using an existing Project_NT114 checkout (no clone / no patch)
# Usage: deploy_using_existing.sh [WORKDIR] (defaults to $PWD/Project_NT114)

RESOURCE_GROUP="${RESOURCE_GROUP:-fl-rg}"
LOCATION="${LOCATION:-japanwest}"
AKS_NAME="${AKS_NAME:-fl-aks}"
ACR_NAME="${ACR_NAME:-flacr$RANDOM}"
NODE_COUNT="${NODE_COUNT:-3}"
NODE_SIZE="${NODE_SIZE:-Standard_B2as_v2}"
TAG="${TAG:-v1}"
SPLIT_TYPE="${SPLIT_TYPE:-non_iid}"
FL_ROUNDS="${FL_ROUNDS:-40}"
FL_STRATEGY="${FL_STRATEGY:-secure}"
AGGREGATION_METHOD="${AGGREGATION_METHOD:-reputation}"
NUM_BYZANTINE="${NUM_BYZANTINE:-1}"
TRIM_RATIO="${TRIM_RATIO:-0.1}"
RFA_CLIP_NORM="${RFA_CLIP_NORM:-1.0}"
VERIFICATION_MODE="${VERIFICATION_MODE:-off-chain}"
STAKING_ENABLED="${STAKING_ENABLED:-0}"
SECURE_AGG_ENABLED="${SECURE_AGG_ENABLED:-0}"
TRAINING_VERIFICATION_ENABLED="${TRAINING_VERIFICATION_ENABLED:-0}"
DEMO_ATTACK_TYPE="${DEMO_ATTACK_TYPE:-}"
DEMO_ATTACK_CLIENTS="${DEMO_ATTACK_CLIENTS:-}"
DEMO_ATTACK_START_ROUND="${DEMO_ATTACK_START_ROUND:-1}"
DEMO_ATTACK_END_ROUND="${DEMO_ATTACK_END_ROUND:-999999}"
DEMO_ATTACK_SCALE="${DEMO_ATTACK_SCALE:-}"
WORKDIR="${1:-$PWD/Project_NT114}"

if [ ! -d "$WORKDIR" ]; then
  echo "ERROR: WORKDIR $WORKDIR does not exist. Clone Project_NT114 or run apply-fixes first." >&2
  exit 2
fi

echo "==> 1/6 az login (will prompt if not already logged in)"
az account show >/dev/null 2>&1 || az login

echo "==> 2/6 Resource group + ACR + AKS"
az group create -n "$RESOURCE_GROUP" -l "$LOCATION" -o none
az acr create  -n "$ACR_NAME" -g "$RESOURCE_GROUP" --sku Basic --admin-enabled true -o none
az aks  create -n "$AKS_NAME" -g "$RESOURCE_GROUP" \
  --node-count "$NODE_COUNT" --node-vm-size "$NODE_SIZE" \
  --enable-managed-identity --attach-acr "$ACR_NAME" \
  --generate-ssh-keys -o none

az aks get-credentials -n "$AKS_NAME" -g "$RESOURCE_GROUP" --overwrite-existing
REGISTRY="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
export REGISTRY TAG SPLIT_TYPE FL_ROUNDS FL_STRATEGY AGGREGATION_METHOD NUM_BYZANTINE TRIM_RATIO RFA_CLIP_NORM VERIFICATION_MODE STAKING_ENABLED SECURE_AGG_ENABLED TRAINING_VERIFICATION_ENABLED DEMO_ATTACK_TYPE DEMO_ATTACK_CLIENTS DEMO_ATTACK_START_ROUND DEMO_ATTACK_END_ROUND DEMO_ATTACK_SCALE

# Drop our deployment overlay into the source tree so Dockerfiles can find it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
cp -R "$DEPLOY_DIR" "$WORKDIR/deployment"
cp "$DEPLOY_DIR/docker/requirements.txt" "$WORKDIR/requirements.txt"

echo "==> 3/6 Build & push images via ACR Tasks (no local docker required)"
cd "$WORKDIR"
az acr build -r "$ACR_NAME" -t "fl-server:$TAG"     -f deployment/docker/Dockerfile.server     --platform linux/amd64 .
az acr build -r "$ACR_NAME" -t "fl-client:$TAG"     -f deployment/docker/Dockerfile.client     --platform linux/amd64 .
az acr build -r "$ACR_NAME" -t "fl-blockchain:$TAG" -f deployment/docker/Dockerfile.blockchain --platform linux/amd64 .
az acr build -r "$ACR_NAME" -t "fl-zkp-node:$TAG"   -f deployment/docker/Dockerfile.zkp        --platform linux/amd64 .

echo "==> 4/6 Render manifests with REGISTRY/TAG and apply"
mkdir -p /tmp/k8s-rendered
for f in deployment/k8s/*.yaml; do
  envsubst '$REGISTRY $TAG $SPLIT_TYPE $FL_ROUNDS $FL_STRATEGY $AGGREGATION_METHOD $NUM_BYZANTINE $TRIM_RATIO $RFA_CLIP_NORM $VERIFICATION_MODE $STAKING_ENABLED $SECURE_AGG_ENABLED $TRAINING_VERIFICATION_ENABLED $DEMO_ATTACK_TYPE $DEMO_ATTACK_CLIENTS $DEMO_ATTACK_START_ROUND $DEMO_ATTACK_END_ROUND $DEMO_ATTACK_SCALE' < "$f" > "/tmp/k8s-rendered/$(basename "$f")"
done
kubectl apply -f /tmp/k8s-rendered/00-namespaces.yaml
kubectl apply -f /tmp/k8s-rendered/10-ipfs.yaml
kubectl apply -f /tmp/k8s-rendered/20-blockchain.yaml

echo "==> 5/6 Wait for blockchain RPC and run contract migration"
kubectl -n blockchain rollout status statefulset/geth --timeout=15m
kubectl -n blockchain rollout status deploy/zkp-node --timeout=5m
kubectl -n blockchain wait --for=condition=complete job/contract-migrate --timeout=15m \
  || { echo "migration failed"; kubectl -n blockchain logs job/contract-migrate; exit 1; }

echo "==> 6/6 Deploy aggregator + clients"
kubectl apply -f /tmp/k8s-rendered/30-server.yaml
kubectl -n aggregation rollout status deploy/fl-server --timeout=5m
kubectl apply -f /tmp/k8s-rendered/40-clients.yaml

echo
echo "Deployment complete using existing Project_NT114 at $WORKDIR"
echo "Cluster:  $AKS_NAME  ($RESOURCE_GROUP)"
echo "Registry: $REGISTRY"
echo "Watch:    kubectl get pods -A -w"
echo "Logs:     kubectl -n aggregation logs -f deploy/fl-server"
