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

_contract = None
_contract_warning_emitted = False

with open("build/contracts/Reputation.json", "r", encoding="utf-8") as f:
    contract_json = json.load(f)

abi = contract_json["abi"]


def _load_contract_address():
    address = os.environ.get("REPUTATION_ADDRESS")
    if address:
        return address.strip()

    contract_file = os.environ.get("CONTRACT_ADDRESS_FILE", "/app/build/contracts/Reputation.address")
    if os.path.exists(contract_file):
        with open(contract_file, "r", encoding="utf-8") as handle:
            address = handle.read().strip()
            if address:
                return address

    return None


def _get_contract():
    global _contract, _contract_warning_emitted

    if _contract is not None:
        return _contract

    contract_address = _load_contract_address()
    if not contract_address:
        if not _contract_warning_emitted:
            print("⚠ Blockchain disabled: missing REPUTATION_ADDRESS / contract address file")
            _contract_warning_emitted = True
        return None

    _contract = w3.eth.contract(address=contract_address, abi=abi)
    return _contract


def _get_account():
    if not w3.eth.accounts:
        return None
    return w3.eth.accounts[0]

# ==========================================
# Submit client update
# ==========================================
def submit_update(round_num, client_id, cid, proof_hash, accuracy):
    contract = _get_contract()
    account = _get_account()

    if contract is None or account is None:
        return None

    tx_hash = contract.functions.submitUpdate(
        int(round_num),
        int(client_id),
        str(cid), # cid này có thể là tên hoặc hash (string)
        str(proof_hash),
        int(accuracy * 1000)
    ).transact({"from": account})

    return tx_hash.hex()

# ==========================================
# Verify update + update reputation (SỬA LỖI TẠI ĐÂY)
# ==========================================
def verify_update(client_id, round_num, result):
    try:
        contract = _get_contract()
        account = _get_account()

        if contract is None or account is None:
            score = 1.0 if result else -1.0
            rep = update_reputation(client_id, score)
            print(f"⚠ Blockchain skipped → Client {client_id} | Round {round_num} | Rep: {rep:.3f}")
            return False

        tx = contract.functions.verifyUpdate(
            int(client_id),   
            int(round_num),   
            bool(result)      
        ).transact({"from": account})

        score = 1.0 if result else -1.0
        rep = update_reputation(client_id, score)

        print(f"✅ Blockchain Verify → Client {client_id} | Round {round_num} | Rep: {rep:.3f} | TX: {tx.hex()}")
        return True
    except Exception as e:
        print(f"❌ Blockchain Error: {e}")
        return False

# ==========================================
# Query reputation
# ==========================================
def get_reputation(client_id):
    contract = _get_contract()
    if contract is None:
        return None
    return contract.functions.getReputation(int(client_id)).call()