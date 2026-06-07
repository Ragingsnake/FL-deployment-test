# System Guide: Federated Learning, ZKP, IPFS, Blockchain, and Cloud Deployment

This guide explains what the system does, how the pieces fit together, how to operate it on cloud infrastructure, and how to interpret the results. It is written for the current repository layout and Kubernetes deployment in this workspace.

## 1. What This System Offers

This project is a cloud-deployed federated learning system with supporting verification, storage, and audit layers:

| Capability | What it gives you |
|------------|-------------------|
| Federated learning | Multiple clients train locally on IID or non-IID EMNIST splits without centralizing raw training data. |
| Secure aggregation policy | The server verifies update proofs, evaluates client quality, weights accepted updates, and applies FedAdam. |
| ZKP node | A dedicated proof service receives `/prove` and `/verify` requests. It is the boundary where actual zkSNARK proving can be plugged in later. |
| IPFS storage | Client model files are uploaded to IPFS and referenced by CID instead of being stored directly on-chain. |
| Blockchain audit trail | A private Ethereum PoA chain records update metadata, proof hashes, verification outcomes, and contract-level reputation counters. |
| Reputation and defense | The server scores clients from similarity, weight delta, local accuracy, local loss, and rejection status. |
| Charts and histories | The server writes mode-specific history JSON files and automatically generates plots after training. |
| Demo controls | You can demonstrate poisoned/faulty clients and invalid ZKP proofs with client-side environment variables. |

The high-level shape is:

```text
FL clients train locally
  -> upload model file to IPFS
  -> ask ZKP node to prove update statement
  -> send model parameters + CID + proof to FL server
  -> server asks ZKP node to verify proof
  -> server records verification on blockchain
  -> server scores/reweights clients
  -> server aggregates accepted updates
  -> server writes history and charts
```

## 2. Cloud Infrastructure

The deployment targets Azure Kubernetes Service. The scripts create or use:

| Cloud resource | Purpose |
|----------------|---------|
| Azure Resource Group | Container for AKS, ACR, disks, and related resources. |
| Azure Container Registry | Stores `fl-server`, `fl-client`, `fl-blockchain`, and `fl-zkp-node` images. |
| AKS cluster | Runs the four namespaces and their workloads. |
| Azure managed disks / PVCs | Persist IPFS data, geth chain data, server histories, and generated plots. |
| Kubernetes ConfigMaps | Share the deployed smart contract address with server and clients. |

The default deploy scripts are:

| Script | Best use |
|--------|----------|
| `deployment/scripts/deploy.sh` | Fresh clone/build/deploy from configured repo URL. |
| `deployment/scripts/deploy_using_existing.sh` | Deploy from the local `Project_NT114` checkout. This is the safest script for your current workflow. |
| `deployment/scripts/deploy_using_local_images.sh` | Use existing cached/local/Docker Hub images and deploy manifests. |
| `deployment/scripts/build_and_push_dockerhub.sh` | Build all four images and push to Docker Hub. |
| `deployment/scripts/pull-outputs.sh` | Copy generated charts and history JSON files from the server pod. |

The Kubernetes namespaces are:

| Namespace | Workloads |
|-----------|-----------|
| `fl-clients` | `fl-client` StatefulSet, one pod per client. |
| `aggregation` | `fl-server` Deployment, server history PVC, plot/output PVC. |
| `ipfs` | Single Kubo IPFS StatefulSet and PVC. |
| `blockchain` | Geth StatefulSet, Truffle migration Job, ZKP node Deployment. |

Code and manifest references:

- Namespaces: `deployment/k8s/00-namespaces.yaml`
- IPFS: `deployment/k8s/10-ipfs.yaml`
- Geth, migration Job, ZKP node: `deployment/k8s/20-blockchain.yaml`
- FL server: `deployment/k8s/30-server.yaml`
- FL clients: `deployment/k8s/40-clients.yaml`
- Dockerfiles: `deployment/docker/`

## 3. Federated Learning

Federated learning trains a shared model by sending model updates instead of raw data. Each client owns its local dataset, trains locally, and returns updated parameters to the server.

