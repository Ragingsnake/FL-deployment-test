# System Guide: Federated Learning, ZKP, IPFS, Blockchain, and Cloud Deployment

This guide explains what the system does, how the pieces fit together, how to operate it on cloud infrastructure, and how to interpret the results. It is written for the current repository layout and Kubernetes deployment in this workspace.

---

## 1. What This System Offers

This project is a cloud-deployed federated learning system with supporting verification, storage, defense, and audit layers:

| Capability | What it gives you |
|------------|-------------------|
| Federated learning | Multiple clients train locally on IID or non-IID EMNIST splits without centralizing raw training data. |
| Secure aggregation policy | The server verifies update proofs, evaluates client quality, weights accepted updates, and applies FedAdam. |
| ZKP node | A dedicated proof service receives `/prove` and `/verify` requests. Uses Groth16 zkSNARK with a gradient norm bound circuit. |
| On-chain ZKP verification | Proofs can be verified directly on the Ethereum smart contract (trustless, no server bias). |
| IPFS storage | Client model files are uploaded to IPFS and referenced by CID instead of being stored directly on-chain. |
| Blockchain audit trail | A private Ethereum PoA chain records update metadata, proof hashes, verification outcomes, and reputation counters. |
| Staking & slashing | Clients stake ETH to participate; consecutive failures trigger stake slashing. Rewards are distributed based on contribution. |
| Reputation and defense | The server scores clients from similarity, weight delta, local accuracy, local loss, and rejection status. |
| Byzantine-resilient aggregation | Pluggable aggregators: Multi-Krum, Trimmed Mean, Bulyan, RFA (geometric median), alongside the default reputation-weighted method. |
| Advanced attack framework | Backdoor, free-rider, Sybil, collusion, and sign-flip attacks for benchmarking defenses. |
| Secure aggregation | Additive masking hides individual client updates from the server while preserving aggregate correctness. |
| Training verification | Cryptographic commitments prove clients actually trained (loss decreased) to detect free-riders. |
| Charts and histories | The server writes mode-specific history JSON files and automatically generates plots after training. |

The high-level shape is:

```text
FL clients train locally
  -> compute training commitment (loss before/after)
  -> upload model file to IPFS
  -> ask ZKP node to prove gradient norm bound
  -> (optional) mask update with secure aggregation
  -> send model parameters + CID + proof + commitment to FL server
  -> server verifies ZKP proof (off-chain via node, OR on-chain via contract)
  -> server records verification on blockchain
  -> server scores/reweights clients (reputation)
  -> server aggregates using selected method (reputation-weighted / Krum / Trimmed Mean / Bulyan / RFA)
  -> server applies FedAdam to update global model
  -> (optional) server distributes staking rewards
  -> server writes history and charts
```

---

## 2. Cloud Infrastructure

The deployment targets Azure Kubernetes Service. The scripts create or use:

| Cloud resource | Purpose |
|----------------|---------|
| Azure Resource Group | Container for AKS, ACR, disks, and related resources. |
| Azure Container Registry | Stores `fl-server`, `fl-client`, `fl-blockchain`, and `fl-zkp-node` images. |
| AKS cluster | Runs the four namespaces and their workloads. |
| Azure managed disks / PVCs | Persist IPFS data, geth chain data, server histories, and generated plots. |
| Kubernetes ConfigMaps | Share the deployed smart contract address with server and clients. |

The Kubernetes namespaces are:

| Namespace | Workloads |
|-----------|-----------|
| `fl-clients` | `fl-client` StatefulSet, one pod per client. |
| `aggregation` | `fl-server` Deployment, server history PVC, plot/output PVC. |
| `ipfs` | Single Kubo IPFS StatefulSet and PVC. |
| `blockchain` | Geth StatefulSet, Truffle migration Job, ZKP node Deployment. |

---

## 3. Complete Environment Variable Reference

