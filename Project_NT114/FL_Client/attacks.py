"""
Advanced Byzantine attack strategies for federated learning research.

Each attack operates on model parameters represented as List[np.ndarray]
and returns corrupted parameters in the same format.

Environment variables:
    DEMO_ATTACK_TYPE: str - 'backdoor', 'freerider', 'sybil', 'collusion', 'signflip'
    DEMO_ATTACK_SCALE: float - attack intensity (default varies per attack)
    DEMO_ATTACK_CLIENTS: str - comma-separated client IDs to attack
    DEMO_ATTACK_START_ROUND: int - first round to activate (default 1)
    DEMO_ATTACK_END_ROUND: int - last round to activate (default 999999)
"""

import os
import hashlib
import numpy as np


# ======================== Module-level state ========================
_SYBIL_DIRECTION = None  # Cached direction vector for coordinated Sybil drift


# ======================== Attack implementations ========================

def backdoor_attack(params, target_label=7, source_label=1, poison_ratio=None):
    """
    Targeted backdoor / label-flipping attack.

    Subtly modifies the last fully-connected layer weights to encourage
    misclassification of `source_label` as `target_label`. The perturbation
    is scaled to stay within `poison_ratio` of the original parameter norms,
    making it harder for norm-based defenses to detect.

    Reference: Bagdasaryan et al., "How To Back Door Federated Learning" (AISTATS 2020).

    Args:
        params: List[np.ndarray] - model parameters
        target_label: int - the label the attacker wants inputs classified as
        source_label: int - the label the attacker wants to hijack
        poison_ratio: float - perturbation scale relative to param norm (default 0.1)
    Returns:
        List[np.ndarray] - corrupted parameters
    """
    if poison_ratio is None:
        poison_ratio = float(os.environ.get("DEMO_ATTACK_SCALE", "0.1"))

    corrupted = [p.copy() for p in params]

    # Target the last weight matrix (fc2.weight in the CNN)
    # In the CNN model: conv1.weight, conv1.bias, conv2.weight, conv2.bias,
    #                   fc1.weight, fc1.bias, fc2.weight, fc2.bias
    # fc2.weight is params[-2], fc2.bias is params[-1]
    if len(corrupted) >= 2:
        fc_weight = corrupted[-2]  # shape: (num_classes, hidden_dim)
        fc_bias = corrupted[-1]    # shape: (num_classes,)

        if fc_weight.ndim == 2 and fc_weight.shape[0] > max(target_label, source_label):
            # Boost the target_label row and suppress the source_label row
            weight_norm = np.linalg.norm(fc_weight) + 1e-10
            perturbation_scale = weight_norm * poison_ratio

            # Swap influence: make source_label inputs activate target_label output
            direction = fc_weight[source_label] - fc_weight[target_label]
            direction_norm = np.linalg.norm(direction) + 1e-10
            direction = direction / direction_norm

            fc_weight[target_label] += perturbation_scale * direction
            fc_weight[source_label] -= perturbation_scale * direction * 0.5

            if fc_bias.ndim == 1 and len(fc_bias) > max(target_label, source_label):
                bias_shift = np.abs(fc_bias).mean() * poison_ratio
                fc_bias[target_label] += bias_shift
                fc_bias[source_label] -= bias_shift * 0.5

        corrupted[-2] = fc_weight
        corrupted[-1] = fc_bias

    return corrupted


def free_rider_attack(params, global_params=None, noise_scale=None):
    """
    Free-rider attack: the client skips training and returns the global model
    with negligible noise, contributing nothing while still receiving the
    aggregated global model.

    Reference: Lin et al., "Free-rider Attacks on Model Aggregation in
    Federated Learning" (AISTATS 2019).

    Args:
        params: List[np.ndarray] - local model parameters (ignored)
        global_params: List[np.ndarray] - global model parameters received from server
        noise_scale: float - magnitude of cosmetic noise (default 0.001)
    Returns:
        List[np.ndarray] - global params with tiny noise
    """
    if noise_scale is None:
        noise_scale = float(os.environ.get("DEMO_ATTACK_SCALE", "0.001"))

    base = global_params if global_params is not None else params
    corrupted = []
    for p in base:
        noise = np.random.normal(0, noise_scale, p.shape).astype(p.dtype)
        corrupted.append(p + noise)
    return corrupted


