# ================== evaluate.py ==================
import torch

def evaluate(model, testloader, criterion):
    model.eval()
    device = next(model.parameters()).device
    correct, total, loss = 0, 0, 0.0
    with torch.no_grad():
        for data, target in testloader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            loss += criterion(output, target).item()
            pred = torch.argmax(output, dim=1)
            correct += (pred == target).sum().item()
            total += target.size(0)
    return {
        "loss": loss / len(testloader),
        "accuracy": correct / total
    }