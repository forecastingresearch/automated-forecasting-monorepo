"""Five quantiles -> a distribution to draw from: the five-term metalog, with a fallback.

The metalog (Keelin 2016, "The Metalog Distributions", Decision Analysis
13(4)) is a quantile function linear in its coefficients a1..a5:

    M(y) = a1 + a2 L + a3 (y - 1/2) L + a4 (y - 1/2) + a5 (y - 1/2)^2,   L = ln(y / (1 - y))

Five terms through five quantiles is a square system, so the fit passes
through every stated quantile exactly. It is fitted on a transformed scale
(log-odds for a share, log for a positive quantity), so draws respect the
bounds. A metalog fitted this way need not be increasing; where it is not
(checked on a fine grid), the fallback is straight lines between the five
points against their normal scores, extended beyond the 5th and 95th
percentiles along the end segments' slopes, as the design note specifies.

Not derived from the paper's mbf_core.py, which is unchecked.
"""
from statistics import NormalDist

import numpy as np

TRANSFORMS = ("none", "log", "logit")
GRID = np.concatenate([np.linspace(1e-4, 0.01, 50), np.linspace(0.01, 0.99, 981)[1:-1], np.linspace(0.99, 1 - 1e-4, 50)])


def basis(y):
    """The five basis functions at probabilities y -> (..., 5)."""
    y = np.asarray(y, dtype=float)
    L, c = np.log(y / (1 - y)), y - 0.5
    return np.stack([np.ones_like(y), L, c * L, c, c * c], axis=-1)


def forward(x, transform):
    """Natural scale -> the unbounded scale the fit lives on. `transform`: an array of codes (TRANSFORMS index)."""
    x = np.asarray(x, dtype=float)
    t = np.broadcast_to(np.asarray(transform)[..., None] if np.ndim(transform) else transform, x.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(t == 1, np.log(x), np.where(t == 2, np.log(x / (1 - x)), x))


def inverse(z, transform):
    """The fit's scale -> natural, for draws shaped (worlds, items) and `transform` shaped (items,)."""
    t = np.asarray(transform)
    with np.errstate(over="ignore"):
        return np.where(t == 1, np.exp(z), np.where(t == 2, 1 / (1 + np.exp(-z)), z))


class Fit:
    """Many quantile sets at once.

    q: (n, 5) quantiles at `probs` on the natural scale; transform: (n,) codes.
    .coef (n, 5) the metalog coefficients; .metalog (n,) whether the metalog is
    used (increasing on GRID), else the fallback.
    """

    def __init__(self, q, transform, probs=(0.05, 0.25, 0.5, 0.75, 0.95)):
        self.probs = np.asarray(probs, dtype=float)
        self.transform = np.asarray(transform)
        self.x = forward(np.asarray(q, dtype=float), self.transform)          # (n, 5)
        if not np.all(np.isfinite(self.x)):
            raise ValueError("a quantile is outside its transform's domain")
        if np.any(np.diff(self.x, axis=1) <= 0):
            raise ValueError("quantiles must be strictly increasing")
        self.coef = np.linalg.solve(basis(self.probs), self.x.T).T          # (n, 5)
        on_grid = self.coef @ basis(GRID).T                                    # (n, grid)
        self.metalog = np.all(np.diff(on_grid, axis=1) > 0, axis=1)
        self.z = np.array([NormalDist().inv_cdf(p) for p in self.probs])

    @property
    def fallback_rate(self):
        return float(1 - self.metalog.mean()) if len(self.metalog) else 0.0

    def _meta(self, u):
        """The metalog at u (worlds, n), term by term (no (worlds, n, 5) array)."""
        a = self.coef
        L, c = np.log(u / (1 - u)), u - 0.5
        return a[:, 0] + a[:, 1] * L + a[:, 2] * c * L + a[:, 3] * c + a[:, 4] * c * c

    def quantile(self, u):
        """The quantile function at probabilities u, shaped (worlds, n) -> natural scale."""
        u = np.asarray(u, dtype=float)
        meta = self._meta(u)
        fb = self._fallback(np.vectorize(NormalDist().inv_cdf)(u)) if not self.metalog.all() else meta
        return inverse(np.where(self.metalog, meta, fb), self.transform)

    def _fallback(self, z):
        """Piecewise linear in normal scores z (worlds, n), extended along the end slopes."""
        zk, x = self.z, self.x
        seg = np.clip(np.searchsorted(zk, z, side="right") - 1, 0, len(zk) - 2)  # (worlds, n)
        n = np.arange(x.shape[0])
        x0, x1 = x[n, seg], x[n, seg + 1]
        z0, z1 = zk[seg], zk[seg + 1]
        return x0 + (z - z0) * (x1 - x0) / (z1 - z0)

    def draw(self, rng, worlds):
        """`worlds` independent draws of every item -> (worlds, n), natural scale.

        Metalog items are drawn by inverse transform from u ~ U(0, 1); the
        fallback's from z ~ N(0, 1) directly (the same distribution, without
        an inverse normal over millions of draws)."""
        n = len(self.metalog)
        meta = self._meta(rng.uniform(1e-9, 1 - 1e-9, size=(worlds, n)))
        if self.metalog.all():
            return inverse(meta, self.transform)
        fb = self._fallback(rng.standard_normal((worlds, n)))
        return inverse(np.where(self.metalog, meta, fb), self.transform)


def pinball(q, x, probs=(0.05, 0.25, 0.5, 0.75, 0.95)):
    """The mean pinball loss of quantiles q (..., 5) against outcomes x (...)."""
    q, x, p = np.asarray(q, float), np.asarray(x, float)[..., None], np.asarray(probs, float)
    return np.mean(np.maximum(p * (x - q), (p - 1) * (x - q)), axis=-1)
