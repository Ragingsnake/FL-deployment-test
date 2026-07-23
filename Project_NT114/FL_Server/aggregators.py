"""
Byzantine-resilient aggregation algorithms for federated learning.

Provides Multi-Krum, Trimmed Mean, Bulyan, and RFA (Robust Federated Averaging)
as alternatives to the default reputation-weighted aggregation. Each aggregator
operates on numpy arrays and returns a single aggregated update.

All aggregators follow the same interface:
    Input:  List of client updates, each being List[np.ndarray]
    Output: Single aggregated update as List[np.ndarray]
"""

import numpy as np
from typing import List, Callable, Optional, Tuple


# ======================== Helpers ========================

def flatten(update: List[np.ndarray]) -> Tuple[np.ndarray, List[Tuple[int, ...]]]:
    """Flatten a list of arrays into a single 1D vector and return shapes for unflattening."""
    if not update:
        return np.array([]), []
    shapes = [arr.shape for arr in update]
    flat = np.concatenate([arr.flatten() for arr in update])
    return flat, shapes


def unflatten(flat: np.ndarray, shapes: List[Tuple[int, ...]]) -> List[np.ndarray]:
    """Unflatten a 1D vector back into a list of arrays using the original shapes."""
    update = []
    idx = 0
    for shape in shapes:
        size = int(np.prod(shape))
        arr = flat[idx:idx + size].reshape(shape)
        update.append(arr)
        idx += size
    return update


# ======================== Multi-Krum ========================

def multi_krum(updates: List[List[np.ndarray]], num_byzantine: int = 1,
               num_select: int = 1, **kwargs) -> List[np.ndarray]:
    """
    Multi-Krum aggregation.

    For each update, computes the sum of squared distances to its
    (n - num_byzantine - 2) closest neighbors. Selects the `num_select`
    updates with the smallest scores and averages them.

    Reference:
        Blanchard et al., "Machine Learning with Adversaries: Byzantine
        Tolerant Gradient Descent" (NeurIPS 2017).

    Args:
        updates: List of client updates, each being List[np.ndarray].
        num_byzantine: Assumed number of Byzantine clients.
        num_select: Number of updates to select and average.
    Returns:
        Aggregated update as List[np.ndarray].
    """
    if not updates:
        raise ValueError("Updates list is empty.")

    n = len(updates)
    num_closest = max(1, n - num_byzantine - 2)

    flat_updates = []
    shapes = None
    for u in updates:
        flat, shp = flatten(u)
        if shapes is None:
            shapes = shp
        flat_updates.append(flat)

    flat_updates_arr = np.array(flat_updates)

    # Compute pairwise distances
    distances = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.linalg.norm(flat_updates_arr[i] - flat_updates_arr[j])
            distances[i, j] = dist
            distances[j, i] = dist

    # Krum scores: sum of distances to closest neighbors
    scores = np.zeros(n)
    for i in range(n):
        sorted_dists = np.sort(distances[i])
        scores[i] = np.sum(sorted_dists[1:num_closest + 1])

    selected_indices = np.argsort(scores)[:num_select]
    selected_updates = flat_updates_arr[selected_indices]

    avg_flat = np.mean(selected_updates, axis=0)
    return unflatten(avg_flat, shapes)


# ======================== Trimmed Mean ========================