### Server-Side Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FL_ROUNDS` | `40` | Number of federated learning rounds. |
| `NUM_CLIENTS` | `5` | Number of FL clients. |
| `SPLIT_TYPE` | `non_iid` | Data split type: `iid` or `non_iid`. |
| `FL_STRATEGY` | `secure` | Strategy: `secure` (SecureFLStrategy) or `fedavg` (SimpleFLStrategy). |
| `AGGREGATION_METHOD` | `reputation` | Aggregation algorithm: `reputation`, `krum`, `trimmed_mean`, `bulyan`, `rfa`. |
| `NUM_BYZANTINE` | `1` | Assumed number of Byzantine clients (for Krum/Bulyan). |
| `TRIM_RATIO` | `0.1` | Fraction to trim in Trimmed Mean aggregator. |
| `RFA_CLIP_NORM` | `1.0` | Per-update norm clip for RFA. |
| `VERIFICATION_MODE` | `off-chain` | ZKP verification: `off-chain` (via ZKP node) or `on-chain` (via smart contract). |
| `STAKING_ENABLED` | `0` | Enable staking/slashing contract: `0` or `1`. |
| `SECURE_AGG_ENABLED` | `0` | Enable secure aggregation masking: `0` or `1`. |
| `TRAINING_VERIFICATION_ENABLED` | `0` | Enable training correctness commitments: `0` or `1`. |
| `FEDADAM_LR` | `0.0007` | FedAdam server learning rate. |
| `ETH_RPC` | `http://127.0.0.1:7545` | Ethereum RPC endpoint. |
| `REPUTATION_ADDRESS` | *(from ConfigMap)* | Deployed Reputation contract address. |
| `STAKING_ADDRESS` | *(from ConfigMap)* | Deployed StakingReputation contract address. |

### Client-Side Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FL_SERVER_HOST` | `localhost` | FL server hostname. |
| `FL_SERVER_PORT` | `8080` | FL server port. |
| `CLIENT_LR` | `0.0005` | Local Adam learning rate. |
| `LOCAL_EPOCHS` | `2` | Local training epochs per round. |
| `FEDPROX_MU` | `0.001` | FedProx regularization strength. |
| `IPFS_API` | `/ip4/127.0.0.1/tcp/5001` | IPFS API multiaddr. |
| `ZKP_NODE_URL` | *(empty)* | URL of the ZKP node service. |

### Demo Attack Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEMO_FAULTY_CLIENTS` | *(empty)* | Comma-separated client IDs for noise injection. |
| `DEMO_FAULTY_NOISE_SCALE` | `0.01` | Noise magnitude for faulty attack. |
| `DEMO_BAD_ZKP_CLIENTS` | *(empty)* | Comma-separated client IDs for ZKP tampering. |
| `DEMO_ATTACK_TYPE` | *(empty)* | Advanced attack: `backdoor`, `freerider`, `sybil`, `collusion`, `signflip`. |
| `DEMO_ATTACK_CLIENTS` | *(empty)* | Comma-separated client IDs for advanced attacks. |
| `DEMO_ATTACK_START_ROUND` | `1` | First round to activate the attack. |
| `DEMO_ATTACK_END_ROUND` | `999999` | Last round to activate the attack. |
| `DEMO_ATTACK_SCALE` | *(varies)* | Attack intensity (meaning varies per attack type). |

---

## 4. Federated Learning

Federated learning trains a shared model by sending model updates instead of raw data. Each client owns its local dataset, trains locally, and returns updated parameters to the server.

In this system:

1. The server starts a Flower training round.
2. Each client receives the current global model.
3. Each client trains locally using its local EMNIST split (with FedProx regularization).
4. Each client returns updated parameters and metrics.
5. The server verifies, scores, and aggregates accepted updates.

The client model is a lightweight CNN in `model.py`:
- 2 convolutional layers (32 and 64 filters)
- Max pooling and dropout
- 2 fully connected layers (128 hidden, 62 output for EMNIST ByClass)

Code path:

| Step | Code |
|------|------|
| Server entrypoint | `fl_server.py` |
| Server strategy | `FL_Server/strategy.py` |
| Client entrypoint | `fl_client.py` |
| Flower client | `FL_Client/Flower.py` |
| Local training | `FL_Client/train.py` |
| Local evaluation | `FL_Client/evaluate.py` |
| Model architecture | `model.py` |
| Dataset loading | `utils.py` |

---

## 5. ZKP: Groth16 zkSNARK Gradient Norm Proof

### What it proves

The Circom circuit (`prove_gradient_norm.circom`) proves:

```
"The L2 norm of my gradient update is at most norm_bound,
 and the public metadata (model_hash, client_id, round_num) matches."
```

