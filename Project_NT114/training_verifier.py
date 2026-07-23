"""
Training correctness verification through cryptographic commitments.

Allows clients to prove they actually performed local training by committing
to training metadata (loss reduction, data root, learning rate, epochs).
The server can verify these commitments to detect free-rider attacks.

This module provides hash-based commitment schemes. For full ZK verification
of training correctness, these commitments serve as the public inputs to a
zkSNARK circuit (see prove_gradient_norm.circom for the norm-bound circuit).

Environment variables:
    TRAINING_VERIFICATION_ENABLED: '1' to enable (default '0')
"""

import hashlib
import json
import os

import numpy as np

# ======================== Configuration ========================

TRAINING_VERIFICATION_ENABLED = os.environ.get("TRAINING_VERIFICATION_ENABLED", "0") == "1"


# ======================== Parameter Hashing ========================

def hash_params(params):
    """
    Compute a deterministic SHA-256 hash of model parameters.

    Args:
        params: List[np.ndarray] - model parameters
    Returns:
        str - hex digest
    """
    digest = hashlib.sha256()
    for p in params:
        digest.update(str(p.dtype).encode("utf-8"))
        digest.update(str(p.shape).encode("utf-8"))
        digest.update(p.tobytes())
    return digest.hexdigest()


# ======================== Data Commitment (Merkle Tree) ========================

def _hash_batch(batch_data):
    """Hash a single data batch."""
    if isinstance(batch_data, np.ndarray):
        return hashlib.sha256(batch_data.tobytes()).hexdigest()
    return hashlib.sha256(str(batch_data).encode("utf-8")).hexdigest()


def _merkle_parent(left, right):
    """Compute the parent hash of two Merkle tree nodes."""
    combined = (left + right).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def compute_data_commitment(data_batches):
    """
    Compute a Merkle root over hashes of training data batches.

    This commitment allows the client to prove their training data hasn't
    changed between rounds without revealing the data itself.

    Args:
        data_batches: List[np.ndarray] - training data batches
    Returns:
        str - hex Merkle root hash
    """
    if not data_batches:
        return hashlib.sha256(b"empty").hexdigest()

    # Hash each batch as a leaf
    leaves = [_hash_batch(batch) for batch in data_batches]

    # Pad to power of 2
    while len(leaves) & (len(leaves) - 1) != 0:
        leaves.append(leaves[-1])

    # Build Merkle tree bottom-up
    current_level = leaves
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            next_level.append(_merkle_parent(left, right))
        current_level = next_level

    return current_level[0]


# ======================== Training Commitment ========================

def compute_training_commitment(global_params, local_params, loss_before,
                                loss_after, num_epochs, learning_rate):
    """
    Create a cryptographic commitment to the training process.

    Binds together: the global model received, the local model produced,
    loss before and after training, and hyperparameters. The server can
    verify this commitment to ensure the client actually trained.

    Args:
        global_params: List[np.ndarray] - global model received from server
        local_params: List[np.ndarray] - local model after training
        loss_before: float - loss on local data before training
        loss_after: float - loss on local data after training
        num_epochs: int - number of local training epochs
        learning_rate: float - local learning rate
    Returns:
        dict with commitment_hash, loss_before, loss_after, loss_decreased,
        num_epochs, lr, global_hash, local_hash
    """
    global_hash = hash_params(global_params)
    local_hash = hash_params(local_params)

    commitment_material = json.dumps({
        "global_hash": global_hash,
        "local_hash": local_hash,
        "loss_before": float(loss_before),
        "loss_after": float(loss_after),
        "num_epochs": int(num_epochs),
        "learning_rate": float(learning_rate),
    }, sort_keys=True, separators=(",", ":"))

    commitment_hash = hashlib.sha256(commitment_material.encode("utf-8")).hexdigest()

    return {
        "commitment_hash": commitment_hash,
        "global_hash": global_hash,
        "local_hash": local_hash,
        "loss_before": float(loss_before),
        "loss_after": float(loss_after),
        "loss_decreased": loss_after < loss_before,
        "num_epochs": int(num_epochs),
        "lr": float(learning_rate),
    }


def verify_training_commitment(commitment, global_params, local_params,
                                loss_before, loss_after, num_epochs,
                                learning_rate):
    """
    Verify a training commitment by recomputing the hash and checking properties.

    Args:
        commitment: dict - the commitment to verify (from compute_training_commitment)
        global_params: List[np.ndarray] - global model
        local_params: List[np.ndarray] - local model
        loss_before: float
        loss_after: float
        num_epochs: int
        learning_rate: float
    Returns:
        bool - True if the commitment is valid
    """
    expected = compute_training_commitment(
        global_params, local_params, loss_before, loss_after,
        num_epochs, learning_rate
    )

    if commitment.get("commitment_hash") != expected["commitment_hash"]:
        return False

    # Basic sanity: loss should decrease after honest training
    if not commitment.get("loss_decreased", False):
        print("⚠ Training commitment: loss did not decrease (possible free-rider)")
        # Don't reject outright — early rounds or hard data can cause this
        # But flag it for the reputation system

    return True


# ======================== Gradient Statistics ========================

def compute_gradient_statistics(global_params, local_params):
    """
    Compute statistics about the gradient (local - global) for auditing.

    These statistics can be logged, compared across clients, and used
    as additional inputs to defense mechanisms.

    Args:
        global_params: List[np.ndarray] - global model parameters
        local_params: List[np.ndarray] - local model parameters
    Returns:
        dict with gradient_norm, direction_hash, layer_norms, num_layers,
        max_layer_norm, min_layer_norm
    """
    gradients = [
        local_p - global_p
        for local_p, global_p in zip(local_params, global_params)
    ]

    # Overall gradient norm
    flat_gradient = np.concatenate([g.flatten() for g in gradients])
    gradient_norm = float(np.linalg.norm(flat_gradient))

    # Direction hash (gradient normalized to unit vector, then hashed)
    if gradient_norm > 1e-10:
        unit_gradient = flat_gradient / gradient_norm
        direction_hash = hashlib.sha256(unit_gradient.tobytes()).hexdigest()
    else:
        direction_hash = hashlib.sha256(b"zero_gradient").hexdigest()

    # Per-layer norms
    layer_norms = [float(np.linalg.norm(g)) for g in gradients]

    return {
        "gradient_norm": gradient_norm,
        "direction_hash": direction_hash,
        "layer_norms": layer_norms,
        "num_layers": len(gradients),
        "max_layer_norm": float(max(layer_norms)) if layer_norms else 0.0,
        "min_layer_norm": float(min(layer_norms)) if layer_norms else 0.0,
    }
