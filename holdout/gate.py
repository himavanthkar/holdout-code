"""Parameter-free Ladder (Blum & Hardt, ICML 2015, arXiv 1502.04585, Figure 2 / Sec. 4).

    R_0 <- inf, l_0 <- (0)_n
    for each submission f_t:
        l_t <- per-example loss vector of f_t on the holdout
        s   <- sample std (ddof=1) of (l_t - l_{t-1})        # l_{t-1} = last ACCEPTED vector
        if R_S(f_t) < R_{t-1} - s / sqrt(n):                # strict; R_{t-1} is the last REPORTED score
            R_t <- [R_S(f_t)]_{1/n}                         # round to nearest multiple of 1/n; keep l_t
        else:
            R_t <- R_{t-1};  l_t <- l_{t-1}
        output R_t

Here a loss is 1 if the task fails its hidden (plus) tests, else 0, on the audit pool. The caller only ever sees
(accepted, reported score): never per-task results, never the unrounded loss.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


@dataclass
class Verdict:
    accepted: bool
    reported_loss: float  # R_t
    reason: str

    @property
    def reported_score(self) -> float:
        return 1.0 - self.reported_loss


@dataclass
class Ladder:
    n: int
    R: float = math.inf
    best: list[int] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.best:
            self.best = [0] * self.n

    def submit(self, losses: list[int]) -> Verdict:
        if len(losses) != self.n:
            raise ValueError(f"expected {self.n} losses, got {len(losses)}")
        emp = sum(losses) / self.n
        s = _std([a - b for a, b in zip(losses, self.best)])
        thr = s / math.sqrt(self.n)
        if emp < self.R - thr - 1e-12:  # strict, robust to float ties (e.g. one flip: s/sqrt(n) == 1/n)
            prev = self.R
            self.R = round(emp * self.n) / self.n
            self.best = list(losses)
            v = Verdict(True, self.R, "first submission" if prev == math.inf else "audit gain beats noise threshold")
        else:
            gain = self.R - emp
            why = "no audit gain" if gain <= 0 else "audit gain within noise"
            v = Verdict(False, self.R, why)
        self.history.append({"accepted": v.accepted, "reported_loss": v.reported_loss, "reason": v.reason,
                             "_emp_loss": emp, "_threshold": thr})  # underscored fields: logs only, never to agents
        return v