This prevents gradient explosion/poisoning attacks where a malicious client sends an update with enormous magnitude.

### Public signals (verifiable by anyone)

| Signal | Meaning |
|--------|---------|
| `model_hash` | Hash of submitted model parameters (field element). |
| `client_id` | Client identity. |
| `round_num` | FL round number. |
| `norm_bound` | Maximum allowed gradient norm (scaled integer). |

### Private witness (known only to the client)

| Input | Meaning |
|-------|---------|
| `gradient[128]` | First 128 gradient values (quantized, scaled). |

### Verification modes

| Mode | How it works |
|------|-------------|
| `off-chain` (default) | Client calls `zkp-node /prove`, server calls `zkp-node /verify`. Fast but requires trusting the server. |
| `on-chain` | Proof is submitted to `Reputation.verifyUpdateProof()` or `StakingReputation.verifyUpdateWithProof()`. The EVM verifies using elliptic curve pairing precompiles. Trustless. |

Set `VERIFICATION_MODE=on-chain` to enable trustless verification.

---

## 6. Byzantine Attack Framework

### Available attacks

| Attack | Env `DEMO_ATTACK_TYPE` | Description |
|--------|----------------------|-------------|
| **Backdoor** | `backdoor` | Modifies last FC layer to misclassify source_label as target_label. Stays within norm bounds. |
| **Free-rider** | `freerider` | Returns global model + tiny noise. Contributes nothing but receives aggregated model. |
| **Sybil** | `sybil` | Coordinated drift toward a cached random direction. Cumulative effect across multiple clients. |
| **Collusion** | `collusion` | Shifts updates within IQR bounds toward an adversarial direction. Hard to detect individually. |
| **Sign-flip** | `signflip` | Negates parameters, pushing model away from convergence. |
| **Noise (legacy)** | *(use `DEMO_FAULTY_CLIENTS`)* | Adds Gaussian noise to parameters. |
| **Bad ZKP (legacy)** | *(use `DEMO_BAD_ZKP_CLIENTS`)* | Tampers with ZKP proof to trigger rejection. |

### Example: Run backdoor attack on clients 2,3 during rounds 5-15

```bash
DEMO_ATTACK_TYPE=backdoor \
DEMO_ATTACK_CLIENTS=2,3 \
DEMO_ATTACK_START_ROUND=5 \
DEMO_ATTACK_END_ROUND=15 \
DEMO_ATTACK_SCALE=0.15 \
bash deployment/scripts/deploy_using_existing.sh
```

---

## 7. Byzantine-Resilient Aggregation

### Available aggregators

| Method | Env `AGGREGATION_METHOD` | Reference |
|--------|------------------------|-----------|
| **Reputation-weighted** (default) | `reputation` | Custom: cosine similarity + delta + accuracy scoring with FedAdam. |
| **Multi-Krum** | `krum` | Blanchard et al., NeurIPS 2017. Selects updates closest to neighbors. |
| **Trimmed Mean** | `trimmed_mean` | Yin et al., ICML 2018. Coordinate-wise sorting and trimming. |
| **Bulyan** | `bulyan` | El Mhamdi et al., ICML 2018. Iterative Krum + trimmed mean. |
| **RFA (Geometric Median)** | `rfa` | Pillutla et al., IEEE TPAMI 2022. Weiszfeld's algorithm. |

### Example: Compare Krum vs default

```bash
# Run with Krum
AGGREGATION_METHOD=krum NUM_BYZANTINE=1 \
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
bash deployment/scripts/deploy_using_existing.sh

# Run with default reputation-weighted
AGGREGATION_METHOD=reputation \
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
bash deployment/scripts/deploy_using_existing.sh
```

---

## 8. Staking & Slashing (Game-Theoretic Incentive)

### Smart contract: `StakingReputation.sol`

| Feature | Detail |
|---------|--------|
| **Registration** | Clients call `registerClient()` with `>= 0.01 ETH` stake. |
| **Reputation** | Starts at 100, incremented by 10 on success, decremented by 20 on failure. Max 200. |
| **Slashing** | After 3 consecutive verification failures, 30% of stake is slashed. |
| **Rewards** | Aggregator distributes rewards proportional to reputation (Shapley-value proxy). |
| **Withdrawal** | Clients can withdraw stake if reputation >= 50. Rewards are always withdrawable. |

