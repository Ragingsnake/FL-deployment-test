import flwr as fl
import os
import subprocess
import sys
import time
from FL_Server.strategy import SecureFLStrategy
from FL_Server.strategy_fedavg import SimpleFLStrategy
from FL_Server.config import ROUNDS

def main():

    # strategy = SimpleFLStrategy()
    strategy = SecureFLStrategy()

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

    if os.environ.get("KEEP_SERVER_ALIVE_AFTER_TRAINING", "1") == "1":
        print("Training finished. Keeping server pod alive for output retrieval.")
        while True:
            time.sleep(3600)
    
if __name__ == "__main__":
    print("Starting Federated Learning Server...")
    main()
