"""Statistics that separate an edge from a lucky backtest.

References: Bailey and Lopez de Prado, "The Deflated Sharpe Ratio" (2014) and Bailey et
al., "The Probability of Backtest Overfitting" (2017). Sharpe ratios here are per period,
not annualised, unless a name says otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, pairwise
from statistics import NormalDist

import numpy as np
from numpy.typing import NDArray

_NORMAL = NormalDist()
_EULER_GAMMA = 0.5772156649015329

Floats = NDArray[np.float64]


def sharpe(returns: Floats) -> float:
    deviation = float(np.std(returns, ddof=1))
    return float(np.mean(returns)) / deviation if deviation > 0 else 0.0


def skewness(returns: Floats) -> float:
    centred = returns - np.mean(returns)
    deviation = float(np.std(returns))
    return float(np.mean(centred**3)) / deviation**3 if deviation > 0 else 0.0


def kurtosis(returns: Floats) -> float:
    """Raw kurtosis: 3 for a normal distribution."""
    centred = returns - np.mean(returns)
    deviation = float(np.std(returns))
    return float(np.mean(centred**4)) / deviation**4 if deviation > 0 else 3.0


def probabilistic_sharpe(
    observed: float, benchmark: float, observations: int, skew: float, kurt: float
) -> float:
    """Probability the true Sharpe exceeds ``benchmark``, allowing for non-normal returns."""
    variance = 1 - skew * observed + (kurt - 1) / 4 * observed**2
    if variance <= 0 or observations < 2:
        return 0.0
    z = (observed - benchmark) * math.sqrt(observations - 1) / math.sqrt(variance)
    return _NORMAL.cdf(z)


def expected_max_sharpe(trials: int, sharpe_variance: float) -> float:
    """The best Sharpe that ``trials`` skill-free attempts would produce by luck alone."""
    if trials < 2:
        return 0.0
    first = (1 - _EULER_GAMMA) * _NORMAL.inv_cdf(1 - 1 / trials)
    second = _EULER_GAMMA * _NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    return math.sqrt(sharpe_variance) * (first + second)


def deflated_sharpe(
    observed: float,
    observations: int,
    skew: float,
    kurt: float,
    trials: int,
    sharpe_variance: float,
) -> float:
    """Probabilistic Sharpe against the luck benchmark for this many trials."""
    benchmark = expected_max_sharpe(trials, sharpe_variance)
    return probabilistic_sharpe(observed, benchmark, observations, skew, kurt)


@dataclass(frozen=True)
class Interval:
    low: float
    high: float


def bootstrap_sharpe_interval(
    returns: Floats,
    seed: int,
    resamples: int = 2000,
    block: int = 20,
    confidence: float = 0.95,
) -> Interval:
    """Stationary block bootstrap: blocks of random length keep autocorrelation intact."""
    rng = np.random.default_rng(seed)
    n = len(returns)
    restart = rng.random((resamples, n)) < 1 / block
    restart[:, 0] = True
    starts = rng.integers(0, n, size=(resamples, n))
    last_restart = np.maximum.accumulate(np.where(restart, np.arange(n), 0), axis=1)
    offset = np.arange(n) - last_restart
    origin = np.take_along_axis(starts, last_restart, axis=1)
    samples = returns[(origin + offset) % n]
    deviation = samples.std(axis=1, ddof=1)
    means = samples.mean(axis=1)
    values = np.divide(means, deviation, out=np.zeros_like(means), where=deviation > 0)
    tail = (1 - confidence) / 2
    low, high = np.quantile(values, [tail, 1 - tail])
    return Interval(float(low), float(high))


def probability_of_overfitting(trial_returns: Floats, blocks: int = 16) -> float:
    """PBO by combinatorially symmetric cross-validation.

    ``trial_returns`` has one column per trial. Every half of the time blocks takes a turn
    as the in-sample period. PBO is how often the in-sample winner lands in the bottom half
    out of sample. About 0.5 means the selection process is picking noise.
    """
    periods, trials = trial_returns.shape
    if trials < 2:
        raise ValueError("PBO needs at least two trials")
    blocks = min(blocks, periods // 2)
    blocks -= blocks % 2
    if blocks < 2:
        raise ValueError("too few periods for PBO")
    edges = np.linspace(0, periods, blocks + 1).astype(int)
    parts = [trial_returns[a:b] for a, b in pairwise(edges)]

    def scores(indices: list[int]) -> Floats:
        data = np.concatenate([parts[i] for i in indices])
        deviation = data.std(axis=0, ddof=1)
        means = data.mean(axis=0)
        result: Floats = np.divide(means, deviation, out=np.zeros(trials), where=deviation > 0)
        return result

    overfit = 0
    total = 0
    everything = set(range(blocks))
    for chosen in combinations(range(blocks), blocks // 2):
        inside = scores(list(chosen))
        outside = scores(sorted(everything - set(chosen)))
        winner = int(np.argmax(inside))
        # Average rank handles ties, so identical trials do not read as skill.
        below = float(np.sum(outside < outside[winner]))
        equal = float(np.sum(outside == outside[winner]))
        relative_rank = (below + (equal + 1) / 2) / (trials + 1)
        overfit += relative_rank <= 0.5
        total += 1
    return overfit / total
