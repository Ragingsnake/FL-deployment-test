# ================== train.py ==================
import torch
import time
import os

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

MU = float(os.environ.get("FEDPROX_MU", "0.001"))
LR = float(os.environ.get("CLIENT_LR", "0.0005"))
EPOCHS = int(os.environ.get("LOCAL_EPOCHS", "2"))
PROX_EVERY_N_BATCHES = int(os.environ.get("FEDPROX_EVERY_N_BATCHES", "5"))
NUM_THREADS = int(os.environ.get("TORCH_NUM_THREADS", "8"))
NUM_INTEROP_THREADS = int(os.environ.get("TORCH_NUM_INTEROP_THREADS", "4"))

torch.set_num_threads(NUM_THREADS)
torch.set_num_interop_threads(NUM_INTEROP_THREADS)

# def train(model, trainloader, _, criterion):
#     optimizer = torch.optim.Adam(model.parameters(), lr=LR)
#     model.train()

#     total_loss, correct, total = 0.0, 0, 0
#     start_time = time.time()

#     for _ in range(EPOCHS):
#         for data, target in trainloader:
#             data, target = data.to(DEVICE), target.to(DEVICE)

#             optimizer.zero_grad()
#             output = model(data)
#             loss = criterion(output, target)

#             loss.backward()
#             optimizer.step()

#             total_loss += loss.item()

#             pred = torch.argmax(output, dim=1)
#             correct += (pred == target).sum().item()
#             total += target.size(0)

#     return {
#         "loss": total_loss / (len(trainloader) * EPOCHS),
#         "accuracy": correct / total,
#         "time": time.time() - start_time
#     }

def train(model, trainloader, global_params, criterion):
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    model.train()

    total_loss, correct, total = 0.0, 0, 0
    start_time = time.time()

    if isinstance(global_params, dict):
        global_param_list = [
            global_params[name]
            for name, _ in model.named_parameters()
            if name in global_params
        ]
    else:
        global_param_list = list(global_params or [])

    # ==============================
    # TRAINING LOOP
    # ==============================
    for _ in range(EPOCHS):
        for batch_idx, (data, target) in enumerate(trainloader):

            data, target = data.to(DEVICE), target.to(DEVICE)
            optimizer.zero_grad()

            output = model(data)
            loss = criterion(output, target)

            # ==============================
            # FEDPROX (reduced frequency for the upstream fast-training profile)
            # ==============================
            if global_param_list and batch_idx % PROX_EVERY_N_BATCHES == 0:
                prox_term = 0.0
                for w, w_t in zip(model.parameters(), global_param_list):
                    w_t = w_t.to(w.device)
                    prox_term += torch.sum((w - w_t) ** 2)
            else:
                prox_term = 0.0

            loss = loss + (MU / 2) * prox_term

            loss.backward()
            optimizer.step()

            total_loss += loss.item()

            pred = torch.argmax(output, dim=1)
            correct += (pred == target).sum().item()
            total += target.size(0)

    # ==============================
    # FIX LOSS (đúng theo epoch)
    # ==============================
    avg_loss = total_loss / (len(trainloader) * EPOCHS)

    return {
        "loss": avg_loss,
        "accuracy": correct / total,
        "time": time.time() - start_time
    }