def trimmed_mean(updates: List[List[np.ndarray]], trim_ratio: float = 0.1,
                 **kwargs) -> List[np.ndarray]:
    """
    Coordinate-wise trimmed mean aggregation.

    For each parameter coordinate, sorts the values across all clients,
    trims the top and bottom `trim_ratio` fraction, and averages the rest.

    Reference:
        Yin et al., "Byzantine-Robust Distributed Learning: Towards Optimal
        Statistical Rates" (ICML 2018).

    Args:
        updates: List of client updates, each being List[np.ndarray].
        trim_ratio: Fraction of extreme values to trim from each end.
    Returns:
        Aggregated update as List[np.ndarray].
    """
    if not updates:
        raise ValueError("Updates list is empty.")

    n = len(updates)
    trim_count = int(n * trim_ratio)

    agg_update = []
    for layer_idx in range(len(updates[0])):
        layer_arrays = np.stack([u[layer_idx] for u in updates], axis=0)
        layer_sorted = np.sort(layer_arrays, axis=0)

        if trim_count > 0 and 2 * trim_count < n:
            layer_trimmed = layer_sorted[trim_count:-trim_count]
        else:
            layer_trimmed = layer_sorted

        layer_mean = np.mean(layer_trimmed, axis=0)
        agg_update.append(layer_mean)

    return agg_update


# ======================== Bulyan ========================

def bulyan(updates: List[List[np.ndarray]], num_byzantine: int = 1,
           **kwargs) -> List[np.ndarray]:
    """
    Bulyan aggregation.

    Phase 1: Iteratively applies Multi-Krum to select (n - 2*num_byzantine)
             candidate updates.
    Phase 2: Applies coordinate-wise trimmed mean on the selected candidates.

    Reference:
        El Mhamdi et al., "The Hidden Vulnerability of Distributed Learning
        in Byzantium" (ICML 2018).

    Args:
        updates: List of client updates, each being List[np.ndarray].
        num_byzantine: Assumed number of Byzantine clients.
    Returns:
        Aggregated update as List[np.ndarray].
    """
    n = len(updates)
    theta = n - 2 * num_byzantine
    if theta <= 0:
        theta = max(1, n - 2)

    selected_updates = []
    remaining_indices = list(range(n))

    flat_updates = []
    shapes = None
    for u in updates:
        flat, shp = flatten(u)
        if shapes is None:
            shapes = shp
        flat_updates.append(flat)
    flat_updates_arr = np.array(flat_updates)

    # Phase 1: iterative Krum selection
    for _ in range(theta):
        current_n = len(remaining_indices)
        if current_n <= 1:
            selected_updates.append(updates[remaining_indices[0]])
            break

        if current_n <= num_byzantine * 2 + 2:
            num_closest = max(1, current_n - 2)
        else:
            num_closest = max(1, current_n - num_byzantine - 2)

        distances = np.zeros((current_n, current_n))
        for i in range(current_n):
            for j in range(i + 1, current_n):
                dist = np.linalg.norm(
                    flat_updates_arr[remaining_indices[i]] -
                    flat_updates_arr[remaining_indices[j]]
                )
                distances[i, j] = dist
                distances[j, i] = dist

        scores = np.zeros(current_n)
        for i in range(current_n):
            sorted_dists = np.sort(distances[i])
            scores[i] = np.sum(sorted_dists[1:num_closest + 1])

        best_local_idx = int(np.argmin(scores))
        best_global_idx = remaining_indices[best_local_idx]

        selected_updates.append(updates[best_global_idx])
        remaining_indices.pop(best_local_idx)

    if not selected_updates:
        return updates[0]

    # Phase 2: trimmed mean on selected candidates
    beta = num_byzantine
    trim_ratio = beta / len(selected_updates) if len(selected_updates) > 2 * beta else 0.0

    return trimmed_mean(selected_updates, trim_ratio=trim_ratio)


# ======================== Robust Federated Averaging (Geometric Median) ========================

