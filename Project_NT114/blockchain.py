import os
import json
from web3 import Web3
from reputation import update_reputation

# ======================== Web3 Connection ========================
w3 = Web3(Web3.HTTPProvider(os.environ.get("ETH_RPC", "http://127.0.0.1:7545")))

try:
    from web3.middleware import ExtraDataToPOAMiddleware
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
except Exception:
    try:
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
    except Exception:
        pass

# ======================== Contract Loading ========================
_contract = None
_staking_contract = None
_contract_warning_emitted = False

# Load the basic Reputation ABI
with open("build/contracts/Reputation.json", "r", encoding="utf-8") as f:
    contract_json = json.load(f)
abi = contract_json["abi"]

# Try to load the StakingReputation ABI if available
_staking_abi = None
_staking_abi_path = "build/contracts/StakingReputation.json"
if os.path.exists(_staking_abi_path):
    with open(_staking_abi_path, "r", encoding="utf-8") as f:
        _staking_json = json.load(f)
    _staking_abi = _staking_json["abi"]

# ======================== Configuration ========================
VERIFICATION_MODE = os.environ.get("VERIFICATION_MODE", "off-chain")
STAKING_ENABLED = os.environ.get("STAKING_ENABLED", "0") == "1"


def _load_contract_address():
    address = os.environ.get("REPUTATION_ADDRESS")
    if address:
        return address.strip()

    contract_file = os.environ.get(
        "CONTRACT_ADDRESS_FILE", "/app/build/contracts/Reputation.address"
    )
    if os.path.exists(contract_file):
        with open(contract_file, "r", encoding="utf-8") as handle:
            address = handle.read().strip()
            if address:
                return address

    return None


def _load_staking_address():
    address = os.environ.get("STAKING_ADDRESS")
    if address:
        return address.strip()

    contract_file = os.environ.get(
        "STAKING_ADDRESS_FILE", "/app/build/contracts/StakingReputation.address"
    )
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


def _get_staking_contract():
    global _staking_contract

    if _staking_contract is not None:
        return _staking_contract

    if _staking_abi is None:
        return None

    staking_address = _load_staking_address()
    if not staking_address:
        return None

    _staking_contract = w3.eth.contract(address=staking_address, abi=_staking_abi)
    return _staking_contract


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
        str(cid),
        str(proof_hash),
        int(accuracy * 1000),
    ).transact({"from": account})

    return tx_hash.hex()


# ==========================================
# Off-chain verification (existing behavior)
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
            bool(result),
        ).transact({"from": account})

        score = 1.0 if result else -1.0
        rep = update_reputation(client_id, score)

        print(f"✅ Blockchain Verify → Client {client_id} | Round {round_num} | Rep: {rep:.3f} | TX: {tx.hex()}")
        return True
    except Exception as e:
        print(f"❌ Blockchain Error: {e}")
        return False


