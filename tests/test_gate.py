import random

from holdout.gate import Ladder


def _fresh(base):
    lad = Ladder(len(base))
    assert lad.submit(base).accepted  # R_0 = inf: the first submission sets the baseline
    return lad


def test_identical_never_accepted():
    base = [1] * 10 + [0] * 20
    lad = _fresh(base)
    for _ in range(20):
        v = lad.submit(list(base))
        assert not v.accepted
        assert v.reported_loss == 10 / 30


def test_clearly_better_accepted():
    base = [1] * 12 + [0] * 18
    lad = _fresh(base)
    better = [0] * 6 + [1] * 6 + [0] * 18  # 6 fewer hidden failures, none worse
    v = lad.submit(better)
    assert v.accepted and abs(v.reported_loss - 6 / 30) < 1e-9


def test_single_flip_is_noise():
    base = [1] * 12 + [0] * 18
    lad = _fresh(base)
    one = [0] + [1] * 11 + [0] * 18  # exactly s/sqrt(n): strict inequality rejects
    assert not lad.submit(one).accepted


def test_worse_rejected_and_state_kept():
    base = [1] * 10 + [0] * 20
    lad = _fresh(base)
    worse = [1] * 15 + [0] * 15
    v = lad.submit(worse)
    assert not v.accepted and lad.best == base and v.reported_loss == 10 / 30


def test_noise_rarely_accepted():
    rng = random.Random(0)
    accepted = trials = 0
    for _ in range(300):
        base = [1 if rng.random() < 0.35 else 0 for _ in range(30)]
        lad = _fresh(base)
        for _ in range(4):  # 4 adaptive rounds of pure noise: each task re-flips with p=0.1
            noisy = [b if rng.random() > 0.1 else 1 - b for b in base]
            accepted += lad.submit(noisy).accepted
            trials += 1
    assert accepted / trials < 0.15, accepted / trials


def test_reports_rounded_to_1_over_n():
    lad = Ladder(30)
    v = lad.submit([1] * 7 + [0] * 23)
    assert abs(v.reported_loss * 30 - round(v.reported_loss * 30)) < 1e-9
