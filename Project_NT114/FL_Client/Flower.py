import copy
import json
import os

import flwr as fl
import torch
import torch.nn as nn
from model import CNN
from utils import load_client_data
from ipfs_utils import upload_to_ipfs
from zkp_utils import canonical_proof_json, generate_proof, proof_hash
from blockchain import submit_update
from FL_Client.train import train
from FL_Client.evaluate import evaluate
from FL_Client.faulty import corrupt_parameters
from FL_Client.attacks import get_attack_fn

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# ======================== Secure Aggregation ========================
SECURE_AGG_ENABLED = os.environ.get("SECURE_AGG_ENABLED", "0") == "1"
NUM_CLIENTS = int(os.environ.get("NUM_CLIENTS", "5"))

# ======================== Training Verification ========================
TRAINING_VERIFICATION_ENABLED = os.environ.get("TRAINING_VERIFICATION_ENABLED", "0") == "1"


def _parse_client_ids(value):
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {int(v) for v in value}
    value = str(value).strip()
    if not value:
        return set()
    return {int(v.strip()) for v in value.split(",") if v.strip()}


def _tamper_proof(proof):
    bad_proof = copy.deepcopy(proof)

    if "public" in bad_proof and len(bad_proof["public"]) > 0:
        bad_proof["public"][0] = str(
            (int(bad_proof["public"][0]) + 1)
            % 21888242871839275222246405745257275088548364400416034343698204186575808495617
        )

    return bad_proof

def _demo_enabled(client_id, round_num, clients_env, start_env, end_env):
    clients = _parse_client_ids(os.environ.get(clients_env, ""))
    if client_id not in clients:
        return False

    start_round = int(os.environ.get(start_env, "1"))
    end_round = int(os.environ.get(end_env, str(10**9)))
    return start_round <= int(round_num) <= end_round


