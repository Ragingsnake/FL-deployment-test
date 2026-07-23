import flwr as fl
import numpy as np
import json
import time
import os

from flwr.common import parameters_to_ndarrays, ndarrays_to_parameters

from blockchain import verify_update, verify_update_on_chain, distribute_rewards
from reputation import evaluate_clients, update_reputation
from zkp_utils import verify_proof
from model import CNN

from FL_Server.config import (
    NUM_CLIENTS, BASE_LAMBDA, MAX_LAMBDA,
    AGGREGATION_METHOD, NUM_BYZANTINE, TRIM_RATIO, RFA_CLIP_NORM,
    VERIFICATION_MODE, STAKING_ENABLED, SECURE_AGG_ENABLED,
    TRAINING_VERIFICATION_ENABLED,
)
from FL_Server.defense import compute_delta
from FL_Server.fedadam import fedadam_update

os.makedirs("history", exist_ok=True)
SPLIT_TYPE = os.environ.get("SPLIT_TYPE", "non_iid")
HISTORY_PATH = os.environ.get(
    "HISTORY_PATH",
    f"history/server_history_fedadam_{SPLIT_TYPE}.json",
)


class SecureFLStrategy(fl.server.strategy.FedAvg):
    def __init__(self):
        super().__init__(
            fraction_fit=1.0,
            min_fit_clients=NUM_CLIENTS,
            min_available_clients=NUM_CLIENTS
        )

        self.start_time = None
        self.global_weights = None
        self.history = {
            "global": {
                "round": [], "accuracy": [], "loss": [],
                "verification_time": [], "penalty_clients": [],
                "round_time": [],
                "aggregation_method": [],
                "on_chain_verifications": [],
                "staking_events": [],
            },
            "clients": {},
            "config": {
                "aggregation_method": AGGREGATION_METHOD,
                "verification_mode": VERIFICATION_MODE,
                "staking_enabled": STAKING_ENABLED,
                "secure_agg_enabled": SECURE_AGG_ENABLED,
                "training_verification_enabled": TRAINING_VERIFICATION_ENABLED,
                "num_byzantine": NUM_BYZANTINE,
                "trim_ratio": TRIM_RATIO,
            },
        }

        # Lazy-load the aggregator module
        self._aggregator_fn = None
        if AGGREGATION_METHOD != "reputation":
            try:
                from FL_Server.aggregators import get_aggregator
                self._aggregator_fn = get_aggregator(AGGREGATION_METHOD)
                print(f"🔧 Using aggregation method: {AGGREGATION_METHOD}")
            except Exception as e:
                print(f"⚠ Failed to load aggregator '{AGGREGATION_METHOD}': {e}")
                print("⚠ Falling back to reputation-weighted aggregation")

    def configure_fit(self, server_round, parameters, client_manager):
        fit_config = super().configure_fit(server_round, parameters, client_manager)

        for _, fit_ins in fit_config:
            fit_ins.config["server_round"] = server_round

        return fit_config

    def aggregate_fit(self, server_round, results, failures):
        self.start_time = time.time()
        if not results:
            return None, {}

        clients_info = []
        round_verify_times = []
        penalty_clients = []
        on_chain_count = 0

        # ===== VERIFY ZKP =====
        for client, fit_res in results:
            metrics = fit_res.metrics
            cid = str(metrics["client_id"])
            params = parameters_to_ndarrays(fit_res.parameters)
            try:
                proof = json.loads(metrics.get("proof", "{}"))
            except json.JSONDecodeError:
                proof = {}
            model_cid = metrics.get("cid", "")

            print(f"\nClient {cid} update received")

            # ===== Training verification check =====
            if TRAINING_VERIFICATION_ENABLED:
                commitment_str = metrics.get("training_commitment", "")
                if commitment_str:
                    try:
                        commitment = json.loads(commitment_str)
                        if not commitment.get("loss_decreased", True):
                            print(f"⚠ Client {cid}: loss did not decrease (possible free-rider)")
                    except json.JSONDecodeError:
                        print(f"⚠ Client {cid}: invalid training commitment")

            # ===== ZKP verification =====
            start = time.time()
            try:
                if VERIFICATION_MODE == "on-chain":
                    # On-chain Groth16 verification via smart contract
                    verified, tx_hash = verify_update_on_chain(cid, server_round, proof)
                    on_chain_count += 1
                else:
                    # Off-chain verification via ZKP node
                    verified = verify_proof(params, proof, client_id=cid, round_num=server_round, cid=model_cid)
            except Exception as exc:
                print(f"ZKP verification error for Client {cid}: {exc}")
                verified = False
            round_verify_times.append(time.time() - start)

            if not verified:
                print(f"ZKP FAILED for Client {cid}")
                update_reputation(cid, -1.0)
                if VERIFICATION_MODE != "on-chain":
                    # Off-chain mode: record on blockchain manually
                    verify_update(cid, server_round, False)
                penalty_clients.append(cid)
                continue

            if VERIFICATION_MODE != "on-chain":
                # Off-chain mode: record success on blockchain
                verify_update(cid, server_round, True)

            clients_info.append({
                "params": params,
                "client_id": cid,
                "test_acc": metrics.get("local_accuracy", 0),
                "test_loss": metrics.get("local_loss", 0),
                "train_time": metrics.get("train_time", 0)
            })

        if not clients_info:
            return None, {}

        # ===== INITIALIZE GLOBAL MODEL =====
        if self.global_weights is None:
            print("First round: averaging all client updates for initial global model...")
            all_params = [info["params"] for info in clients_info]
            num_clients = len(all_params)

            averaged_weights = []
            for layer_idx in range(len(all_params[0])):
                layer_avg = np.mean(
                    [params[layer_idx] for params in all_params],
                    axis=0
                )
                averaged_weights.append(layer_avg)

            self.global_weights = averaged_weights
            print(f"Initialized global weights from average of {num_clients} clients")

        # ===== CLIENT EVALUATION =====
        client_weights_dict = {info["client_id"]:
            info["params"] for info in clients_info}

        eval_results, Q1, Q3 = evaluate_clients(
            self.global_weights,
            client_weights_dict,
            clients_info
        )

        # ===== IQR OUTLIER DETECTION =====
        IQR = Q3 - Q1
        lower = Q1 - 1.5 * IQR
        upper = Q3 + 1.5 * IQR

        # ===== AGGREGATION =====
        if self._aggregator_fn is not None:
            # Use alternative Byzantine-resilient aggregator
            new_weights = self._aggregate_with_method(
                clients_info, eval_results, server_round, penalty_clients
            )
        else:
            # Use the existing reputation-weighted + FedAdam pipeline
            new_weights = self._aggregate_reputation_weighted(
                clients_info, eval_results, server_round,
                penalty_clients, lower, upper
            )

        if new_weights is None:
            print("❌ No valid clients for aggregation")
            return None, {}

        self.global_weights = new_weights

        # ===== STAKING: Distribute rewards =====
        if STAKING_ENABLED:
            self._distribute_round_rewards(server_round, clients_info, eval_results)

        # ===== LOGGING =====
        if round_verify_times:
            self.history["global"]["verification_time"].append(float(np.mean(round_verify_times)))
            self.history["global"]["penalty_clients"].append(penalty_clients)
            self.history["global"]["aggregation_method"].append(AGGREGATION_METHOD)
            self.history["global"]["on_chain_verifications"].append(on_chain_count)

        return ndarrays_to_parameters(self.global_weights), {}

    def _aggregate_reputation_weighted(self, clients_info, eval_results,
                                       server_round, penalty_clients, lower, upper):
        """Original reputation-weighted aggregation with FedAdam."""
        gradients = []
        final_weights = []
        LAMBDA = min(MAX_LAMBDA, BASE_LAMBDA + server_round * 0.005)

        for info in clients_info:
            cid = info["client_id"]
            res = eval_results[cid]

            reputation = res["reputation"]
            score = res["score"]

            # ===== SKIP BAD CLIENTS =====
            if score < -0.4 or reputation < 0.2:
                print(f"Skip client {cid} (score={score:.3f}, rep={reputation:.3f})")
                penalty_clients.append(cid)
                continue

            # ===== COMPUTE DELTA =====
            delta = compute_delta(self.global_weights, info["params"])

            # ===== IQR OUTLIER DEFENSE =====
            if delta < lower or delta > upper:
                print(f"Outlier Client {cid} (Δ={delta:.4f})")
                penalty_clients.append(cid)

            # ===== COMPUTE REWARD =====
            gamma = np.exp(-BASE_LAMBDA * delta)
            reward = np.sqrt(reputation) * gamma
            reward = np.clip(reward, 0.05, 1.5)

            # ===== COMPUTE GRADIENT =====
            grad = [
                local_w - global_w
                for local_w, global_w in zip(info["params"], self.global_weights)
            ]

            gradients.append(grad)
            final_weights.append(reward)

            print(f"Client {cid} | reputation={reputation:.3f} | reward={reward:.3f}")

            self._update_client_history(cid, server_round, info, reputation)

        if not gradients:
            return None

        # ===== WEIGHTED GRADIENT AGGREGATION =====
        total_weight = sum(final_weights) + 1e-8
        agg_grad = []

        for layer_idx in range(len(gradients[0])):
            layer_sum = sum(
                grad[layer_idx] * weight
                for grad, weight in zip(gradients, final_weights)
            )
            layer_avg = layer_sum / total_weight
            layer_avg = np.clip(layer_avg, -1, 1)
            agg_grad.append(layer_avg)

        # ===== FEDADAM UPDATE =====
        return fedadam_update(self.global_weights, agg_grad)

    def _aggregate_with_method(self, clients_info, eval_results, server_round,
                               penalty_clients):
        """Aggregate using an alternative Byzantine-resilient method."""
        from FL_Server.aggregators import get_aggregator

        # Collect client updates and their reputation weights
        client_updates = []
        client_weights = []
        valid_clients = []

        for info in clients_info:
            cid = info["client_id"]
            res = eval_results[cid]
            reputation = res["reputation"]

            # Still skip obviously bad clients
            if res["score"] < -0.4 or reputation < 0.2:
                print(f"Skip client {cid} (score={res['score']:.3f}, rep={reputation:.3f})")
                penalty_clients.append(cid)
                continue

            # Compute the gradient (local - global)
            grad = [
                local_w - global_w
                for local_w, global_w in zip(info["params"], self.global_weights)
            ]
            client_updates.append(grad)
            client_weights.append(reputation)
            valid_clients.append(info)

            print(f"Client {cid} | reputation={reputation:.3f} | method={AGGREGATION_METHOD}")
            self._update_client_history(cid, server_round, info, reputation)

        if not client_updates:
            return None

        # Call the selected aggregator
        agg_fn = get_aggregator(AGGREGATION_METHOD)
        kwargs = {
            "num_byzantine": NUM_BYZANTINE,
            "trim_ratio": TRIM_RATIO,
            "clip_norm": RFA_CLIP_NORM,
            "weights": client_weights,
        }

        try:
            agg_grad = agg_fn(client_updates, **kwargs)
        except TypeError:
            # Some aggregators don't accept all kwargs
            agg_grad = agg_fn(client_updates)

        # Clip and apply via FedAdam
        agg_grad = [np.clip(g, -1, 1) for g in agg_grad]
        return fedadam_update(self.global_weights, agg_grad)

    def _distribute_round_rewards(self, server_round, clients_info, eval_results):
        """Distribute staking rewards based on reputation (Shapley-value proxy)."""
        client_ids = []
        reward_shares = []

        for info in clients_info:
            cid = info["client_id"]
            if cid in eval_results:
                rep = eval_results[cid].get("reputation", 0)
                # Scale reputation to reward share (integer, in wei-like units)
                share = max(1, int(rep * 1000))
                client_ids.append(int(cid))
                reward_shares.append(share)

        if client_ids:
            try:
                distribute_rewards(server_round, client_ids, reward_shares)
            except Exception as e:
                print(f"⚠ Reward distribution failed: {e}")

    # ================= EVALUATE =================
    def aggregate_evaluate(self, server_round, results, failures):
        if not results:
            return None, {}

        accuracies = [
            r.metrics.get("accuracy", 0)
            for _, r in results
        ]

        losses = [
            r.loss
            for _, r in results
        ]

        avg_acc = float(np.mean(accuracies))
        avg_loss = float(np.mean(losses))

        print(f"\n--- Round {server_round} Global Result ---")
        print(f"Average Accuracy: {avg_acc:.4f} | Average Loss: {avg_loss:.4f}")

        self.history["global"]["round"].append(server_round)
        self.history["global"]["accuracy"].append(avg_acc)
        self.history["global"]["loss"].append(avg_loss)

        if self.start_time:
            round_duration = time.time() - self.start_time
            self.history["global"]["round_time"].append(float(round_duration))

        try:
            with open(HISTORY_PATH,
                      "w",
                      encoding="utf-8"
            ) as f:
                json.dump(self.history, f, indent=4)

        except Exception as e:
            print(f"❌ Error saving history: {e}")

        return avg_loss, {"accuracy": avg_acc}

    def _update_client_history(self, cid, server_round, info, rep_val):
        cid_str = str(cid)
        if cid_str not in self.history["clients"]:
            self.history["clients"][cid_str] = {"round": [], "test_accuracy": [], "test_loss": [], "reputation": [], "train_time": []}

        h = self.history["clients"][cid_str]
        h["round"].append(server_round)
        h["test_accuracy"].append(info["test_acc"])
        h["test_loss"].append(info["test_loss"])
        h["reputation"].append({"round": server_round, "value": float(rep_val)})
        h["train_time"].append(info["train_time"])
