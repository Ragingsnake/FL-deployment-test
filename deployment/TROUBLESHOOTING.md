# Troubleshooting & operations guide

Everything here assumes you ran `deploy.sh` and your kubeconfig now points at
the AKS cluster (`az aks get-credentials …` did this automatically).

---

## 1. Quick health overview

```bash
# Every namespace, every pod, one screen
kubectl get pods -A -o wide

# Watch them come up live
kubectl get pods -A -w
```

A healthy steady state looks like:

```
NAMESPACE     NAME              READY   STATUS    RESTARTS
aggregation   fl-server-...     1/1     Running   0
blockchain    geth-0            1/1     Running   0
blockchain    zkp-node-...      1/1     Running   0
fl-clients    fl-client-0..4    1/1     Running   0
ipfs          ipfs-0            1/1     Running   0
```

Once a training round finishes, the **clients exit Completed** — that's
correct, FL clients only run for `ROUNDS` rounds.

---

## 2. Are the pods actually doing their job?

### FL Server (aggregator)
```bash
kubectl -n aggregation logs -f deploy/fl-server
```
You should see Flower output like:
```
INFO flwr 2026-05-12 ... :  Starting Flower server, config: num_rounds=40
INFO flwr 2026-05-12 ... :  fit_round 1: strategy sampled 5 clients (out of 5)
INFO flwr 2026-05-12 ... :  aggregate_fit: received 5 results and 0 failures
```

### FL Clients
```bash
kubectl -n fl-clients logs -f fl-client-0
```
Expect "Starting Client 0 with non_iid" then per-round local training loss.

### Blockchain
```bash
kubectl -n blockchain logs -f geth-0 | grep -E "Sealing|Imported|Successfully"
# Check the migration Job actually deployed contracts:
kubectl -n blockchain logs job/contract-migrate
kubectl -n aggregation get configmap contract-address -o yaml
```

### ZKP node
```bash
kubectl -n blockchain rollout status deploy/zkp-node
kubectl -n blockchain logs -f deploy/zkp-node
kubectl -n blockchain run zkp-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://zkp-node-svc:8090/healthz
```

The health response should include `{"status":"ok"}` and the active proof
backend. If clients or the server cannot reach it, proof generation or
verification fails closed.

### IPFS
```bash
kubectl -n ipfs logs -f ipfs-0
# Inside-the-cluster API test:
kubectl -n ipfs exec -it ipfs-0 -- ipfs id
kubectl -n ipfs exec -it ipfs-0 -- ipfs repo stat
```

---

## 3. Common failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| **`exec format error` in logs** | **Usually a stale or wrong-arch blockchain image; the repo reuses the `v1` tag, so AKS may keep an old cached image** | **Rebuild the image, then restart the pod; with the manifest fix, the pod will always pull the latest tag** |
| Clients stuck in `Pending` | AKS out of CPU | scale node pool: `az aks scale -g fl-rg -n fl-aks -c 5` |
| `contract-migrate` Job fails | Geth not finished sealing genesis | re-run: `kubectl -n blockchain delete job contract-migrate && kubectl apply -f /tmp/k8s-rendered/20-blockchain.yaml` |
| Client crashloop with `Connection refused` to server | `fl-server` not ready yet; clients retry. Wait for the rollout to finish before applying `40-clients.yaml` (the deploy script already orders this). |
| `IPFS Upload Failed` in client logs | Old `ipfshttpclient` against new Kubo API. Pin Kubo to `v0.28.0` (already done in `10-ipfs.yaml`); confirm with `kubectl -n ipfs exec ipfs-0 -- ipfs version`. |
| Geth pod restarts | PVC corrupted from forced delete | delete the PVC `geth-data` and re-apply (you lose chain state) |
| `ImagePullBackOff` | ACR not attached to AKS | `az aks update -g fl-rg -n fl-aks --attach-acr $ACR_NAME` |
| ZKP verification fails for every client | `zkp-node` unavailable, mismatched proof backend, or stale client/server image | Check `kubectl -n blockchain logs deploy/zkp-node`, confirm `ZKP_NODE_URL` on server/clients, rebuild all four images with the same tag |

---

## 4. Poking the cluster interactively