### Enable staking

```bash
STAKING_ENABLED=1 \
STAKING_ADDRESS=<deployed_address> \
bash deployment/scripts/deploy_using_existing.sh
```

---

## 9. Secure Aggregation

When `SECURE_AGG_ENABLED=1`:

1. Each client generates pairwise additive masks with all peers.
2. Masks are designed to cancel when summed: `mask_i(j) = -mask_j(i)`.
3. Client sends `params + mask` to the server.
4. Server sums all masked updates → masks cancel → true aggregate recovered.

The server never sees individual client updates, defending against gradient inversion attacks (Deep Leakage from Gradients).

**Limitation**: Currently uses deterministic shared secrets for the experimental setup. A production deployment would use Diffie-Hellman key exchange.

---

## 10. Training Correctness Verification

When `TRAINING_VERIFICATION_ENABLED=1`:

1. Client evaluates loss on training data **before** training → `loss_before`.
2. Client trains normally → `loss_after`.
3. Client computes a cryptographic commitment binding: global model hash, local model hash, loss_before, loss_after, epochs, learning rate.
4. Server checks the commitment and flags if `loss_after >= loss_before` (possible free-rider).

This detects clients that skip training and return the global model unchanged.

---

## 11. End-to-End Round Workflow (Upgraded)

```text
1. fl_server.py starts Flower with SecureFLStrategy
2. SecureFLStrategy.configure_fit sends server_round to clients
3. Each fl_client.py pod starts a FlowerClient
4. FlowerClient.fit:
   a. Loads global parameters into CNN
   b. (If TRAINING_VERIFICATION) Evaluates loss_before
   c. Trains locally using FedProx
   d. Saves model to models/clients/
   e. Uploads to IPFS → CID
   f. Gets parameters as numpy arrays
   g. (If attack demo) Applies selected attack
   h. Generates Groth16 ZKP proof via zkp-node
   i. (If bad ZKP demo) Tampers proof
   j. Submits metadata to blockchain
   k. (If SECURE_AGG) Masks parameters
   l. (If TRAINING_VERIFICATION) Computes training commitment
   m. Returns params + metrics to server
5. SecureFLStrategy.aggregate_fit:
   a. For each client: verify ZKP (off-chain or on-chain)
   b. Record verification on blockchain
   c. Evaluate client quality (reputation scoring)
   d. Select aggregation method:
      - reputation: weighted gradients + FedAdam
      - krum/trimmed_mean/bulyan/rfa: robust aggregator + FedAdam
   e. Update global model
   f. (If STAKING) Distribute rewards
6. aggregate_evaluate: average eval results, write history JSON
7. After training: generate plots, keep pod alive
```

---

## 12. Reputation Scoring

The reputation system in `reputation.py` computes:

```text
combined_score = 0.4 * cosine_similarity
              + 0.3 * delta_score
              + 0.3 * normalized_accuracy
              - 0.2 * normalized_loss
```

Then updates reputation with EMA:

```text
new_rep = old_rep + 0.12 * (score - old_rep)
new_rep = clip(new_rep, 0.1, 1.0)
```

Low reputation does NOT necessarily mean the client is malicious. It can mean:
- The client has difficult/skewed non-IID data
- The update is less aligned with the global direction
- The client is statistically unusual compared with peers
- The system is in early training rounds

---

## 13. Histories, Charts, and Outputs

The server writes histories to:

```text
/app/history/server_history_fedadam_iid.json
/app/history/server_history_fedadam_non_iid.json
```

The history now also includes:
- `config`: aggregation method, verification mode, staking status
- `aggregation_method`: per-round aggregation method used
- `on_chain_verifications`: count of on-chain verifications per round

Generated charts include:
- Training time per client
- Local accuracy
- Global loss and client loss comparison
- Global accuracy and client accuracy comparison
- Rejected update rate
- Global model performance
- Client reputation evolution
- Convergence speed

Pull results:

```bash
bash deployment/scripts/pull-outputs.sh ./fl-outputs
```

---

## 14. Common Commands

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

---

## 15. Example Experiment Configurations

