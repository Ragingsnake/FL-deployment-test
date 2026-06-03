import numpy as np
import os

TOTAL_CLIENTS = 5
LAMBDA = 1 

LAST_FAULTY = set()

def get_faulty_clients(round_num):
    global LAST_FAULTY

    num_faulty = np.random.poisson(LAMBDA)
    num_faulty = min(num_faulty, TOTAL_CLIENTS      )

    candidates = list(set(range(1, TOTAL_CLIENTS + 1)) - LAST_FAULTY)

    if len(candidates) < num_faulty:
        candidates = list(range(1, TOTAL_CLIENTS + 1))

    faulty_clients = list(np.random.choice(candidates, num_faulty, replace=False))

    LAST_FAULTY = set(faulty_clients)

    print(f"[Round {round_num}] Faulty clients: {faulty_clients} (Poisson λ={LAMBDA})")

    return faulty_clients


def is_faulty_client(client_id, round_num):

    faulty_clients = get_faulty_clients(round_num)

    return client_id in faulty_clients

def corrupt_parameters(params, noise_scale=None):
    if noise_scale is None:
        noise_scale = float(os.environ.get("DEMO_FAULTY_NOISE_SCALE", "0.01"))
    else:
        noise_scale = float(noise_scale)

    corrupted = []

    for p in params:
        noise = np.random.normal(0, noise_scale, p.shape)

        corrupted.append(p + noise)

    return corrupted
