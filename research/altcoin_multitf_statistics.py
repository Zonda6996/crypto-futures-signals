"""Statistical machinery for ALTCOIN_MULTITF_005 Phase 4 Part 2.

Pure standard-library implementations of the frozen-protocol statistics:
- SPA (Hansen 2005 superior predictive ability) with stationary bootstrap,
- Deflated Sharpe Ratio probability (Bailey & Lopez de Prado) using the effective
  number of trials taken as the complete valid search space,
- Holm step-down multiple-testing correction,
- seeded circular block-bootstrap confidence intervals.

All randomness flows through :class:`random.Random` seeded exclusively with the
frozen protocol seeds, so results are deterministic across runs and platforms.
"""
from __future__ import annotations

import math
from random import Random
from typing import Mapping, Sequence

SQRT_TWO = math.sqrt(2.0)
EULER_GAMMA = 0.5772156649015329


def normal_cdf(z: float) -> float:
    if math.isnan(z):
        raise ValueError("normal_cdf input must be finite")
    return 0.5 * math.erfc(-z / SQRT_TWO)


def normal_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, |eps|<1.15e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("normal_ppf requires 0 < p < 1")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1-p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def moments(values: Sequence[float]) -> tuple[float, float, float, float]:
    """Population central moments (mean, m2, skew gamma3, kurtosis gamma4)."""
    n = len(values)
    if n == 0:
        raise ValueError("empty series")
    mean = math.fsum(values) / n
    if n < 2:
        return mean, 0.0, 0.0, 0.0
    m2 = math.fsum((v - mean) ** 2 for v in values) / n
    if m2 == 0:
        return mean, 0.0, 0.0, 0.0
    m3 = math.fsum((v - mean) ** 3 for v in values) / n
    m4 = math.fsum((v - mean) ** 4 for v in values) / n
    return mean, m2, m3 / m2**1.5, m4 / (m2 * m2)


def sharpe_ratio(values: Sequence[float]) -> float | None:
    """Sample (ddof=1) Sharpe of a return series; None when undefined."""
    n = len(values)
    if n < 2:
        return None
    mean = math.fsum(values) / n
    var = math.fsum((v - mean) ** 2 for v in values) / (n - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var)


def newey_west_lrv(values: Sequence[float], lag: int) -> float:
    """Bartlett-kernel long-run variance estimate."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = math.fsum(values) / n
    centered = [v - mean for v in values]
    lrv = math.fsum(c * c for c in centered) / n
    for l in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - l / (lag + 1)
        cov = math.fsum(centered[t] * centered[t - l] for t in range(l, n)) / n
        lrv += 2.0 * weight * cov
    return lrv


def nw_lag(length: int) -> int:
    """Deterministic Newey-West lag rule floor(T^(1/3))."""
    return max(1, int(round(length ** (1.0 / 3.0))))


def studentized_statistic(values: Sequence[float], lag: int) -> float | None:
    """sqrt(T) * mean / omega_hat; None when the series has no dispersion."""
    n = len(values)
    if n < 2:
        return None
    lrv = newey_west_lrv(values, lag)
    if lrv <= 0:
        return None
    mean = math.fsum(values) / n
    return math.sqrt(n) * mean / math.sqrt(lrv)


def spa_pvalues(
    panel: Mapping[str, Sequence[float]],
    *,
    replicates: int,
    seed: int,
    lag: int | None = None,
) -> dict[str, float]:
    """Hansen (2005) SPA p-values under the null ``E[r_k] <= 0 for all k``.

    Uses the stationary bootstrap with mean block length ``lag`` and Hansen's
    moment screening of irrelevant configurations. The returned value per key is
    the consistent (recentered) SPA p-value; zero-dispersion columns receive 1.0.
    """
    keys = sorted(panel)
    if not keys:
        return {}
    lengths = {len(series) for series in panel.values()}
    if len(lengths) != 1:
        raise ValueError("SPA panel requires a balanced panel")
    horizon = lengths.pop()
    if horizon < 4:
        return {key: 1.0 for key in keys}
    q = lag if lag is not None else nw_lag(horizon)
    kappa = math.sqrt(2.0 * math.log(math.log(horizon)))
    observed: dict[str, float] = {}
    for key in keys:
        stat = studentized_statistic(panel[key], q)
        observed[key] = 1.0 if stat is None else stat
    relevant = [key for key in keys if observed[key] > -kappa and observed[key] != 1.0]
    result = {key: 1.0 for key in keys}
    if not relevant:
        return result
    rng = Random(seed)
    jump_probability = 1.0 / q
    prefixes: dict[str, list[float]] = {}
    omegas: dict[str, float] = {}
    means: dict[str, float] = {}
    for key in relevant:
        series = panel[key]
        mean = math.fsum(series) / horizon
        demeaned = [v - mean for v in series]
        prefix = [0.0]
        acc = 0.0
        for value in demeaned:
            acc += value
            prefix.append(acc)
        prefixes[key] = prefix
        omegas[key] = math.sqrt(newey_west_lrv(series, q))
        means[key] = mean
    counts = {key: 0 for key in relevant}
    scale = math.sqrt(horizon) / horizon
    for _ in range(replicates):
        position = 0
        totals = dict.fromkeys(relevant, 0.0)
        while position < horizon:
            start = rng.randrange(horizon)
            u = rng.random()
            block = 1 + int(math.log(1.0 - u) / math.log(1.0 - jump_probability)) if u > 0 else q
            remaining = horizon - position
            if block > remaining:
                block = remaining
            end = start + block
            if end <= horizon:
                for key in relevant:
                    prefix = prefixes[key]
                    totals[key] += prefix[end] - prefix[start]
            else:
                wrapped = end - horizon
                for key in relevant:
                    prefix = prefixes[key]
                    totals[key] += (prefix[horizon] - prefix[start]) + prefix[wrapped]
            position += block
        best = -math.inf
        for key in relevant:
            stat = scale * totals[key] / omegas[key]
            if stat > best:
                best = stat
        for key in relevant:
            if best >= observed[key]:
                counts[key] += 1
    for key, count in counts.items():
        result[key] = count / replicates
    return result


def holm_adjusted(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values preserving monotonicity."""
    items = sorted(pvalues.items(), key=lambda kv: (kv[1], kv[0]))
    total = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (key, value) in enumerate(items):
        candidate = (total - rank) * value
        running = max(running, candidate)
        adjusted[key] = min(1.0, running)
    return adjusted


