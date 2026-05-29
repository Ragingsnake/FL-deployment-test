#!/usr/bin/env bash
# =============================================================================
# Generate training plots from FL server results
# =============================================================================
set -euo pipefail

NAMESPACE="${1:-aggregation}"
OUTPUT_DIR="${2:-./fl-outputs}"

echo "==> Finding FL server pod..."
POD=$(kubectl -n "$NAMESPACE" get pod -l app=fl-server -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD" ]; then
  echo "ERROR: No fl-server pod found in namespace $NAMESPACE"
  exit 1
fi

echo "Found pod: $POD"

echo ""
echo "==> Checking for plot_results.py in the pod..."
kubectl -n "$NAMESPACE" exec "$POD" -- find /app -name "plot_results.py" -o -name "*plot*.py" | head -10

echo ""
echo "==> Listing Python files in /app..."
kubectl -n "$NAMESPACE" exec "$POD" -- find /app -maxdepth 1 -name "*.py" -exec ls -la {} +

echo ""
echo "==> Checking what's currently in /app/picture..."
kubectl -n "$NAMESPACE" exec "$POD" -- ls -laR /app/picture

echo ""
echo "==> Looking for any existing PNG files..."
kubectl -n "$NAMESPACE" exec "$POD" -- find /app -name "*.png" -type f 2>/dev/null || echo "No PNG files found"

echo ""
echo "==> Checking /app/history (expected by plot_results.py)..."
# list history directory recursively if it exists, otherwise note missing
kubectl -n "$NAMESPACE" exec "$POD" -- test -d /app/history && \
  kubectl -n "$NAMESPACE" exec "$POD" -- ls -laR /app/history || \
  echo "No /app/history directory found in the pod"

# look specifically for any server_history JSON files
kubectl -n "$NAMESPACE" exec "$POD" -- find /app/history -maxdepth 2 -name "server_history*.json" -print 2>/dev/null || echo "No server_history JSON files found in /app/history"

echo ""
echo "==> Checking if plot_results.py exists and running it..."
if kubectl -n "$NAMESPACE" exec "$POD" -- test -f /app/plot_results.py; then
  echo "Found plot_results.py! Running it..."
  kubectl -n "$NAMESPACE" exec "$POD" -- python /app/plot_results.py

  echo ""
  echo "==> Checking /app/picture again after running plot_results.py..."
  kubectl -n "$NAMESPACE" exec "$POD" -- ls -la /app/picture

  echo ""
  echo "==> Pulling pictures to $OUTPUT_DIR..."
  mkdir -p "$OUTPUT_DIR"
  kubectl cp "$NAMESPACE/$POD:/app/picture" "$OUTPUT_DIR"

  echo ""
  echo "✓ Pictures saved to: $OUTPUT_DIR"
  ls -lh "$OUTPUT_DIR"
else
  echo "❌ plot_results.py not found"
  echo ""
  echo "Available Python files:"
  kubectl -n "$NAMESPACE" exec "$POD" -- find /app -maxdepth 1 -name "*.py" -exec basename {} \; | sort

  echo ""
  echo "Searching for plotting code in source files..."
  kubectl -n "$NAMESPACE" exec "$POD" -- grep -l "matplotlib\|plt.savefig\|plot" /app/*.py 2>/dev/null || echo "No plotting code found"
fi
