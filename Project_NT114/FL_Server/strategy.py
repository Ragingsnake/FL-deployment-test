import flwr as fl
import numpy as np
import json
import time
import os
import torch

from flwr.common import parameters_to_ndarrays, ndarrays_to_parameters

from blockchain import verify_update
from reputation import evaluate_clients
from zkp_utils import verify_proof
from model import CNN

from FL_Server.config import NUM_CLIENTS, BASE_LAMBDA, MAX_LAMBDA, WARMUP_ROUNDS
from FL_Server.reputation import reputation_manager
from FL_Server.defense import compute_delta
from FL_Server.fedadam import fedadam_update

os.makedirs("history", exist_ok=True)


class SecureFLStrategy(fl.server.strategy.FedAvg):
    def __init__(self):
        super().__init__(
            fraction_fit=1.0,
            min_fit_clients=NUM_CLIENTS,
            min_available_clients=NUM_CLIENTS
        )

        self.start_time = None

        # Initialize from the actual model weights, not from client_0's first upload.
        # Using client_0's params as the baseline caused round-1 deltas and cosine
        # similarities to be measured against a random local model, poisoning all
        # initial reputation scores.
        _model = CNN()
        self.global_weights = [p.detach().cpu().numpy() for p in _model.parameters()]

        self.history = {
            "global": {
                "round": [],
                "accuracy": [],
                "loss": [],
                "verification_time": [],
                "penalty_clients": [],
                "round_time": []
            },
            "clients": {}
        }

    def aggregate_fit(self, server_round, results, failures):
        self.start_time = time.time()
        if not results:
            return None, {}

        clients_info = []
        round_verify_times = []
        penalty_clients = []

        # ===== VERIFY ZKP =====
        for client, fit_res in results:
            metrics = fit_res.metrics
            cid = str(metrics["client_id"])
            params = parameters_to_ndarrays(fit_res.parameters)
            proof = json.loads(metrics.get("proof", "{}"))

            print(f"\nClient {cid} update received")

            start = time.time()
            verified = verify_proof(params, proof)
            round_verify_times.append(time.time() - start)

            if not verified:
                print(f"❌ ZKP FAILED for Client {cid}")
                reputation_manager.update_reputation(cid, -1.0)
                continue

            # Fire blockchain verify — non-blocking, no reputation side-effect
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

        # ===== WARMUP: skip defense for first N rounds =====
        # Gradients are large and noisy during warmup — normal behavior, not attacks.
        # Penalizing here pollutes reputation with meaningless early-round noise.
        if server_round <= WARMUP_ROUNDS:
            print(f"[Warmup Round {server_round}/{WARMUP_ROUNDS}] Skipping reputation/defense")
            gradients = []
            weights_list = []

            for info in clients_info:
                grad = [lw - gw for lw, gw in zip(info["params"], self.global_weights)]
                gradients.append(grad)
                weights_list.append(1.0)  # equal weight during warmup

                self._update_client_history(
                    info["client_id"], server_round, info,
                    rep_val=reputation_manager.get(info["client_id"])
                )

            total_weight = sum(weights_list) + 1e-8
            agg_grad = [
                sum(grad[i] * w for grad, w in zip(gradients, weights_list)) / total_weight
                for i in range(len(gradients[0]))
            ]
            self.global_weights = fedadam_update(self.global_weights, agg_grad)

            if round_verify_times:
                self.history["global"]["verification_time"].append(float(np.mean(round_verify_times)))
                self.history["global"]["penalty_clients"].append([])

            return ndarrays_to_parameters(self.global_weights), {}

        # ===== CLIENT EVALUATION =====
        client_weights_dict = {info["client_id"]: info["params"] for info in clients_info}

        # evaluate_clients now returns (results, mean_delta, std_delta)
        # It handles outlier detection internally via z-score — no second IQR pass here.
        eval_results, mean_delta, std_delta = evaluate_clients(
            self.global_weights,
            client_weights_dict,
            clients_info
        )

        # ===== REWARD + GRADIENT =====
        gradients = []
        final_weights = []
        LAMBDA = min(MAX_LAMBDA, BASE_LAMBDA + server_round * 0.005)

        for info in clients_info:
            cid = info["client_id"]
            res = eval_results[cid]

            reputation = res["reputation"]
            score = res["score"]

            # Skip genuinely bad clients
            if score < -0.4 or reputation < 0.2:
                print(f"🚫 Skip client {cid} (score={score:.3f}, rep={reputation:.3f})")
                penalty_clients.append(cid)
                continue

            # REMOVED: duplicate IQR outlier block that was here.
            # evaluate_clients already applied z-score outlier penalty to the score,
            # which already updated reputation. Adding reputation *= 0.7 here was a
            # second penalty in the same round on the same client — primary cause of
            # the 0.68 → 0.65 accuracy drop after round 13.

            delta = compute_delta(self.global_weights, info["params"])
            gamma = np.exp(-BASE_LAMBDA * delta)
            reward = np.sqrt(reputation) * gamma
            reward = np.clip(reward, 0.05, 1.5)

            grad = [lw - gw for lw, gw in zip(info["params"], self.global_weights)]
            gradients.append(grad)
            final_weights.append(reward)

            print(f"Client {cid} | reputation={reputation:.3f} | reward={reward:.3f}")

            self._update_client_history(cid, server_round, info, reputation)

        if not gradients:
            print("❌ No valid clients for aggregation")
            return None, {}

        # ===== WEIGHTED GRADIENT AGGREGATION =====
        total_weight = sum(final_weights) + 1e-8
        agg_grad = [
            sum(grad[i] * w for grad, w in zip(gradients, final_weights)) / total_weight
            for i in range(len(gradients[0]))
        ]

        # ===== FEDADAM UPDATE =====
        self.global_weights = fedadam_update(self.global_weights, agg_grad)

        # ===== LOGGING =====
        if round_verify_times:
            self.history["global"]["verification_time"].append(float(np.mean(round_verify_times)))
            self.history["global"]["penalty_clients"].append(penalty_clients)

        return ndarrays_to_parameters(self.global_weights), {}

    # ================= EVALUATE =================
    def aggregate_evaluate(self, server_round, results, failures):
        if not results:
            return None, {}

        accuracies = [r.metrics.get("accuracy", 0) for _, r in results]
        losses = [r.loss for _, r in results]

        avg_acc = float(np.mean(accuracies))
        avg_loss = float(np.mean(losses))

        print(f"\n--- Round {server_round} Global Result ---")
        print(f"Average Accuracy: {avg_acc:.4f} | Average Loss: {avg_loss:.4f}")

        self.history["global"]["round"].append(server_round)
        self.history["global"]["accuracy"].append(avg_acc)
        self.history["global"]["loss"].append(avg_loss)

        if self.start_time:
            self.history["global"]["round_time"].append(float(time.time() - self.start_time))

        try:
            with open("history/server_history_fedadam.json", "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=4)
        except Exception as e:
            print(f"❌ Error saving history: {e}")

        return avg_loss, {"accuracy": avg_acc}

    def _update_client_history(self, cid, server_round, info, rep_val):
        cid_str = str(cid)
        if cid_str not in self.history["clients"]:
            self.history["clients"][cid_str] = {
                "round": [], "test_accuracy": [], "test_loss": [],
                "reputation": [], "train_time": []
            }
        h = self.history["clients"][cid_str]
        h["round"].append(server_round)
        h["test_accuracy"].append(info["test_acc"])
        h["test_loss"].append(info["test_loss"])
        h["reputation"].append({"round": server_round, "value": float(rep_val)})
        h["train_time"].append(info["train_time"])