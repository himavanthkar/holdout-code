"""Runtime seal: the improver, red team and explainer may never see audit/unseen task text or hidden (plus) inputs."""
from __future__ import annotations

from functools import lru_cache

from .tasks import _dataset, pools


class SealBroken(RuntimeError):
    pass


def _snippet(prompt: str) -> str:
    body = " ".join(prompt.replace('"""', " ").split())
    return body[:70]


@lru_cache(maxsize=1)
def sealed_snippets() -> tuple[str, ...]:
    P = pools()
    out = []
    for name in ("audit", "unseen"):
        for ds, tid in P[name]:
            t = _dataset(ds)[tid]
            out.append(_snippet(t["prompt"]))
    return tuple(s for s in out if len(s) > 30)


def check(text: str) -> str:
    flat = " ".join(text.split())
    for s in sealed_snippets():
        if s in flat:
            raise SealBroken(f"sealed task text leaked into a prompt: {s[:50]!r}")
    return text