# ==========================================
# On-chain Groth16 verification (NEW)
# ==========================================
def verify_update_on_chain(client_id, round_num, proof_data):
    """
    Submit Groth16 proof directly to the smart contract for on-chain verification.
    The contract performs the elliptic curve pairing check and updates reputation
    state variables directly — no trusted server needed for verification.

    Args:
        client_id: The client identifier
        round_num: The FL round number
        proof_data: Dict containing 'proof' (with pi_a, pi_b, pi_c) and 'public' signals
    Returns:
        tuple: (verified: bool, tx_hash: str or None)
    """
    contract = _get_contract()
    account = _get_account()

    if contract is None or account is None:
        print("⚠ On-chain verification skipped: no contract or account")
        score = -1.0
        rep = update_reputation(client_id, score)
        return False, None

    try:
        proof = proof_data.get("proof", {})
        public = proof_data.get("public", [])

        # Parse Groth16 proof components (pi_a, pi_b, pi_c)
        # snarkjs outputs: pi_a = [x, y, "1"], pi_b = [[x1,x2],[y1,y2],["1","0"]], pi_c = [x, y, "1"]
        pi_a = proof.get("pi_a", [])
        pi_b = proof.get("pi_b", [])
        pi_c = proof.get("pi_c", [])

        # Format for Solidity: uint[2] a, uint[2][2] b, uint[2] c, uint[4] public_signals
        a = [int(pi_a[0]), int(pi_a[1])]
        # Note: snarkjs pi_b indices are swapped for the EVM precompile
        b = [
            [int(pi_b[0][1]), int(pi_b[0][0])],
            [int(pi_b[1][1]), int(pi_b[1][0])],
        ]
        c = [int(pi_c[0]), int(pi_c[1])]
        public_signals = [int(s) for s in public[:4]]

        # Pad if fewer than 4 public signals
        while len(public_signals) < 4:
            public_signals.append(0)

        # Use StakingReputation if available, otherwise fall back to Reputation
        staking = _get_staking_contract()
        if staking is not None:
            tx = staking.functions.verifyUpdateWithProof(
                int(client_id),
                int(round_num),
                a,
                b,
                c,
                public_signals,
            ).transact({"from": account})
        else:
            tx = contract.functions.verifyUpdateProof(
                int(client_id),
                int(round_num),
                a,
                b,
                c,
                public_signals,
            ).transact({"from": account})

        # Check verification result from event logs
        receipt = w3.eth.wait_for_transaction_receipt(tx)

        verified = False
        target_contract = staking if staking is not None else contract
        for log in receipt.get("logs", []):
            try:
                event = target_contract.events.UpdateVerified().process_log(log)
                verified = event["args"]["result"]
                break
            except Exception:
                continue

        score = 1.0 if verified else -1.0
        rep = update_reputation(client_id, score)

        status = "✅ VALID" if verified else "❌ INVALID"
        print(f"{status} On-Chain ZKP → Client {client_id} | Round {round_num} | Rep: {rep:.3f} | TX: {tx.hex()}")
        return verified, tx.hex()

    except Exception as e:
        print(f"❌ On-chain verification error: {e}")
        print("⚠ Falling back to off-chain verification")
        return False, None


# ==========================================
# Staking operations (NEW)
# ==========================================
def register_client(client_id, stake_wei=None):
    """Register a client with the StakingReputation contract and deposit stake."""
    staking = _get_staking_contract()
    account = _get_account()

    if staking is None or account is None:
        print(f"⚠ Staking disabled: Client {client_id} registration skipped")
        return None

    if stake_wei is None:
        stake_wei = int(os.environ.get("CLIENT_STAKE_WEI", str(10**16)))  # 0.01 ether default

    try:
        tx = staking.functions.registerClient(
            int(client_id)
        ).transact({"from": account, "value": stake_wei})

        w3.eth.wait_for_transaction_receipt(tx)
        print(f"🔐 Client {client_id} registered with stake {stake_wei} wei | TX: {tx.hex()}")
        return tx.hex()
    except Exception as e:
        print(f"❌ Registration error for Client {client_id}: {e}")
        return None


def distribute_rewards(round_num, client_ids, reward_shares):
    """
    Distribute rewards to clients based on their contribution scores.
    reward_shares should be a list of integers representing relative contributions.
    """
    staking = _get_staking_contract()
    account = _get_account()

    if staking is None or account is None:
        return None

    try:
        tx = staking.functions.distributeRewards(
            int(round_num),
            [int(c) for c in client_ids],
            [int(s) for s in reward_shares],
        ).transact({"from": account})

        print(f"💰 Rewards distributed for round {round_num} | TX: {tx.hex()}")
        return tx.hex()
    except Exception as e:
        print(f"❌ Reward distribution error: {e}")
        return None


def get_client_stake(client_id):
    """Query the staked amount for a client."""
    staking = _get_staking_contract()
    if staking is None:
        return None
    try:
        return staking.functions.getStake(int(client_id)).call()
    except Exception:
        return None


def is_client_registered(client_id):
    """Check if a client is registered in the staking contract."""
    staking = _get_staking_contract()
    if staking is None:
        return False
    try:
        return staking.functions.isRegistered(int(client_id)).call()
    except Exception:
        return False


# ==========================================
# Query reputation (existing + staking)
# ==========================================
def get_reputation(client_id):
    # Try staking contract first
    staking = _get_staking_contract()
    if staking is not None:
        try:
            return staking.functions.getReputation(int(client_id)).call()
        except Exception:
            pass

    contract = _get_contract()
    if contract is None:
        return None
    return contract.functions.getReputation(int(client_id)).call()