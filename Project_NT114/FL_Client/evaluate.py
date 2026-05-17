# ================== evaluate.py ==================
import torch
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

def evaluate(model, testloader, criterion):
    model.eval()
    # Update BatchNorm stats by running a forward pass in training mode
    # This synchronizes the running_mean and running_var for proper evaluation
    model.train()
    with torch.no_grad():
        for data, _ in testloader:
            data = data.to(DEVICE)
            _ = model(data)
            break  # Only need one batch to update stats
    
    # Now run evaluation in eval mode with synchronized stats
    model.eval()
    correct, total, loss = 0, 0, 0.0
    with torch.no_grad():
        for data, target in testloader:
            data, target = data.to(DEVICE), target.to(DEVICE)
            output = model(data)
            loss += criterion(output, target).item()
            pred = torch.argmax(output, dim=1)
            correct += (pred == target).sum().item()
            total += target.size(0)
    return {
        "loss": loss / len(testloader),
        "accuracy": correct / total
    }