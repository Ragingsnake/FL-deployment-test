import flwr as fl
import torch
import torch.nn as nn
import os
import json
import hashlib
import threading

from model import CNN
from utils import load_client_data
from ipfs_utils import upload_to_ipfs
from zkp_utils import generate_proof
from blockchain import submit_update
from FL_Client.train import train
from FL_Client.evaluate import evaluate
from FL_Client.faulty import corrupt_parameters

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Controls whether model is uploaded to IPFS every round.
# Set SKIP_IPFS=1 during development/benchmarking to remove upload latency.
# In production leave unset or set to 0.
# SKIP_IPFS = os.environ.get("SKIP_IPFS", "0") == "1"
SKIP_IPFS = False

def _upload_async(model_path, round_num, client_id, proof_hash, accuracy):
    """Upload to IPFS and submit blockchain tx off the critical path."""
    cid = upload_to_ipfs(model_path) if not SKIP_IPFS else "SKIPPED"
    try:
        submit_update(round_num, client_id, cid, proof_hash, accuracy)
    except Exception as e:
        print(f"[Client {client_id}] Blockchain submit error (non-fatal): {e}")


class FlowerClient(fl.client.NumPyClient):
    def __init__(self, client_id, split_type):
        self.client_id = client_id
        self.model = CNN(num_classes=62).to(DEVICE)
        self.trainloader, self.testloader = load_client_data(client_id, split_type)
        self.criterion = nn.CrossEntropyLoss()

    def get_parameters(self, config):
        # Return only trainable parameters — excludes BatchNorm running stats
        # (running_mean, running_var, num_batches_tracked) which are buffers,
        # not weights. Sending buffers wastes bandwidth every round.
        return [p.detach().cpu().numpy() for p in self.model.parameters()]

    def set_parameters(self, parameters):
        # Match incoming parameters to named_parameters (trainable only)
        for param, value in zip(self.model.parameters(), parameters):
            param.data = torch.tensor(value).to(DEVICE)

    def fit(self, parameters, config):
        self.set_parameters(parameters)
        round_num = config.get("server_round", 1)

        faulty_clients = config.get("faulty_clients", [])
        is_faulty = self.client_id in faulty_clients

        if is_faulty:
            print(f"⚠ Client {self.client_id} is FAULTY this round")

        # Build global_params dict for FedProx (trainable params only)
        global_params = {
            name: p.detach().clone().to(DEVICE)
            for name, p in zip(
                [n for n, _ in self.model.named_parameters()],
                parameters
            )
            for p in [torch.tensor(
                next(v for n2, v in zip([n2 for n2, _ in self.model.named_parameters()], parameters) 
                     if n2 == name)
            ).to(DEVICE)]
        }
        # Simpler equivalent:
        global_params = {}
        for (name, _), value in zip(self.model.named_parameters(), parameters):
            global_params[name] = torch.tensor(value).to(DEVICE).detach().clone()

        result = train(self.model, self.trainloader, global_params, self.criterion)
        print(f"[Client {self.client_id}] Acc: {result['accuracy']:.4f} | Loss: {result['loss']:.4f} | Time: {result['time']:.1f}s")

        params = self.get_parameters({})

        if is_faulty:
            params = corrupt_parameters(params)
            print(f"[Client {self.client_id}] 💣 Sent corrupted update")

        proof = generate_proof(params)
        proof_str = json.dumps(proof)
        proof_hash = hashlib.sha256((proof_str).encode()).hexdigest()

        # Save model only every 5 rounds to reduce disk I/O
        # (was saving every round × 5 clients = 250 writes for 50 rounds)
        if round_num % 5 == 0:
            os.makedirs("models/clients", exist_ok=True)
            model_path = f"models/clients/client{self.client_id}_round{round_num}.pth"
            torch.save(self.model.state_dict(), model_path)

            # IPFS upload + blockchain submit off the critical path
            threading.Thread(
                target=_upload_async,
                args=(model_path, round_num, self.client_id, proof_hash, result["accuracy"]),
                daemon=True
            ).start()
            cid = "async"
        else:
            cid = "skipped"

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