def sybil_attack(params, sybil_target_direction=None, drift_scale=None):
    """
    Coordinated Sybil drift attack: shifts all parameters slightly toward
    a shared target direction vector. When multiple Sybil clients participate,
    the individual drifts are small enough to evade per-client outlier detection
    but their cumulative effect shifts the global model.

    The direction is cached at module level so all Sybil clients in the same
    process drift consistently.

    Reference: Fung et al., "Mitigating Sybils in Federated Learning Poisoning"
    (arXiv 2019).

    Args:
        params: List[np.ndarray] - model parameters
        sybil_target_direction: List[np.ndarray] or None - shared drift direction
        drift_scale: float - magnitude of drift (default 0.05)
    Returns:
        List[np.ndarray] - parameters shifted toward the Sybil direction
    """
    global _SYBIL_DIRECTION

    if drift_scale is None:
        drift_scale = float(os.environ.get("DEMO_ATTACK_SCALE", "0.05"))

    if sybil_target_direction is not None:
        _SYBIL_DIRECTION = sybil_target_direction
    elif _SYBIL_DIRECTION is None or len(_SYBIL_DIRECTION) != len(params):
        # Generate a deterministic random direction (seeded for reproducibility)
        seed = int(os.environ.get("DEMO_SYBIL_SEED", "12345"))
        rng = np.random.RandomState(seed)
        _SYBIL_DIRECTION = []
        for p in params:
            direction = rng.randn(*p.shape).astype(p.dtype)
            norm = np.linalg.norm(direction) + 1e-10
            _SYBIL_DIRECTION.append(direction / norm)

    corrupted = []
    for p, d in zip(params, _SYBIL_DIRECTION):
        param_norm = np.linalg.norm(p) + 1e-10
        corrupted.append(p + drift_scale * param_norm * d)

    return corrupted


def collusion_attack(params, global_params=None, num_colluders=2, target_shift=None):
    """
    Collusion attack: coordinated poisoners shift updates just enough to
    stay inside IQR bounds while pulling the model in a target direction.
    The shift is calibrated as a fraction of the global weight norm.

    Args:
        params: List[np.ndarray] - local model parameters after training
        global_params: List[np.ndarray] - global model parameters
        num_colluders: int - number of colluding clients (for scaling)
        target_shift: float - fraction of global norm to shift (default 0.03)
    Returns:
        List[np.ndarray] - subtly shifted parameters
    """
    if target_shift is None:
        target_shift = float(os.environ.get("DEMO_ATTACK_SCALE", "0.03"))

    base = global_params if global_params is not None else params

    # Compute the legitimate delta
    corrupted = []
    seed = int(os.environ.get("DEMO_SYBIL_SEED", "12345"))
    rng = np.random.RandomState(seed)

    for p_local, p_global in zip(params, base):
        delta = p_local - p_global
        delta_norm = np.linalg.norm(delta) + 1e-10

        # Generate a consistent adversarial direction
        adv_direction = rng.randn(*p_local.shape).astype(p_local.dtype)
        adv_direction = adv_direction / (np.linalg.norm(adv_direction) + 1e-10)

        # Scale the adversarial shift to be a fraction of the legitimate delta
        # This keeps it inside statistical bounds
        adv_shift = adv_direction * delta_norm * target_shift / max(num_colluders, 1)

        corrupted.append(p_local + adv_shift)

    return corrupted


def sign_flip_attack(params, scale=None):
    """
    Sign-flip attack: negates all parameter values, effectively reversing
    the gradient direction and pushing the model away from convergence.

    This is a simple but effective untargeted attack.

    Reference: Li et al., "RSA: Byzantine-Robust Stochastic Aggregation Methods"
    (AAAI 2019).

    Args:
        params: List[np.ndarray] - model parameters
        scale: float - multiplier for the negation (default -1.0)
    Returns:
        List[np.ndarray] - negated parameters
    """
    if scale is None:
        scale = float(os.environ.get("DEMO_ATTACK_SCALE", "-1.0"))

    return [p * scale for p in params]


# ======================== Attack dispatcher ========================

_ATTACK_REGISTRY = {
    "backdoor": backdoor_attack,
    "freerider": free_rider_attack,
    "sybil": sybil_attack,
    "collusion": collusion_attack,
    "signflip": sign_flip_attack,
}


def get_attack_fn(attack_name):
    """
    Return the attack function for the given name.

    Args:
        attack_name: str - one of 'backdoor', 'freerider', 'sybil', 'collusion', 'signflip'
    Returns:
        callable - the attack function
    Raises:
        ValueError - if attack_name is not recognized
    """
    fn = _ATTACK_REGISTRY.get(attack_name.lower())
    if fn is None:
        raise ValueError(
            f"Unknown attack type '{attack_name}'. "
            f"Available: {list(_ATTACK_REGISTRY.keys())}"
        )
    return fn
