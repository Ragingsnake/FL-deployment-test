# ================== train.py ==================
import torch
import time
import os

# Use the same device detection as Flower.py for consistency
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MU = 0.001
LR = 0.0005
EPOCHS = 2

if DEVICE.type == "cpu":
    torch.set_num_threads(8)       
    torch.set_num_interop_threads(4)

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

    # Keep only trainable parameters, keyed by name, to avoid buffer/shape mismatches.
    if isinstance(global_params, dict):
        global_param_dict = global_params
    else:
        global_param_dict = {
            name: tensor
            for (name, _), tensor in zip(model.named_parameters(), global_params)
        }

    # ==============================
    # TRAINING LOOP
    # ==============================
    for _ in range(EPOCHS):
        for batch_idx, (data, target) in enumerate(trainloader):

            data, target = data.to(DEVICE), target.to(DEVICE)
            optimizer.zero_grad()

            output = model(data)
            loss = criterion(output, target)

            # FedProx — computed every 5 batches to reduce overhead
            if batch_idx % 5 == 0:
                prox_term = sum(
                    torch.sum((w - global_param_dict[name]) ** 2)
                    for name, w in model.named_parameters()
                    if name in global_param_dict
                )
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