In this system:

1. The server starts a Flower training round.
2. Each client receives the current global model.
3. Each client trains locally using its local EMNIST split.
4. Each client returns updated parameters and metrics.
5. The server verifies, scores, and aggregates accepted updates.

Code path:

| Step | Code |
|------|------|
| Server entrypoint | `Project_NT114/fl_server.py` |
| Server strategy | `Project_NT114/FL_Server/strategy.py` |
| Client entrypoint | `Project_NT114/fl_client.py` |
| Flower client implementation | `Project_NT114/FL_Client/Flower.py` |
| Local training | `Project_NT114/FL_Client/train.py` |
| Local evaluation | `Project_NT114/FL_Client/evaluate.py` |
| Model architecture | `Project_NT114/model.py` |
| Dataset loading | `Project_NT114/utils.py` |

The client model is a lightweight CNN in `model.py`. Local training uses:

- Adam optimizer.
- FedProx regularization.
- `LOCAL_EPOCHS`, default `2`.
- `CLIENT_LR`, default `0.0005`.
- `FEDPROX_MU`, default `0.001`.
- `FEDPROX_EVERY_N_BATCHES`, default `5`.

The server uses FedAdam in:

- `Project_NT114/FL_Server/fedadam.py`
- `Project_NT114/FL_Server/config.py`

## 4. IID vs Non-IID Modes

The system supports both IID and non-IID data splits.

| Mode | Meaning |
|------|---------|
| IID | Each client sees a more similar data distribution. Training tends to be smoother. |
| non-IID | Clients see different/skewed distributions. This is more realistic and usually harder. |

The mode is controlled by `SPLIT_TYPE`:

```bash
SPLIT_TYPE=non_iid FL_ROUNDS=40 bash deployment/scripts/deploy_using_existing.sh
SPLIT_TYPE=iid FL_ROUNDS=40 bash deployment/scripts/deploy_using_existing.sh
```

Data is loaded from:

```text
Project_NT114/data_new/iid/client_0.pkl
Project_NT114/data_new/non_iid/client_0.pkl
...
```

Code path:

- `Project_NT114/fl_client.py` receives `<client_id> <iid|non_iid>`.
- `Project_NT114/FL_Client/Flower.py` passes the split type to `load_client_data`.
- `Project_NT114/utils.py` loads `data_new/<split_type>/client_<id>.pkl`.

## 5. ZKP: What It Is and What This System Does

ZKP means zero-knowledge proof. A ZKP lets one party prove a statement is valid without revealing private information beyond the statement itself.

In theory, a training-update ZKP could prove something like:

```text
I produced this model update by running the agreed training computation
over private local data, and the public hash/CID/round metadata matches.
```

That full statement is expensive and normally requires an actual zkSNARK circuit.

### Current implementation

The current system uses a dedicated ZKP node and a Schnorr-style non-interactive proof backend. This is a real proof boundary, but it is not yet a full Groth16/Plonk zkSNARK training circuit.

The important design win is that the FL code now talks to a service:

```text
POST /prove
POST /verify
```

Later, the internals of `zkp-node` can be replaced with actual zkSNARK artifacts while keeping the same client/server API.

Code path:

| Action | Code |
|--------|------|
| Client builds proof statement | `Project_NT114/zkp_utils.py::build_statement` |
| Client requests proof | `Project_NT114/zkp_utils.py::generate_proof` |
| ZKP service `/prove` | `Project_NT114/zkp_node.py` |
| Server verifies proof | `Project_NT114/zkp_utils.py::verify_proof` |
| ZKP service `/verify` | `Project_NT114/zkp_node.py` |

The public statement includes:

| Field | Meaning |
|-------|---------|
| `model_hash` | Hash of submitted model parameters. |
| `client_id` | Client identity. |
| `round` | FL round number. |
| `cid` | IPFS CID for the saved model file. |

The server must send the current round to clients. That happens in:

```text
Project_NT114/FL_Server/strategy.py::configure_fit
```

Without this, clients may prove `round=1` repeatedly, causing valid-looking round-1 proofs to fail from round 2 onward.