### Baseline (no attacks, no defenses)
```bash
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
AGGREGATION_METHOD=reputation \
bash deployment/scripts/deploy_using_existing.sh
```

### Backdoor attack with Multi-Krum defense
```bash
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
AGGREGATION_METHOD=krum NUM_BYZANTINE=2 \
DEMO_ATTACK_TYPE=backdoor DEMO_ATTACK_CLIENTS=2,3 \
DEMO_ATTACK_START_ROUND=5 DEMO_ATTACK_END_ROUND=30 \
bash deployment/scripts/deploy_using_existing.sh
```

### On-chain verification with staking
```bash
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
VERIFICATION_MODE=on-chain \
STAKING_ENABLED=1 \
bash deployment/scripts/deploy_using_existing.sh
```

### Full security stack
```bash
SPLIT_TYPE=non_iid FL_ROUNDS=40 \
AGGREGATION_METHOD=bulyan NUM_BYZANTINE=1 \
VERIFICATION_MODE=on-chain \
STAKING_ENABLED=1 \
SECURE_AGG_ENABLED=1 \
TRAINING_VERIFICATION_ENABLED=1 \
bash deployment/scripts/deploy_using_existing.sh
```

---

## 16. New File Reference

| File | Purpose |
|------|---------|
| `FL_Client/attacks.py` | Advanced attack implementations (backdoor, free-rider, Sybil, collusion, sign-flip). |
| `FL_Server/aggregators.py` | Byzantine-resilient aggregation (Multi-Krum, Trimmed Mean, Bulyan, RFA). |
| `contracts/StakingReputation.sol` | Enhanced smart contract with staking, slashing, on-chain ZKP verification, and rewards. |
| `secure_agg.py` | Additive-masking secure aggregation. |
| `training_verifier.py` | Training correctness verification via cryptographic commitments. |

Modified files:
| File | Changes |
|------|---------|
| `FL_Server/config.py` | Added all new environment variables and defaults. |
| `FL_Server/strategy.py` | Integrated on-chain verification, pluggable aggregators, staking rewards, training verification. |
| `FL_Client/Flower.py` | Integrated advanced attacks, secure aggregation masking, training commitments. |
| `blockchain.py` | Added on-chain Groth16 verification, staking contract support, reward distribution. |
| `fl_server.py` | Print active configuration on startup, strategy selection. |

---

## 17. Important Limitations and Honest Notes

| Area | Current state |
|------|---------------|
| ZKP | Groth16 zkSNARK proving gradient norm bound. Not a full training correctness circuit. |
| Privacy | Secure aggregation hides individual updates but masks are deterministic (simulated DH). |
| Blockchain trust | Private PoA chain — useful for auditability, not equivalent to public-chain decentralization. |
| Reputation | Low reputation can reflect non-IID difficulty, not maliciousness. |
| Staking | Works on private PoA chain with test-ETH. Not real financial incentives. |
| Attacks | Implemented at the parameter level. Real-world attacks may operate at the data or training loop level. |
| Aggregators | Theoretical guarantees require specific assumptions about the number of Byzantine clients. |
| Training verification | Hash-based commitments prove training occurred but not correctness of the specific algorithm. |

---

## 18. Mental Model for Presenting the System

```text
Federated learning keeps data local.
IPFS stores model artifacts by content address.
ZKP proves the gradient update satisfies a norm bound (Groth16 zkSNARK).
On-chain verification eliminates server trust for ZKP checks.
Staking makes attacks financially costly.
Reputation estimates whether verified updates are useful.
Byzantine-resilient aggregators (Krum/Bulyan/RFA) resist coordinated poisoning.
Secure aggregation hides individual updates from the server.
Training verification detects free-riders who skip training.
FedAdam combines useful verified updates into the global model.
Blockchain records the audit trail.
```

That separation matters. A client can be:

- ZKP-valid but low-quality.
- ZKP-invalid and rejected immediately.
- Honest but low-reputation because its non-IID data makes its update look unusual.
- High-performing locally but less useful globally.
- A free-rider caught by training verification.
- A backdoor attacker caught by Krum/Bulyan aggregation.
- A financially-staked attacker whose stake gets slashed after repeated failures.

This is not a bug in the story. It is the point of having multiple layers instead of one giant "trust" switch.
