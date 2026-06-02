#!/usr/bin/env bash
# Copies generated charts/logs out of the FL server pod onto your local machine.
set -euo pipefail

DEST="${1:-./fl-outputs}"
NS="aggregation"

POD=$(kubectl -n "$NS" get pod -l app=fl-server -o jsonpath='{.items[0].metadata.name}')
echo "Copying /app/picture and /app/history from $POD -> $DEST"
mkdir -p "$DEST"
kubectl cp "$NS/$POD:/app/picture" "$DEST"
kubectl cp "$NS/$POD:/app/history" "$DEST/history"
echo "Done. Files in: $DEST"