```bash
# Shell into a client
kubectl -n fl-clients exec -it fl-client-0 -- bash

# Hit the Geth RPC from a debug pod
kubectl -n blockchain run rpc-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://geth-svc:8545 -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'

# Hit the ZKP node health endpoint
kubectl -n blockchain run zkp-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://zkp-node-svc:8090/healthz

# Browse IPFS contents
kubectl -n ipfs exec -it ipfs-0 -- ipfs pin ls --type=recursive
```

---

## 5. Pulling generated output back to your computer

The aggregator writes charts (the PNGs you see in `picture/`) into
`/app/picture` inside the `fl-server` pod, backed by a PVC so they survive
restarts.

Use the helper script (run on Cloudshell, or anywhere `kubectl` is configured):

```bash
bash deployment/scripts/pull-outputs.sh ./fl-outputs
```

Under the hood it just runs:

```bash
POD=$(kubectl -n aggregation get pod -l app=fl-server -o jsonpath='{.items[0].metadata.name}')
kubectl cp aggregation/$POD:/app/picture ./fl-outputs
```

To get them onto your **local machine** from Azure Cloudshell:

```bash
# In Cloudshell:
bash deployment/scripts/pull-outputs.sh ~/fl-outputs
tar czf fl-outputs.tgz -C ~ fl-outputs
# Then click the Cloudshell "Upload/Download files" button (paperclip icon)
# and choose Download → ~/fl-outputs.tgz
```

Alternatively, push to a storage account:

```bash
az storage blob upload-batch -d results -s ~/fl-outputs --account-name <yoursa>
```

---

## 6. Re-running an experiment cleanly

### Run IID after a completed non-IID run

The server keeps `/app/history` and `/app/picture` on PVCs, so the non-IID
history remains available while you run IID.

```bash
# Stop the completed/non-IID client set.
kubectl -n fl-clients delete statefulset fl-client --ignore-not-found
kubectl -n fl-clients wait --for=delete statefulset/fl-client --timeout=5m || true

# Restart the server in IID mode. Keep FL_ROUNDS aligned with the experiment.
kubectl -n aggregation set env deploy/fl-server SPLIT_TYPE=iid FL_ROUNDS=40
kubectl -n aggregation rollout restart deploy/fl-server
kubectl -n aggregation rollout status deploy/fl-server --timeout=5m

# Recreate clients from the last rendered manifest, but with IID mode.
cp /tmp/k8s-rendered/40-clients.yaml /tmp/k8s-rendered/40-clients-iid.yaml
sed -i -E 's/(name: SPLIT_TYPE, value: ")[^"]+(")/\1iid\2/' /tmp/k8s-rendered/40-clients-iid.yaml
kubectl apply -f /tmp/k8s-rendered/40-clients-iid.yaml

# Watch the IID run.
kubectl -n aggregation logs -f deploy/fl-server
```

When IID finishes, the server generates:

- `/app/history/server_history_fedadam_non_iid.json`
- `/app/history/server_history_fedadam_iid.json`
- `/app/picture/log_full/non_iid/*.png`
- `/app/picture/log_full/iid/*.png`
- `/app/picture/comparison/*.png`

Pull all generated histories and charts:

```bash
bash deployment/scripts/pull-outputs.sh ./fl-outputs
```

If you need to manually regenerate the comparison plots inside the server pod:

```bash
kubectl -n aggregation exec deploy/fl-server -- \
  python comparison.py \
    --iid-history history/server_history_fedadam_iid.json \
    --non-iid-history history/server_history_fedadam_non_iid.json \
    --output-dir picture/comparison
```

```bash
# Re-roll clients (keeps server, chain, IPFS state):
kubectl -n fl-clients delete statefulset fl-client
kubectl apply -f /tmp/k8s-rendered/40-clients.yaml

# Full wipe of training artifacts:
kubectl -n aggregation exec deploy/fl-server -- rm -rf /app/picture/*

# Nuke everything (keeps cluster, drops workloads):
kubectl delete ns fl-clients ipfs blockchain aggregation
```

---

## 7. Tearing the whole thing down

```bash
az group delete -n fl-rg --yes --no-wait
```

That removes AKS, ACR, public IPs, disks — everything billed.