class FlowerClient(fl.client.NumPyClient):
    def __init__(self, client_id, split_type):
        self.client_id = client_id

        self.model = CNN(num_classes=62).to(DEVICE)  # EMNIST ByClass

        self.trainloader, self.testloader = load_client_data(client_id, split_type)
        self.criterion = nn.CrossEntropyLoss()

    def get_parameters(self, config):
        return [v.detach().cpu().numpy() for v in self.model.state_dict().values()]

    def set_parameters(self, parameters):
        state_dict = {
            k: torch.tensor(v).to(DEVICE)
            for k, v in zip(self.model.state_dict().keys(), parameters)
        }
        try:
            self.model.load_state_dict(state_dict, strict=True)
        except RuntimeError as e:
            print(f"⚠ WARNING: State dict mismatch for client {self.client_id}: {e}")
            self.model.load_state_dict(state_dict, strict=False)

    def fit(self, parameters, config):
        self.set_parameters(parameters)
        round_num = config.get("server_round", 1)

        # ===== Demo: legacy faulty/bad-zkp checks =====
        is_faulty = _demo_enabled(
            self.client_id, round_num,
            "DEMO_FAULTY_CLIENTS", "DEMO_FAULTY_START_ROUND", "DEMO_FAULTY_END_ROUND",
        )
        is_bad_zkp = _demo_enabled(
            self.client_id, round_num,
            "DEMO_BAD_ZKP_CLIENTS", "DEMO_BAD_ZKP_START_ROUND", "DEMO_BAD_ZKP_END_ROUND",
        )

        # ===== Demo: advanced attacks =====
        attack_type = os.environ.get("DEMO_ATTACK_TYPE", "")
        is_attack = False
        if attack_type:
            is_attack = _demo_enabled(
                self.client_id, round_num,
                "DEMO_ATTACK_CLIENTS", "DEMO_ATTACK_START_ROUND", "DEMO_ATTACK_END_ROUND",
            )

        if is_faulty:
            print(f"⚠ Client {self.client_id} is FAULTY")
        if is_bad_zkp:
            print(f"⚠ Client {self.client_id} will send an INVALID ZKP proof")
        if is_attack:
            print(f"⚠ Client {self.client_id} will execute '{attack_type}' attack")

        trainable_names = {name for name, _ in self.model.named_parameters()}
        global_params = {
            name: torch.from_numpy(value).to(DEVICE).detach().clone()
            for name, value in zip(self.model.state_dict().keys(), parameters)
            if name in trainable_names
        }

        # ===== Training verification: compute loss BEFORE training =====
        loss_before = None
        if TRAINING_VERIFICATION_ENABLED:
            pre_eval = evaluate(self.model, self.trainloader, self.criterion)
            loss_before = pre_eval["loss"]

        # ===== Train locally =====
        result = train(self.model, self.trainloader, global_params, self.criterion)
        print(f"[Client {self.client_id}] Acc: {result['accuracy']:.4f} | Loss: {result['loss']:.4f}")

        os.makedirs("models/clients", exist_ok=True)
        model_path = f"models/clients/client{self.client_id}_round{round_num}.pth"
        torch.save(self.model.state_dict(), model_path)

        cid = upload_to_ipfs(model_path)
        params = self.get_parameters({})

        # ===== Apply attacks (order: faulty -> advanced attack) =====
        global_params_np = list(parameters)  # Original global params as numpy
        if is_faulty:
            params = corrupt_parameters(params)
            print("💣 Sent corrupted update (legacy faulty)")

        if is_attack and attack_type:
            try:
                attack_fn = get_attack_fn(attack_type)
                if attack_type == "freerider":
                    params = attack_fn(params, global_params=global_params_np)
                elif attack_type in ("collusion", "sybil"):
                    params = attack_fn(params, global_params=global_params_np) if attack_type == "collusion" else attack_fn(params)
                else:
                    params = attack_fn(params)
                print(f"🎯 Applied '{attack_type}' attack")
            except Exception as e:
                print(f"❌ Attack '{attack_type}' failed: {e}")

        # ===== Generate ZKP proof =====
        proof = generate_proof(params, client_id=self.client_id, round_num=round_num, cid=cid)
        if is_bad_zkp:
            proof = _tamper_proof(proof)
            print("🧪 Sent intentionally invalid ZKP proof")

        proof_str = canonical_proof_json(proof)

        # ===== Submit to blockchain =====
        try:
            tx_hash = submit_update(round_num, self.client_id, cid, proof_hash(proof), result["accuracy"])
            if tx_hash:
                print("TX:", tx_hash)
            else:
                print("TX skipped")
        except Exception as e:
            print("Blockchain error:", e)

        # ===== Secure aggregation: apply mask =====
        if SECURE_AGG_ENABLED:
            try:
                from secure_agg import generate_client_mask, mask_update
                shapes = [p.shape for p in params]
                all_ids = list(range(NUM_CLIENTS))
                mask = generate_client_mask(shapes, self.client_id, all_ids)
                params = mask_update(params, mask)
                print(f"🔒 Applied secure aggregation mask")
            except Exception as e:
                print(f"⚠ Secure aggregation masking failed: {e}")

        # ===== Build metrics =====
        metrics = {
            "client_id": self.client_id,
            "train_time": result["time"],
            "local_accuracy": result["accuracy"],
            "local_loss": result["loss"],
            "cid": cid,
            "proof": proof_str,
        }

        # ===== Training verification commitment =====
        if TRAINING_VERIFICATION_ENABLED and loss_before is not None:
            try:
                from training_verifier import compute_training_commitment
                from FL_Client.train import LR, EPOCHS
                commitment = compute_training_commitment(
                    global_params_np, params,
                    loss_before, result["loss"],
                    EPOCHS, LR,
                )
                metrics["training_commitment"] = json.dumps(commitment)
            except Exception as e:
                print(f"⚠ Training commitment failed: {e}")

        return params, len(self.trainloader.dataset), metrics

    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        result = evaluate(self.model, self.testloader, self.criterion)
        print(f"[Client {self.client_id}] Test Acc: {result['accuracy']:.4f}")
        return result["loss"], len(self.testloader.dataset), result
