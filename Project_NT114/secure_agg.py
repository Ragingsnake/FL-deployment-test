"""
Secure aggregation via additive masking for federated learning.

Implements pairwise mask generation so that:
  - Each client adds a random mask to their model update before sending.
  - Masks are designed to cancel out when summed across all clients.
  - The server can recover the true aggregate without seeing individual updates.

In a real deployment, shared secrets would use Diffie-Hellman key exchange.
Here we simulate deterministic shared secrets for the experimental setup.

Environment variables:
    SECURE_AGG_ENABLED: '1' to enable (default '0')
    SECURE_AGG_SEED_BASE: Base seed for PRNG (default 42)
"""

import hashlib
import os
import struct

import numpy as np

# ======================== Configuration ========================

SECURE_AGG_ENABLED = os.environ.get("SECURE_AGG_ENABLED", "0") == "1"
SECURE_AGG_SEED_BASE = int(os.environ.get("SECURE_AGG_SEED_BASE", "42"))


# ======================== Shared Secret Generation ========================

def generate_shared_secret(client_id, peer_id):
    """
    Generate a deterministic shared secret between two clients.

    In a real deployment this would use Diffie-Hellman key exchange.
    Here we simulate it with HKDF-like construction from client IDs
    for reproducibility in experiments.

    Args:
        client_id: int - first client ID
        peer_id: int - second client ID
    Returns:
        bytes - 32-byte shared secret
    """
    # Ensure symmetry: secret(A,B) == secret(B,A)
    pair = tuple(sorted([int(client_id), int(peer_id)]))
    material = f"FL-SecAgg-{SECURE_AGG_SEED_BASE}-{pair[0]}-{pair[1]}".encode("utf-8")
    return hashlib.sha256(material).digest()


# ======================== Mask Generation ========================

def _seed_from_secret(secret_bytes, client_id, peer_id):
    """Derive a deterministic PRNG seed from a shared secret and client IDs."""
    material = secret_bytes + struct.pack(">II", min(client_id, peer_id), max(client_id, peer_id))
    digest = hashlib.sha256(material).digest()
    # Use first 4 bytes as a 32-bit seed
    return struct.unpack(">I", digest[:4])[0]


def generate_mask_pair(shapes, client_id, peer_id, shared_secret):
    """
    Generate a pairwise mask between two clients.

    The mask is added by the lower-ID client and subtracted by the
    higher-ID client, so masks cancel when updates are summed.

    Args:
        shapes: List[Tuple] - shapes of each parameter array
        client_id: int - this client's ID
        peer_id: int - the peer client's ID
        shared_secret: bytes - shared secret between the two clients
    Returns:
        List[np.ndarray] - mask arrays (positive for lower ID, negative for higher)
    """
    seed = _seed_from_secret(shared_secret, client_id, peer_id)
    rng = np.random.RandomState(seed)

    sign = 1.0 if int(client_id) < int(peer_id) else -1.0

    mask = []
    for shape in shapes:
        m = rng.randn(*shape).astype(np.float32) * 0.01  # Small mask magnitude
        mask.append(m * sign)

    return mask


def generate_client_mask(shapes, client_id, all_client_ids):
    """
    Generate the total mask for a client by summing pairwise masks with all peers.

    The pairwise masks are constructed so that for any pair (i, j):
      mask_i(j) = -mask_j(i)
    Therefore when all clients' masked updates are summed, the masks cancel.

    Args:
        shapes: List[Tuple] - shapes of each parameter array
        client_id: int - this client's ID
        all_client_ids: List[int] - all client IDs in the round
    Returns:
        List[np.ndarray] - total mask for this client
    """
    total_mask = [np.zeros(shape, dtype=np.float32) for shape in shapes]

    for peer_id in all_client_ids:
        if int(peer_id) == int(client_id):
            continue

        secret = generate_shared_secret(client_id, peer_id)
        pairwise_mask = generate_mask_pair(shapes, client_id, peer_id, secret)

        for i in range(len(total_mask)):
            total_mask[i] += pairwise_mask[i]

    return total_mask


# ======================== Masking / Unmasking ========================

def mask_update(params, mask):
    """
    Apply a mask to model parameters (element-wise addition).

    Args:
        params: List[np.ndarray] - original model parameters
        mask: List[np.ndarray] - mask arrays
    Returns:
        List[np.ndarray] - masked parameters
    """
    return [p + m for p, m in zip(params, mask)]


def unmask_aggregate(masked_sum, num_clients):
    """
    Recover the true aggregate from the sum of masked updates.

    If all clients participate and masks cancel perfectly, the masked_sum
    already contains the true sum. We just divide by num_clients to get
    the average.

    Args:
        masked_sum: List[np.ndarray] - element-wise sum of all masked updates
        num_clients: int - number of participating clients
    Returns:
        List[np.ndarray] - unmasked average update
    """
    return [s / max(num_clients, 1) for s in masked_sum]


# ======================== Dropout Handling ========================

def compute_dropout_correction(shapes, participating_ids, all_client_ids):
    """
    If some clients drop out, their masks don't cancel. This function
    computes the correction term to remove the uncanceled masks.

    In practice, dropped-out clients' shared secrets must be reconstructable
    (e.g., via Shamir secret sharing). Here we simulate direct reconstruction.

    Args:
        shapes: List[Tuple] - shapes of each parameter array
        participating_ids: List[int] - IDs of clients that actually submitted
        all_client_ids: List[int] - all expected client IDs
    Returns:
        List[np.ndarray] - correction mask to subtract from the sum
    """
    dropped_ids = set(int(c) for c in all_client_ids) - set(int(c) for c in participating_ids)

    if not dropped_ids:
        return [np.zeros(shape, dtype=np.float32) for shape in shapes]

    correction = [np.zeros(shape, dtype=np.float32) for shape in shapes]

    for dropped_id in dropped_ids:
        # Reconstruct the dropped client's mask contribution to each participating client
        dropped_mask = generate_client_mask(shapes, dropped_id, all_client_ids)
        for i in range(len(correction)):
            correction[i] += dropped_mask[i]

    return correction
