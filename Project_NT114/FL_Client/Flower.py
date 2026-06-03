import flwr as fl
import torch
import torch.nn as nn
import os
from model import CNN
from utils import load_client_data
from ipfs_utils import upload_to_ipfs
from zkp_utils import canonical_proof_json, generate_proof, proof_hash
from blockchain import submit_update
from FL_Client.train import train
from FL_Client.evaluate import evaluate
from FL_Client.faulty import is_faulty_client, corrupt_parameters

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


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
    bad_proof = dict(proof)
    bad_statement = dict(bad_proof.get("statement", {}))
    bad_statement["model_hash"] = "invalid-demo-proof"
    bad_proof["statement"] = bad_statement
    return bad_proof

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
        # CRITICAL FIX: Use strict=True to ensure model structure matches exactly
        try:
            self.model.load_state_dict(state_dict, strict=True)
        except RuntimeError as e:
            print(f"⚠ WARNING: State dict mismatch for client {self.client_id}: {e}")
            # Only fallback to strict=False if there's a real reason
            self.model.load_state_dict(state_dict, strict=False)
        
    # def fit(self, parameters, config):
    #     self.set_parameters(parameters)

    #     result = train(self.model, self.trainloader, None, self.criterion)

    #     print(f"[Client {self.client_id}] Acc: {result['accuracy']:.4f} | Loss: {result['loss']:.4f}")

    #     params = self.get_parameters({})

    #     metrics = {
    #         "client_id": self.client_id,
    #         "train_time": result["time"],
    #         "test_acc": result["accuracy"],
    #         "test_loss": result["loss"],
    #     }

    #     return params, len(self.trainloader.dataset), metrics

    def fit(self, parameters, config):
        self.set_parameters(parameters)
        round_num = config.get("server_round", 1)
        
        faulty_clients = _parse_client_ids(config.get("demo_faulty_clients", ""))
        bad_zkp_clients = _parse_client_ids(config.get("demo_bad_zkp_clients", ""))

        is_faulty = self.client_id in faulty_clients
        is_bad_zkp = self.client_id in bad_zkp_clients
        
        if is_faulty:
            print(f"⚠ Client {self.client_id} is FAULTY")
        if is_bad_zkp:
            print(f"⚠ Client {self.client_id} will send an INVALID ZKP proof")
        trainable_names = {name for name, _ in self.model.named_parameters()}
        global_params = {
            name: torch.from_numpy(value).to(DEVICE).detach().clone()
            for name, value in zip(self.model.state_dict().keys(), parameters)
            if name in trainable_names
        }
        
        result = train(self.model, self.trainloader, global_params, self.criterion)
        print(f"[Client {self.client_id}] Acc: {result['accuracy']:.4f} | Loss: {result['loss']:.4f}")

        os.makedirs("models/clients", exist_ok=True)
        model_path = f"models/clients/client{self.client_id}_round{round_num}.pth"
        torch.save(self.model.state_dict(), model_path)

        cid = upload_to_ipfs(model_path)
        params = self.get_parameters({})
        if is_faulty:
            params = corrupt_parameters(params, config.get("demo_faulty_noise_scale", 0.01))
            print("💣 Sent corrupted update")

        proof = generate_proof(params, client_id=self.client_id, round_num=round_num, cid=cid)
        if is_bad_zkp:
            proof = _tamper_proof(proof)
            print("🧪 Sent intentionally invalid ZKP proof")

        proof_str = canonical_proof_json(proof)
        try:
            tx_hash = submit_update(round_num, self.client_id, cid, proof_hash(proof), result["accuracy"])
            if tx_hash:
                print("TX:", tx_hash)
            else:
                print("TX skipped")
        except Exception as e:
            print("Blockchain error:", e)

        metrics = {
            "client_id": self.client_id,
            "train_time": result["time"],
            "local_accuracy": result["accuracy"],
            "local_loss": result["loss"],
            "cid": cid,
            "proof": proof_str,
        }
        return params, len(self.trainloader.dataset), metrics

    def evaluate(self, parameters, config):
        self.set_parameters(parameters)
        result = evaluate(self.model, self.testloader, self.criterion)
        print(f"[Client {self.client_id}] Test Acc: {result['accuracy']:.4f}")
        return result["loss"], len(self.testloader.dataset), result