### Where actual zkSNARKs would plug in

The clean plug-in point is:

```text
Project_NT114/zkp_node.py
```

To move to Groth16/Plonk, mount or bake circuit artifacts into the ZKP node image:

- R1CS
- WASM witness generator
- proving key / `.zkey`
- verification key

Then replace the internals of `/prove` and `/verify`, while preserving the same JSON API used by `zkp_utils.py`.

## 6. IPFS: What It Is and How We Use It

IPFS is content-addressed storage. Instead of identifying a file by location, it identifies the file by content hash. That hash-like address is called a CID.

In this system:

1. A client saves its local model file, such as `models/clients/client2_round4.pth`.
2. The client uploads that file to IPFS.
3. IPFS returns a CID.
4. The client includes that CID in its ZKP statement and blockchain submission.

Code path:

- `Project_NT114/FL_Client/Flower.py` saves the model file.
- `Project_NT114/ipfs_utils.py::upload_to_ipfs` uploads it.
- `deployment/k8s/10-ipfs.yaml` runs Kubo.

Important detail: if IPFS upload fails, `ipfs_utils.py` returns a fallback local hash CID:

```text
local-<sha256>
```

That keeps training alive for development, but in a strict production demo you should treat repeated IPFS fallback CIDs as an infrastructure problem.

## 7. Blockchain: What It Is and How We Use It

Blockchain gives the system an append-only audit trail. This project uses a private Ethereum Proof-of-Authority geth node, not a public chain.

The blockchain does not store full model parameters. It stores metadata:

- Round number.
- Client ID.
- IPFS CID.
- Proof hash.
- Accuracy scaled as an integer.
- Verification status.

Code path:

| Action | Code |
|--------|------|
| Geth image | `deployment/docker/Dockerfile.blockchain` |
| Geth startup | `deployment/docker/geth-entrypoint.sh` |
| Contract migration | `deployment/k8s/20-blockchain.yaml` |
| Smart contract | `Project_NT114/contracts/Reputation.sol` |
| Python Web3 wrapper | `Project_NT114/blockchain.py` |
| Client submits update metadata | `blockchain.py::submit_update` |
| Server records verification result | `blockchain.py::verify_update` |

The migration Job deploys the contract, reads the deployed address, and creates the `contract-address` ConfigMap in:

- `aggregation`
- `fl-clients`

The server and clients read `REPUTATION_ADDRESS` from that ConfigMap.

## 8. End-to-End Round Workflow

This is the core training loop.

1. `fl_server.py` starts Flower with `SecureFLStrategy`.
2. `SecureFLStrategy.configure_fit` sends `server_round` to clients.
3. Each `fl_client.py` pod starts a `FlowerClient`.
4. `FlowerClient.fit` loads global parameters into the CNN.
5. `train.py` trains locally using FedProx.
6. The client saves the model state to `models/clients/client<id>_round<round>.pth`.
7. The client uploads the model file to IPFS and receives a CID.
8. The client gets current model parameters and builds a public proof statement.
9. `zkp_utils.generate_proof` calls `zkp-node /prove`.
10. The client submits metadata to the blockchain using `submit_update`.
11. The client returns parameters, CID, proof, local accuracy, local loss, and train time to the server.
12. `SecureFLStrategy.aggregate_fit` receives all client updates.
13. The server calls `zkp_utils.verify_proof`, which calls `zkp-node /verify`.
14. If ZKP verification fails, the server rejects the update and records failure on-chain.
15. If ZKP verification passes, the server records success on-chain and evaluates the client.
16. `reputation.py::evaluate_clients` computes delta, cosine similarity, normalized accuracy, normalized loss, score, and reputation.
17. The server filters very poor clients and applies IQR outlier checks.
18. The server computes weighted gradients and applies FedAdam.
19. `aggregate_evaluate` averages evaluation results and writes history JSON.
20. After training, `fl_server.py` runs `plot_results.py` and keeps the pod alive for output retrieval.

## 9. Reputation: Why Normal Clients Can Look Low

