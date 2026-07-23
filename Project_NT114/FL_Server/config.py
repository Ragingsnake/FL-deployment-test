import os

# ======================== FL Training ========================
ROUNDS = int(os.environ.get("FL_ROUNDS", "40"))
NUM_CLIENTS = int(os.environ.get("NUM_CLIENTS", "5"))

# ======================== FedAdam ========================
LR = float(os.environ.get("FEDADAM_LR", "0.0007"))
BETA1 = 0.9
BETA2 = 0.99
EPS = 1e-8
BASE_LAMBDA = 0.05
MAX_LAMBDA = 0.2

# ======================== Reputation ========================
LAMBDA_DEFENSE = 0.02
REWARD_ALPHA = 0.05
REP_MIN = 0.1
REP_MAX = 1.5
BASE_REWARD = 0.5
WARMUP_ROUNDS = 5

# ======================== Aggregation Method ========================
# Options: "reputation" (default), "krum", "trimmed_mean", "bulyan", "rfa"
AGGREGATION_METHOD = os.environ.get("AGGREGATION_METHOD", "reputation")

# Number of assumed Byzantine clients for Krum/Bulyan
NUM_BYZANTINE = int(os.environ.get("NUM_BYZANTINE", "1"))

# Trim ratio for Trimmed Mean aggregator
TRIM_RATIO = float(os.environ.get("TRIM_RATIO", "0.1"))

# Clip norm for RFA (Robust Federated Averaging)
RFA_CLIP_NORM = float(os.environ.get("RFA_CLIP_NORM", "1.0"))

# ======================== On-Chain Verification ========================
# Options: "off-chain" (default, existing behavior), "on-chain" (use verifyUpdateWithProof)
VERIFICATION_MODE = os.environ.get("VERIFICATION_MODE", "off-chain")

# ======================== Secure Aggregation ========================
SECURE_AGG_ENABLED = os.environ.get("SECURE_AGG_ENABLED", "0") == "1"

# ======================== Staking ========================
# Whether to use the StakingReputation contract instead of the basic Reputation contract
STAKING_ENABLED = os.environ.get("STAKING_ENABLED", "0") == "1"

# ======================== Training Verification ========================
TRAINING_VERIFICATION_ENABLED = os.environ.get("TRAINING_VERIFICATION_ENABLED", "0") == "1"
