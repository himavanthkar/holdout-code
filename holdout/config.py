"""Env-driven configuration: models per role, pool sizes, budget caps."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

RUNS = ROOT / "runs"
RESULTS = ROOT / "results"
GENOMES = ROOT / "genomes"


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, "").strip()
    return v or default


@dataclass(frozen=True)
class Role:
    name: str
    base_url: str
    api_key: str
    model: str
    temperature: float


CRUSOE_URL = _env("CRUSOE_BASE_URL", "https://api.inference.crusoecloud.com/v1")
CRUSOE_KEY = _env("CRUSOE_API_KEY")

# exact ids from GET /v1/models (Step 0, 2026-10-17). Nemotron 3 Ultra is not served on this key, so the improver
# uses the largest Nemotron that is: Nemotron 3 Super 120B.
WORKER_MODEL = _env("WORKER_MODEL", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
IMPROVER_MODEL = _env("IMPROVER_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B")
REDTEAM_MODEL = _env("REDTEAM_MODEL", "deepseek-ai/Deepseek-V4-Flash")
EXPLAINER_MODEL = _env("EXPLAINER_MODEL", "deepseek-ai/Deepseek-V4-Flash")
WORKER_CHOICES = ["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "Qwen/Qwen3.8-27B"]  # what change_model may pick

CONCURRENCY = int(_env("CONCURRENCY", "6"))  # LLM calls in flight (key is shared with another session)
GRADE_WORKERS = int(_env("GRADE_WORKERS", "8"))
SEED = int(_env("SEED", "17"))
SPEND_CAP_USD = float(_env("SPEND_CAP_USD", "15"))

N_TRAIN, N_AUDIT, N_SMOKE, N_UNSEEN = 30, 30, 20, int(_env("N_UNSEEN", "60"))
GENERATIONS = int(_env("GENERATIONS", "4"))
P_IMPROVER = 2

T_WORKER, T_IMPROVER, T_REDTEAM, T_EXPLAINER = 0.2, 0.7, 0.7, 0.2

# USD per 1M tokens (input, output). Estimates for the running spend guard only; not official Crusoe prices.
PRICES = {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": (0.10, 0.40),
    "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B": (0.30, 1.20),
    "deepseek-ai/Deepseek-V4-Flash": (0.30, 1.20),
    "Qwen/Qwen3.8-27B": (0.30, 1.20),
}


def role(name: str, model: str, temperature: float) -> Role:
    return Role(name, CRUSOE_URL, CRUSOE_KEY, model, temperature)