This is a good question, and the answer is less moral than the word "reputation" makes it sound. In this system, reputation is not "is this client honest?" It is closer to "how useful and consistent did this client's update look relative to the current global model and other clients?"

The main reputation calculation is in:

```text
Project_NT114/reputation.py
```

The scoring formula combines:

```text
0.4 * cosine similarity
+ 0.3 * delta score
+ 0.3 * normalized local accuracy
- 0.2 * normalized local loss
```

Then it updates reputation with:

```text
new_rep = old_rep + 0.3 * (score - old_rep)
new_rep = clip(new_rep, 0.1, 1.0)
```

Reasons a normal client can have low reputation:

| Reason | Explanation |
|--------|-------------|
| Non-IID data | A client may train honestly but on a skewed label distribution. Its update can point away from the global direction. |
| Relative scoring | Local accuracy/loss are normalized against other clients in the same round. Someone can be "normal" but still weakest in that round. |
| Early global model instability | Early rounds have a weak global model, so deltas and similarities can be noisy. |
| Outlier detection is statistical | IQR checks compare clients against each other. A legitimate non-IID client can look like an outlier. |
| Reputation starts at 0.5 | The update rule is conservative. A few mediocre scores can pull reputation down quickly. |
| Blockchain reputation is separate | The Solidity contract increments/decrements an integer verification count. The plotted server reputation is the Python-side quality score, not exactly the contract counter. |
| ZKP only proves statement consistency | A valid proof does not mean the update is useful. It means the proof matches the submitted parameters/metadata. |

So low reputation does not automatically mean the client cheated. It can mean:

- the client has difficult/skewed data,
- the local update is less aligned,
- the client has high local loss,
- the client is statistically unusual compared with peers,
- or the system is early in training.

For demos, explain it like this:

```text
ZKP answers: did the submitted update match its proof statement?
Reputation answers: was the accepted update useful and consistent?
Blockchain answers: what was submitted and what did the server decide?
```

Those are related, but not the same.

## 10. Defense and Aggregation

After proof verification, the server evaluates accepted clients.

Key files:

- `Project_NT114/FL_Server/strategy.py`
- `Project_NT114/reputation.py`
- `Project_NT114/FL_Server/defense.py`
- `Project_NT114/FL_Server/fedadam.py`

The server computes:

| Metric | Meaning |
|--------|---------|
| Delta | Relative L2 distance between local and global weights. |
| Cosine similarity | Directional alignment between local and global weights. |
| Local accuracy | Client-side training/evaluation signal. |
| Local loss | Client-side loss signal. |
| IQR bounds | Statistical outlier range for client deltas. |
| Reward | Aggregation weight based on reputation and delta. |

Accepted clients produce gradients:

```text
local_weight - global_weight
```

The server computes a reputation-weighted gradient average, clips it, then applies FedAdam.

## 11. Demo Cases

The demo controls are client-side. This is intentional: malicious behavior should be controlled by the client pod, not by the server. The server only sends `server_round` so the client can create round-correct proofs.

### Demo A: Faulty Client / Poisoned Update

Goal: client sends corrupted parameters but a valid proof over those corrupted parameters.

Expected outcome:

- ZKP passes.
- Blockchain verification can still be true.
- Defense/reputation should notice poor delta/score and reduce influence or penalize the client.

Client-side env vars:

```bash
DEMO_FAULTY_CLIENTS=2
DEMO_FAULTY_START_ROUND=2
DEMO_FAULTY_END_ROUND=4
DEMO_FAULTY_NOISE_SCALE=0.25
```

Code path:

- `Project_NT114/FL_Client/Flower.py::_demo_enabled`
- `Project_NT114/FL_Client/faulty.py::corrupt_parameters`

### Demo B: Invalid ZKP Proof

Goal: client trains normally, then tampers with the proof before submitting.

Expected outcome:

- Server logs `ZKP FAILED for Client X`.
- Update is excluded from aggregation.
- Verification failure is recorded on-chain.
- Client appears in `penalty_clients` history.

Client-side env vars:

