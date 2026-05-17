ROUNDS = 50
NUM_CLIENTS = 5

LR = 0.0003          # was 0.0007 — too high, caused divergence after round 17
BETA1 = 0.9
BETA2 = 0.99
EPS = 1e-8
BASE_LAMBDA = 0.05
MAX_LAMBDA = 0.2

LAMBDA_DEFENSE = 0.02
REWARD_ALPHA = 0.05
REP_MIN = 0.1
REP_MAX = 1.5
BASE_REWARD = 0.5
WARMUP_ROUNDS = 5    # now actually used in strategy.py