def robust_federated_avg(updates: List[List[np.ndarray]],
                         weights: Optional[List[float]] = None,
                         clip_norm: float = 1.0, **kwargs) -> List[np.ndarray]:
    """
    Robust Federated Averaging using the Geometric Median (Weiszfeld's algorithm).

    Computes the weighted geometric median of client updates, which is
    inherently robust to outliers. Optionally clips per-update norms.

    Reference:
        Pillutla et al., "Robust Aggregation for Federated Learning"
        (IEEE TPAMI 2022).

    Args:
        updates: List of client updates, each being List[np.ndarray].
        weights: Optional list of floats for weighted geometric median.
        clip_norm: Maximum L2 norm for each update (0 to disable).
    Returns:
        Aggregated update as List[np.ndarray].
    """
    n = len(updates)
    if weights is None:
        weights = [1.0 / n] * n
    else:
        s = sum(weights)
        weights = [w / s for w in weights] if s > 0 else [1.0 / n] * n

    flat_updates = []
    shapes = None
    for u in updates:
        flat, shp = flatten(u)
        if shapes is None:
            shapes = shp

        if clip_norm > 0:
            norm = np.linalg.norm(flat)
            if norm > clip_norm:
                flat = flat * (clip_norm / norm)

        flat_updates.append(flat)

    flat_updates_arr = np.array(flat_updates)
    weights_arr = np.array(weights)

    # Initialize with weighted mean
    median = np.average(flat_updates_arr, axis=0, weights=weights_arr)

    # Weiszfeld iteration for geometric median
    max_iter = 10
    tol = 1e-5

    for _ in range(max_iter):
        distances = np.linalg.norm(flat_updates_arr - median, axis=1)
        distances = np.maximum(distances, 1e-10)

        new_weights = weights_arr / distances
        new_weights_sum = np.sum(new_weights)
        if new_weights_sum > 0:
            new_weights = new_weights / new_weights_sum

        new_median = np.average(flat_updates_arr, axis=0, weights=new_weights)

        if np.linalg.norm(new_median - median) < tol:
            median = new_median
            break

        median = new_median

    return unflatten(median, shapes)


# ======================== Reputation-Weighted Average ========================

def reputation_weighted_avg(updates: List[List[np.ndarray]],
                            weights: List[float] = None, **kwargs) -> List[np.ndarray]:
    """
    Simple weighted average using reputation scores as weights.

    This is a clean reimplementation of the existing reputation-based
    aggregation logic, provided for benchmark comparison against the
    Byzantine-resilient alternatives.

    Args:
        updates: List of client updates, each being List[np.ndarray].
        weights: Reputation-based weights for each client.
    Returns:
        Aggregated update as List[np.ndarray].
    """
    if not updates:
        raise ValueError("Updates list is empty.")

    n = len(updates)
    if weights is None:
        weights = [1.0 / n] * n
    else:
        s = sum(weights)
        norm_weights = [w / s for w in weights] if s > 0 else [1.0 / n] * n
        weights = norm_weights

    agg_update = []
    for layer_idx in range(len(updates[0])):
        layer_arrays = np.stack([u[layer_idx] for u in updates], axis=0)
        layer_mean = np.average(layer_arrays, axis=0, weights=weights)
        agg_update.append(layer_mean)

    return agg_update


# ======================== Registry ========================

AVAILABLE_AGGREGATORS = [
    "krum",
    "trimmed_mean",
    "bulyan",
    "rfa",
    "reputation",
]

_AGGREGATOR_REGISTRY = {
    "krum": multi_krum,
    "multi_krum": multi_krum,
    "trimmed_mean": trimmed_mean,
    "bulyan": bulyan,
    "rfa": robust_federated_avg,
    "robust_federated_avg": robust_federated_avg,
    "reputation": reputation_weighted_avg,
    "reputation_weighted_avg": reputation_weighted_avg,
}


def get_aggregator(name: str) -> Callable:
    """
    Return the aggregator function for the given name.

    Args:
        name: One of 'krum', 'trimmed_mean', 'bulyan', 'rfa', 'reputation'.
    Returns:
        The aggregator callable.
    Raises:
        ValueError if the name is not recognized.
    """
    fn = _AGGREGATOR_REGISTRY.get(name.lower())
    if fn is None:
        raise ValueError(
            f"Aggregator '{name}' not found. Available: {AVAILABLE_AGGREGATORS}"
        )
    return fn
