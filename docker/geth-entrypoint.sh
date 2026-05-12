#!/usr/bin/env bash
set -euo pipefail

DATADIR=/chain/data
GENESIS=/chain/genesis.json
PASSFILE=/chain/password.txt

mkdir -p "$DATADIR"

if [ ! -f "$PASSFILE" ]; then
  echo "flpoa" > "$PASSFILE"
fi

# First-run bootstrap: create a sealer account + clique genesis
if [ ! -d "$DATADIR/keystore" ] || [ -z "$(ls -A "$DATADIR/keystore" 2>/dev/null || true)" ]; then
  echo "[geth] Creating sealer account..."
  geth --datadir "$DATADIR" account new --password "$PASSFILE" > /tmp/acc.out
  SEALER=$(grep -oE '0x[0-9a-fA-F]{40}' /tmp/acc.out | head -1)
  SEALER_NO0x=${SEALER#0x}

  cat > "$GENESIS" <<EOF
{
  "config": {
    "chainId": 1337,
    "homesteadBlock": 0,
    "eip150Block": 0,
    "eip155Block": 0,
    "eip158Block": 0,
    "byzantiumBlock": 0,
    "constantinopleBlock": 0,
    "petersburgBlock": 0,
    "istanbulBlock": 0,
    "berlinBlock": 0,
    "clique": { "period": 2, "epoch": 30000 }
  },
  "difficulty": "1",
  "gasLimit": "8000000",
  "extradata": "0x0000000000000000000000000000000000000000000000000000000000000000${SEALER_NO0x}0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
  "alloc": {
    "${SEALER_NO0x}": { "balance": "100000000000000000000000" }
  }
}
EOF

  geth --datadir "$DATADIR" init "$GENESIS"
  echo "$SEALER" > /chain/sealer.addr
fi

SEALER=$(cat /chain/sealer.addr)

echo "[geth] Starting PoA node, sealer = $SEALER"
exec geth \
  --datadir "$DATADIR" \
  --networkid 1337 \
  --http --http.addr 0.0.0.0 --http.port 8545 \
  --http.api "eth,net,web3,personal,clique,miner,admin" \
  --http.corsdomain "*" --http.vhosts "*" \
  --ws --ws.addr 0.0.0.0 --ws.port 8546 --ws.api "eth,net,web3" --ws.origins "*" \
  --allow-insecure-unlock \
  --unlock "$SEALER" --password "$PASSFILE" \
  --mine --miner.etherbase "$SEALER" \
  --nodiscover
