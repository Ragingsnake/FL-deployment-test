import argparse
import json
import os

import matplotlib.pyplot as plt
import numpy as np


def load_history(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def align(*series):
    n = min(len(s) for s in series)
    return [s[:n] for s in series]


def sorted_clients(history):
    clients = history.get("clients", {})
    return sorted(clients.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))


def client_metric(client_data, *names):
    for name in names:
        if name in client_data:
            return client_data[name]
    return []


def avg_client_series(history, *metric_names):
    rounds = history.get("global", {}).get("round", [])
    clients = history.get("clients", {})
    values = []
    for i in range(len(rounds)):
        per_client = []
        for cid in sorted_clients(history):
            series = client_metric(clients[cid], *metric_names)
            if i < len(series):
                per_client.append(series[i])
        values.append(float(np.mean(per_client)) if per_client else np.nan)
    return values


def avg_train_time(history):
    times = []
    for cid in sorted_clients(history):
        times.extend(history["clients"][cid].get("train_time", []))
    return float(np.mean(times)) if times else 0.0


def avg_reputation(history):
    rounds = history.get("global", {}).get("round", [])
    clients = history.get("clients", {})
    values = []
    for i in range(len(rounds)):
        reps = []
        for cid in sorted_clients(history):
            reputation = clients[cid].get("reputation", [])
            if i < len(reputation):
                item = reputation[i]
                reps.append(item.get("value", item) if isinstance(item, dict) else item)
        values.append(float(np.mean(reps)) if reps else np.nan)
    return values


def client_reputation_distribution(history):
    values = []
    for cid in sorted_clients(history):
        reputation = history["clients"][cid].get("reputation", [])
        series = [r.get("value", r) if isinstance(r, dict) else r for r in reputation]
        if series:
            values.append(series)
    return values


def save(path):
    plt.tight_layout()
    plt.savefig(path, dpi=300)
    plt.close()


def plot_line_compare(rounds_iid, iid_values, rounds_non_iid, non_iid_values, title, ylabel, path, ylim=None):
    x1, y1 = align(rounds_iid, iid_values)
    x2, y2 = align(rounds_non_iid, non_iid_values)
    plt.figure(figsize=(10, 5))
    plt.plot(x1, y1, marker="o", linewidth=2, label="IID")
    plt.plot(x2, y2, marker="s", linewidth=2, label="Non-IID")
    plt.title(title)
    plt.xlabel("Communication Round")
    plt.ylabel(ylabel)
    if ylim:
        plt.ylim(*ylim)
    plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
    save(path)


