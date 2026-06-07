import numpy as np
from FL_Server.config import REWARD_ALPHA, REP_MIN, REP_MAX, BASE_REWARD

class ReputationManager:

    def __init__(self):
        self.reputation = {}

    def get(self, client_id):
        if client_id not in self.reputation:
            self.reputation[client_id] = BASE_REWARD
        return self.reputation[client_id]

    def reward(self, client_id, gamma):
        r_old = self.get(client_id)
        reward_signal = gamma - 0.3

        r_new = r_old + REWARD_ALPHA * reward_signal
        r = np.clip(r_new, REP_MIN, REP_MAX)
        self.reputation[client_id] = float(r)

    def penalize(self, client_id):
        r = self.get(client_id)

        r = r * 0.85
        r = np.clip(r, REP_MIN, REP_MAX)
        self.reputation[client_id] = float(r)

    def update_reputation(self, client_id, delta):
        r = self.get(client_id)

        r = r + REWARD_ALPHA * delta
        r = np.clip(r, REP_MIN, REP_MAX)
        self.reputation[client_id] = float(r)


reputation_manager = ReputationManager()