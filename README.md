# Deploying the FL + Blockchain + ZKP system on Azure Kubernetes Service

This folder turns the original `Project_NT114` (Flower-based FL + Ganache + local IPFS)
into a cloud-native deployment on **Azure Kubernetes Service** that matches the
4-namespace architecture in `architecture.drawio` (single IPFS node variant).

## What you get

| Namespace      | Workload                  | Image                      |
|----------------|---------------------------|----------------------------|
| `fl-clients`   | `fl-client-0..4` (STS)    | `fl-client`                |
| `ipfs`         | `ipfs-0` (STS, 1 replica) | `ipfs/kubo:v0.28.0`        |
| `blockchain`   | `geth-0` + migrate Job    | `fl-blockchain`            |
| `blockchain`   | `zkp-node` proof service  | `fl-zkp-node`              |
| `aggregation`  | `fl-server` (Deployment)  | `fl-server`                |

## TL;DR — running it on Azure Cloudshell

```bash
git clone https://github.com/<you>/<this-repo>.git && cd <this-repo>
bash deployment/scripts/deploy.sh
```

That single script:
1. `az login`, creates `fl-rg`, ACR, and an AKS cluster (3 × `Standard_D4s_v5` by default).
2. Clones the upstream FL repo.
3. Applies the source patches in `scripts/apply-fixes.sh` (de-hardcodes localhost endpoints).
4. Builds all four images with **ACR Tasks** — so you don't need Docker installed.
5. `envsubst`-renders the manifests with your registry + tag and `kubectl apply`s them.
6. Waits for the Truffle migration Job to publish `Reputation.sol`, then deploys the aggregator + clients.

Tune behaviour with env vars before running:

```bash
RESOURCE_GROUP=my-rg LOCATION=eastus NODE_COUNT=4 TAG=v2 bash deployment/scripts/deploy.sh
```

## Fixes applied to upstream

Found and patched by `scripts/apply-fixes.sh`:

* `blockchain.py` — hardcoded Ganache URL `http://127.0.0.1:7545` and a fixed
  contract address. Replaced with `ETH_RPC` env var + `REPUTATION_ADDRESS` (or
  a file written by the migrate Job).
* `ipfs_utils.py` — hardcoded `/ip4/127.0.0.1/tcp/5001`. Replaced with `IPFS_API` env var.
* `fl_client.py` — hardcoded `localhost:8080` server address. Replaced with
  `FL_SERVER_HOST` + `FL_SERVER_PORT` env vars.
* `truffle-config.js` — added a `kube` network entry pointing at `geth-svc`.

## ZKP / zkSNARK architecture

The deployment now has a dedicated `zkp-node` in the `blockchain` namespace:

```text
fl-client -> zkp-node /prove  -> proof
fl-client -> fl-server        -> model update + CID + proof
fl-server -> zkp-node /verify -> valid/invalid
fl-server -> geth/Reputation  -> proof hash + reputation result
```

This is intentionally the smallest change to the FL code. `zkp_utils.py` keeps
the old function names (`generate_proof`, `verify_proof`) but delegates to
`ZKP_NODE_URL=http://zkp-node-svc.blockchain.svc.cluster.local:8090` in
Kubernetes. Local development still falls back to the in-process proof helper
when `ZKP_NODE_URL` is not set.

For actual zkSNARKs, the boundary is the ZKP node: mount R1CS/WASM/zkey/vkey
artifacts into that pod and replace the `/prove` and `/verify` backend with
Groth16 or Plonk proof generation/verification. The FL clients, aggregator,
IPFS, and geth contract flow do not need to change as long as the ZKP node keeps
the same HTTP contract.

## Demo controls

The server sends demo flags to clients through Flower fit config:

| Demo | Server env vars |
|------|-----------------|
| Faulty client / poisoned update | `DEMO_FAULTY_CLIENTS=2`, optional `DEMO_FAULTY_START_ROUND=2`, `DEMO_FAULTY_END_ROUND=4`, `DEMO_FAULTY_NOISE_SCALE=0.25` |
| Invalid ZKP proof / rejected update | `DEMO_BAD_ZKP_CLIENTS=3`, optional `DEMO_BAD_ZKP_START_ROUND=2`, `DEMO_BAD_ZKP_END_ROUND=4` |

See `deployment/TROUBLESHOOTING.md` for exact `kubectl set env` demo commands
and expected log lines.

## Things you may still need

| Concern | Detail |
|--------|--------|
| **EMNIST data** | The clients reference `data_new/`. If the repo's bundled split is small enough (a few hundred MB), it is baked into the image. For larger datasets, mount an Azure Files PVC and modify `FL_Client/train.py` to load from `/data`. |
| **ZK circuit artifacts** | For actual zkSNARKs, mount proving/verifying artifacts into `zkp-node` and swap its backend while preserving `/prove` and `/verify`. |
| **Solidity compiler** | Truffle 5.11 expects `solc` `^0.8.x`. The `Dockerfile.blockchain` uses Truffle's bundled solc. If contracts target a different version, edit `truffle-config.js`. |
| **GPU nodes** | CNN training on EMNIST is CPU-feasible but slow. For real runs, add a GPU node pool: `az aks nodepool add -g $RG --cluster-name $AKS_NAME -n gpupool -s Standard_NC6s_v3 -c 1` and add a `nodeSelector` to the client manifest. |
| **Persistent block data** | Geth PoA data lives in a `PVC`. Deleting the StatefulSet doesn't drop the PVC, so the chain survives restarts. |
| **Cost** | A 3-node `D4s_v5` cluster is ~$1/hr. Tear down with `az group delete -n fl-rg --yes --no-wait` when done. |

See `TROUBLESHOOTING.md` for how to inspect a running cluster and pull the
PNG charts / logs back to your machine.