def deflated_sharpe_probability(
    sharpe: float,
    returns: Sequence[float],
    trials: int,
    sharpe_variance: float,
) -> float:
    """Probability that the true Sharpe exceeds the expected max under ``trials``."""
    if trials < 1 or len(returns) < 4:
        return 0.0
    expected_max = math.sqrt(max(sharpe_variance, 0.0)) * (
        (1 - EULER_GAMMA) * normal_ppf(1 - 1.0 / trials)
        + EULER_GAMMA * normal_ppf(1 - 1.0 / (trials * math.e))
    )
    _, m2, skew, kurtosis = moments(returns)
    if m2 <= 0:
        return 0.0
    denominator = 1 - skew * sharpe + ((kurtosis - 1) / 4.0) * sharpe * sharpe
    if denominator <= 0:
        return 0.0
    observations = len(returns)
    statistic = (sharpe - expected_max) * math.sqrt(observations - 1) / math.sqrt(denominator)
    return normal_cdf(statistic)


def circular_block_bootstrap_mean_ci(
    values: Sequence[float],
    *,
    replicates: int,
    seed: int,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Circular block-bootstrap CI for the mean of ``values`` (deterministic)."""
    n = len(values)
    if n == 0:
        raise ValueError("empty series")
    block = max(1, int(round(n ** (1.0 / 3.0))))
    rng = Random(seed)
    prefix = [0.0]
    acc = 0.0
    for value in values:
        acc += value
        prefix.append(acc)

    def circ_sum(start: int, length: int) -> float:
        end = start + length
        if end <= n:
            return prefix[end] - prefix[start]
        return (prefix[n] - prefix[start]) + prefix[end - n]

    jump_probability = 1.0 / block
    stats: list[float] = []
    for _ in range(replicates):
        position = 0
        total = 0.0
        while position < n:
            start = rng.randrange(n)
            u = rng.random()
            length = 1 + int(math.log(1.0 - u) / math.log(1.0 - jump_probability)) if u > 0 else block
            remaining = n - position
            if length > remaining:
                length = remaining
            total += circ_sum(start, length)
            position += length
        stats.append(total / n)
    stats.sort()
    alpha = 1 - confidence
    lower_index = int(alpha / 2 * replicates)
    upper_index = int((1 - alpha / 2) * replicates) - 1
    return {
        "lower": stats[min(lower_index, replicates - 1)],
        "upper": stats[max(upper_index, 0)],
        "mean": math.fsum(stats) / replicates,
        "block_length": float(block),
        "replicates": float(replicates),
    }