def plot_comparison(iid, non_iid, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({"font.size": 12, "axes.labelweight": "bold", "axes.titleweight": "bold"})

    iid_global = iid.get("global", {})
    non_iid_global = non_iid.get("global", {})
    rounds_iid = iid_global.get("round", [])
    rounds_non_iid = non_iid_global.get("round", [])

    plot_line_compare(
        rounds_iid,
        iid_global.get("accuracy", []),
        rounds_non_iid,
        non_iid_global.get("accuracy", []),
        "Global Accuracy: IID vs Non-IID",
        "Accuracy",
        f"{output_dir}/compare_global_accuracy.png",
        (0, 1),
    )

    plot_line_compare(
        rounds_iid,
        iid_global.get("loss", []),
        rounds_non_iid,
        non_iid_global.get("loss", []),
        "Global Loss: IID vs Non-IID",
        "Loss",
        f"{output_dir}/compare_global_loss.png",
    )

    if iid_global.get("round_time") and non_iid_global.get("round_time"):
        plot_line_compare(
            rounds_iid,
            iid_global.get("round_time", []),
            rounds_non_iid,
            non_iid_global.get("round_time", []),
            "Round Time: IID vs Non-IID",
            "Round Time (seconds)",
            f"{output_dir}/compare_round_time.png",
        )

    plt.figure(figsize=(8, 5))
    plt.bar(["IID", "Non-IID"], [avg_train_time(iid), avg_train_time(non_iid)])
    plt.title("Average Client Training Time")
    plt.ylabel("Seconds")
    save(f"{output_dir}/compare_train_time.png")

    plot_line_compare(
        rounds_iid,
        avg_client_series(iid, "test_accuracy", "local_accuracy", "accuracy"),
        rounds_non_iid,
        avg_client_series(non_iid, "test_accuracy", "local_accuracy", "accuracy"),
        "Average Local Accuracy: IID vs Non-IID",
        "Accuracy",
        f"{output_dir}/compare_local_accuracy.png",
        (0, 1),
    )

    plot_line_compare(
        rounds_iid,
        avg_reputation(iid),
        rounds_non_iid,
        avg_reputation(non_iid),
        "Average Client Reputation: IID vs Non-IID",
        "Reputation Score",
        f"{output_dir}/compare_reputation.png",
    )

    iid_rep = client_reputation_distribution(iid)
    non_iid_rep = client_reputation_distribution(non_iid)
    if iid_rep and non_iid_rep:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), sharey=True)
        ax1.boxplot(iid_rep)
        ax1.set_title("Reputation Distribution (IID)")
        ax1.set_ylabel("Reputation Score")
        ax1.set_xticklabels([f"Client {i + 1}" for i in range(len(iid_rep))], rotation=45)
        ax2.boxplot(non_iid_rep)
        ax2.set_title("Reputation Distribution (Non-IID)")
        ax2.set_xticklabels([f"Client {i + 1}" for i in range(len(non_iid_rep))], rotation=45)
        save(f"{output_dir}/reputation_distribution_comparison.png")

    total_clients = max(len(iid.get("clients", {})), len(non_iid.get("clients", {})), 1)
    iid_penalty = iid_global.get("penalty_clients", [])
    non_iid_penalty = non_iid_global.get("penalty_clients", [])
    if iid_penalty and non_iid_penalty:
        n = min(len(rounds_iid), len(rounds_non_iid), len(iid_penalty), len(non_iid_penalty))
        x = np.arange(n)
        width = 0.35
        iid_rejected = np.array([len(p) for p in iid_penalty[:n]]) / total_clients
        non_iid_rejected = np.array([len(p) for p in non_iid_penalty[:n]]) / total_clients
        plt.figure(figsize=(10, 5))
        plt.bar(x, 1 - iid_rejected, width=width, label="IID Valid")
        plt.bar(x, iid_rejected, width=width, bottom=1 - iid_rejected, label="IID Rejected")
        plt.bar(x + width, 1 - non_iid_rejected, width=width, label="Non-IID Valid")
        plt.bar(x + width, non_iid_rejected, width=width, bottom=1 - non_iid_rejected, label="Non-IID Rejected")
        plt.title("Valid vs Rejected Update Rate")
        plt.xlabel("Communication Round")
        plt.ylabel("Rate")
        plt.xticks(x + width / 2, rounds_iid[:n])
        plt.ylim(0, 1.05)
        plt.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        save(f"{output_dir}/compare_update_rate_bar.png")

    iid_gain = [0] + list(np.diff(iid_global.get("accuracy", [])))
    non_iid_gain = [0] + list(np.diff(non_iid_global.get("accuracy", [])))
    plot_line_compare(
        rounds_iid,
        iid_gain,
        rounds_non_iid,
        non_iid_gain,
        "Model Convergence Speed",
        "Accuracy Gain",
        f"{output_dir}/compare_convergence_speed.png",
    )

    print(f"All comparison plots saved in: {output_dir}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iid-history", default="history/server_history_fedadam_iid.json")
    parser.add_argument("--non-iid-history", default="history/server_history_fedadam_non_iid.json")
    parser.add_argument("--output-dir", default="picture/comparison")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    plot_comparison(load_history(args.iid_history), load_history(args.non_iid_history), args.output_dir)
