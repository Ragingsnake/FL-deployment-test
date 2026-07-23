import flwr as fl
import os
import subprocess
import sys
import time
from FL_Server.strategy import SecureFLStrategy
from FL_Server.strategy_fedavg import SimpleFLStrategy
from FL_Server.config import ROUNDS, AGGREGATION_METHOD, VERIFICATION_MODE, STAKING_ENABLED

def main():

    strategy_name = os.environ.get("FL_STRATEGY", "secure")

    if strategy_name == "fedavg":
        strategy = SimpleFLStrategy()
        print("📋 Strategy: SimpleFLStrategy (FedAvg baseline)")
    else:
        strategy = SecureFLStrategy()
        print("📋 Strategy: SecureFLStrategy (ZKP + Reputation + Defense)")

    print(f"📋 Aggregation method: {AGGREGATION_METHOD}")
    print(f"📋 Verification mode: {VERIFICATION_MODE}")
    print(f"📋 Staking enabled: {STAKING_ENABLED}")
    print(f"📋 Rounds: {ROUNDS}")

    fl.server.start_server(
        server_address="0.0.0.0:8080",
        config=fl.server.ServerConfig(num_rounds=ROUNDS),
        strategy=strategy
    )

    mode = os.environ.get("SPLIT_TYPE", "non_iid")
    history_path = os.environ.get(
        "HISTORY_PATH",
        f"history/server_history_fedadam_{mode}.json",
    )
    plot_dir = os.environ.get("PLOT_DIR", f"picture/log_full/{mode}")

    if os.path.exists(history_path):
        print(f"Generating plots from {history_path} into {plot_dir}...")
        subprocess.run(
            [
                sys.executable,
                "plot_results.py",
                "--mode",
                mode,
                "--history",
                history_path,
                "--output-dir",
                plot_dir,
            ],
            check=False,
        )
    else:
        print(f"History file not found, skipping plot generation: {history_path}")

    iid_history = "history/server_history_fedadam_iid.json"
    non_iid_history = "history/server_history_fedadam_non_iid.json"
    if os.path.exists(iid_history) and os.path.exists(non_iid_history):
        comparison_dir = os.environ.get("COMPARISON_PLOT_DIR", "picture/comparison")
        print(f"Generating IID vs non-IID comparison plots into {comparison_dir}...")
        subprocess.run(
            [
                sys.executable,
                "comparison.py",
                "--iid-history",
                iid_history,
                "--non-iid-history",
                non_iid_history,
                "--output-dir",
                comparison_dir,
            ],
            check=False,
        )

    if os.environ.get("KEEP_SERVER_ALIVE_AFTER_TRAINING", "1") == "1":
        print("Training finished. Keeping server pod alive for output retrieval.")
        while True:
            time.sleep(3600)

if __name__ == "__main__":
    print("Starting Federated Learning Server...")
    main()
