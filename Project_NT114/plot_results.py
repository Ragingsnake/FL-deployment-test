import argparse
import json
import os

import matplotlib.pyplot as plt
import numpy as np


def align_xy(x, y):
    n = min(len(x), len(y))
    return x[:n], y[:n]


def client_series(data, *names):
    for name in names:
        if name in data:
            return data[name]
    return []


def save_plot(path):
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()


def plot_results(history_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    with open(history_path, "r", encoding="utf-8") as f:
        history = json.load(f)

    global_data = history.get("global", {})
    clients_data = history.get("clients", {})
    rounds = global_data.get("round", [])

    plt.style.use("seaborn-v0_8-whitegrid")

    plt.figure(figsize=(8, 5))
    for cid in sorted(clients_data.keys(), key=lambda x: int(x)):
        data = clients_data[cid]
        x, y = align_xy(data.get("round", []), data.get("train_time", []))
        plt.plot(x, y, marker="o", label=f"Client {cid}")
    plt.title("Training Time per Client")
    plt.xlabel("Communication Round")
    plt.ylabel("Training Time (seconds)")
    plt.legend()
    save_plot(f"{output_dir}/train_time.png")

    plt.figure(figsize=(8, 5))
    for cid in sorted(clients_data.keys(), key=lambda x: int(x)):
        data = clients_data[cid]
        y_values = client_series(data, "test_accuracy", "local_accuracy", "accuracy")
        x, y = align_xy(data.get("round", []), y_values)
        plt.plot(x, y, marker="o", label=f"Client {cid}")
    plt.title("Local Test Accuracy per Client")
    plt.xlabel("Communication Round")
    plt.ylabel("Accuracy")
    plt.ylim(0, 1)
    plt.legend()
    save_plot(f"{output_dir}/local_accuracy.png")

    plt.figure(figsize=(8, 5))
    plt.plot(rounds, global_data.get("loss", []), linewidth=3, label="Global Loss")
    for cid in sorted(clients_data.keys(), key=lambda x: int(x)):
        data = clients_data[cid]
        y_values = client_series(data, "test_loss", "local_loss", "loss")
        x, y = align_xy(data.get("round", []), y_values)
        plt.plot(x, y, linestyle="--", alpha=0.7, label=f"Client {cid}")
    plt.title("Loss Comparison (Global vs Clients)")
    plt.xlabel("Communication Round")
    plt.ylabel("Loss")
    plt.legend()
    save_plot(f"{output_dir}/loss_comparison.png")

    plt.figure(figsize=(8, 5))
    plt.plot(rounds, global_data.get("accuracy", []), linewidth=3, label="Global Accuracy")
    for cid in sorted(clients_data.keys(), key=lambda x: int(x)):
        data = clients_data[cid]
        y_values = client_series(data, "test_accuracy", "local_accuracy", "accuracy")
        x, y = align_xy(data.get("round", []), y_values)
        plt.plot(x, y, linestyle="--", alpha=0.7, label=f"Client {cid}")
    plt.title("Accuracy Comparison (Global vs Clients)")
    plt.xlabel("Communication Round")
    plt.ylabel("Accuracy")
    plt.legend()
    save_plot(f"{output_dir}/accuracy_comparison.png")

    rejected = global_data.get("penalty_clients", [])
    total_clients = max(len(clients_data), 1)
    if rejected:
        x = []
        rejected_rate = []
        valid_rate = []
        for i, round_clients in enumerate(rejected):
            r_rate = len(round_clients) / total_clients
            x.append(i + 1)
            rejected_rate.append(r_rate)
            valid_rate.append(1 - r_rate)

        plt.figure(figsize=(9, 5))
        plt.plot(x, valid_rate, marker="o", linewidth=2, label="Valid Update Rate")
        plt.plot(x, rejected_rate, marker="o", linewidth=2, label="Rejected Update Rate")
        plt.title("Valid vs Rejected Update Rate per Round")
        plt.xlabel("Communication Round")
        plt.ylabel("Rate")
        plt.ylim(0, 1)
        plt.yticks(np.arange(0, 1.1, 0.1))
        plt.grid(axis="y", linestyle="--", alpha=0.6)
        plt.legend()
        save_plot(f"{output_dir}/rejected_clients.png")

    plt.figure(figsize=(8, 5))
    plt.plot(rounds, global_data.get("accuracy", []), marker="o", label="Accuracy")
    plt.plot(rounds, global_data.get("loss", []), marker="s", label="Loss")
    plt.title("Global Model Performance")
    plt.xlabel("Communication Round")
    plt.legend()
    save_plot(f"{output_dir}/global_performance.png")

    plt.figure(figsize=(8, 5))
    for cid in sorted(clients_data.keys(), key=lambda x: int(x)):
        data = clients_data[cid]
        reputation = data.get("reputation", [])
        if not reputation:
            continue
        r_rounds = [r["round"] for r in reputation]
        r_values = [r["value"] for r in reputation]
        plt.plot(r_rounds, r_values, marker="o", label=f"Client {cid}")
    plt.title("Client Reputation Evolution")
    plt.xlabel("Communication Round")
    plt.ylabel("Reputation Score")
    plt.legend()
    save_plot(f"{output_dir}/client_reputation.png")

    accuracy = global_data.get("accuracy", [])
    if len(accuracy) > 1:
        convergence_speed = np.diff(accuracy)
        rounds_conv = rounds[1 : len(convergence_speed) + 1]
        plt.figure(figsize=(8, 5))
        plt.plot(rounds_conv, convergence_speed, marker="o", linewidth=2)
        plt.title("Model Convergence Speed")
        plt.xlabel("Communication Round")
        plt.ylabel("Accuracy Improvement")
        plt.axhline(0, linestyle="--", linewidth=1)
        save_plot(f"{output_dir}/convergence_speed.png")

    print(f"All plots saved in folder: {output_dir}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=os.environ.get("SPLIT_TYPE", "non_iid"))
    parser.add_argument("--history")
    parser.add_argument("--output-dir")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    history_path = args.history or f"history/server_history_fedadam_{args.mode}.json"
    output_dir = args.output_dir or f"picture/log_full/{args.mode}"
    plot_results(history_path, output_dir)
