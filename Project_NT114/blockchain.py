import os
from web3 import Web3
import json
from reputation import update_reputation

w3 = Web3(Web3.HTTPProvider(os.environ.get("ETH_RPC","http://127.0.0.1:7545")))

try:
    from web3.middleware import ExtraDataToPOAMiddleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
except Exception:
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass

contract_address = os.environ.get("REPUTATION_ADDRESS") or (open(os.environ.get("CONTRACT_ADDRESS_FILE","/app/build/contracts/Reputation.address")).read().strip() if os.path.exists(os.environ.get("CONTRACT_ADDRESS_FILE","/app/build/contracts/Reputation.address")) else None)

with open("build/contracts/Reputation.json", "r", encoding="utf-8") as f:
    contract_json = json.load(f)

abi = contract_json["abi"]
contract = w3.eth.contract(address=contract_address, abi=abi)
account = w3.eth.accounts[0]

# ==========================================
# Submit client update
# ==========================================
def submit_update(round_num, client_id, cid, proof_hash, accuracy):

    tx = contract.functions.submitUpdate(
        int(round_num),
        int(client_id),
        str(cid), # cid này có thể là tên hoặc hash (string)
        str(proof_hash),
        int(accuracy * 1000)
    ).transact({"from": account})

    receipt = w3.eth.wait_for_transaction_receipt(tx)
    return receipt.transactionHash.hex()

# ==========================================
# Verify update + update reputation (SỬA LỖI TẠI ĐÂY)
# ==========================================
def verify_update(client_id, round_num, result):
    try:
        tx = contract.functions.verifyUpdate(
            int(client_id),   
            int(round_num),   
            bool(result)      
        ).transact({"from": account})

        w3.eth.wait_for_transaction_receipt(tx)

        score = 1.0 if result else -1.0
        rep = update_reputation(client_id, score)

        print(f"✅ Blockchain Verify → Client {client_id} | Round {round_num} | Rep: {rep:.3f}")
        return True
    except Exception as e:
        print(f"❌ Blockchain Error: {e}")
        return False

# ==========================================
# Query reputation
# ==========================================
def get_reputation(client_id):
    return contract.functions.getReputation(int(client_id)).call()