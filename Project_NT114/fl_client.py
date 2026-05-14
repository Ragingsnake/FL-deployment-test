import os
import sys
import flwr as fl
from FL_Client.Flower import FlowerClient

if __name__ == "__main__":

    if len(sys.argv) != 3:
        print("Usage: python fl_client.py <client_id> <iid|non_iid>")
        sys.exit(1)

    client_id = int(sys.argv[1])
    split_type = sys.argv[2]

    print(f"Starting Client {client_id} with {split_type}")

    fl.client.start_numpy_client(
        server_address=f"{os.environ.get('FL_SERVER_HOST','localhost')}:{os.environ.get('FL_SERVER_PORT','8080')}",
        client=FlowerClient(client_id, split_type),
    )