```bash
DEMO_BAD_ZKP_CLIENTS=3
DEMO_BAD_ZKP_START_ROUND=2
DEMO_BAD_ZKP_END_ROUND=4
```

Code path:

- `Project_NT114/FL_Client/Flower.py::_tamper_proof`
- `Project_NT114/FL_Server/strategy.py::aggregate_fit`

For exact commands, see `deployment/TROUBLESHOOTING.md`.

## 12. Histories, Charts, and Outputs

The server writes histories to:

```text
/app/history/server_history_fedadam_iid.json
/app/history/server_history_fedadam_non_iid.json
```

The server writes plots to:

```text
/app/picture/log_full/iid/
/app/picture/log_full/non_iid/
```

Generated charts include:

- Training time per client.
- Local accuracy.
- Global loss and client loss comparison.
- Global accuracy and client accuracy comparison.
- Rejected update rate.
- Global model performance.
- Client reputation evolution.
- Convergence speed.

Relevant code:

- `Project_NT114/fl_server.py`
- `Project_NT114/plot_results.py`
- `deployment/scripts/pull-outputs.sh`

Pull results:

```bash
bash deployment/scripts/pull-outputs.sh ./fl-outputs
```

## 13. Common Commands

Check pods:

```bash
kubectl get pods -A -o wide
```

Watch server logs:

```bash
kubectl -n aggregation logs -f deploy/fl-server
```

Watch a client:

```bash
kubectl -n fl-clients logs -f fl-client-0
```

Check ZKP node:

```bash
kubectl -n blockchain run zkp-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://zkp-node-svc:8090/healthz
```

Check geth RPC:

```bash
kubectl -n blockchain run rpc-probe --rm -it --image=curlimages/curl --restart=Never -- \
  curl -s http://geth-svc:8545 -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```

Pull outputs:

```bash
bash deployment/scripts/pull-outputs.sh ./fl-outputs
```

## 14. Image and Build Workflow

The system builds four images:

| Image | Dockerfile |
|-------|------------|
| `fl-server` | `deployment/docker/Dockerfile.server` |
| `fl-client` | `deployment/docker/Dockerfile.client` |
| `fl-blockchain` | `deployment/docker/Dockerfile.blockchain` |
| `fl-zkp-node` | `deployment/docker/Dockerfile.zkp` |

Docker Hub build script:

```bash
bash deployment/scripts/build_and_push_dockerhub.sh <dockerhub-user-or-org> <tag> linux/amd64
```

GitHub Actions workflow:

```text
.github/workflows/dockerhub-project-nt114.yml
```

It detects changes under `Project_NT114/**`, computes the next `verN` tag, builds images, pushes to Docker Hub, and pushes the Git tag.

## 15. Important Limitations and Honest Notes

| Area | Current state |
|------|---------------|
| ZKP | The deployed boundary is ZKP-node based, but the backend is currently Schnorr-style NIZK, not a full training zkSNARK. |
| Privacy | Raw data is not sent to the server, but model updates can still leak information in real FL threat models. |
| Blockchain trust | The private PoA chain is useful for auditability inside the experiment, not equivalent to public-chain decentralization. |
| Reputation | A low reputation can reflect non-IID difficulty, not maliciousness. |
| IPFS fallback | If IPFS fails, the code can return a local hash CID. Treat repeated fallback CIDs as a deployment issue. |
| Smart contract reputation | Contract reputation is an integer verification counter; plotted reputation is Python quality scoring. |

## 16. Mental Model for Presenting the System

If you need to explain the system cleanly, use this:

```text
Federated learning keeps data local.
IPFS stores model artifacts by content address.
ZKP checks that an update matches its public proof statement.
Blockchain records the audit trail.
Reputation estimates whether verified updates are useful.
FedAdam combines useful verified updates into the global model.
```

That separation matters. A client can be:

- ZKP-valid but low-quality.
- ZKP-invalid and rejected immediately.
- Honest but low-reputation because its non-IID data makes its update look unusual.
- High-performing locally but less useful globally.

This is not a bug in the story. It is the point of having multiple layers instead of one giant "trust" switch.
