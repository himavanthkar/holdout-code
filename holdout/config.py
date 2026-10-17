"""Env-driven configuration: role -> (base_url, api_key, model, temperature)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

RUNS = ROOT / "runs"
CRUSOE_DEFAULT_URL = "https://api.inference.crusoecloud.com/v1"

TEMPERATURES = {"spec": 0.2, "builder": 0.2, "mutator": 0.7, "verifier": 0.0}


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

    @property
    def family(self) -> str:
        return model_family(self.model)


def model_family(model: str) -> str:
    m = model.lower()
    for fam in ("nemotron", "gemma", "deepseek", "qwen", "glm", "gpt-oss", "llama", "kimi"):
        if fam in m:
            return fam
    return m.split("/")[0]


@dataclass(frozen=True)
class Settings:
    roles: dict[str, Role]
    sandbox: str = "local"
    mut_threshold: float = 0.8
    max_retries: int = 2
    max_llm_calls: int = 14
    wall_clock_s: float = 180.0
    use_cache: bool = False
    extra: dict = field(default_factory=dict)

    def role(self, name: str) -> Role:
        return self.roles[name]

    def with_verifier(self, role: Role) -> "Settings":
        roles = dict(self.roles)
        roles["verifier"] = replace(role, name="verifier", temperature=TEMPERATURES["verifier"])
        return replace(self, roles=roles)

    def same_family_verifier(self) -> "Settings":
        """Condition D: verifier = builder model."""
        return self.with_verifier(self.roles["builder"])


def load_settings(**overrides) -> Settings:
    crusoe_url = _env("CRUSOE_BASE_URL", CRUSOE_DEFAULT_URL)
    crusoe_key = _env("CRUSOE_API_KEY")
    spec = _env("SPEC_MODEL", "deepseek-ai/DeepSeek-V4-Pro")
    roles = {
        "spec": Role("spec", crusoe_url, crusoe_key, spec, TEMPERATURES["spec"]),
        "builder": Role("builder", crusoe_url, crusoe_key, _env("BUILDER_MODEL", "Qwen/Qwen3.8-27B"), TEMPERATURES["builder"]),
        "mutator": Role("mutator", crusoe_url, crusoe_key, _env("MUTATOR_MODEL", spec), TEMPERATURES["mutator"]),
        "verifier": Role(
            "verifier",
            _env("VERIFIER_BASE_URL", crusoe_url),
            _env("VERIFIER_API_KEY", crusoe_key),
            _env("VERIFIER_MODEL", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"),
            TEMPERATURES["verifier"],
        ),
    }
    s = Settings(
        roles=roles,
        sandbox=_env("SANDBOX", "local"),
        mut_threshold=float(_env("MUT_THRESHOLD", "0.8")),
        max_retries=int(_env("MAX_RETRIES", "2")),
        max_llm_calls=int(_env("MAX_LLM_CALLS_PER_TASK", "14")),
        wall_clock_s=float(_env("WALL_CLOCK_S", "180")),
        use_cache=_env("LLM_CACHE", "0") == "1",
    )
    return replace(s, **overrides) if overrides else s


EVAL_N = int(_env("EVAL_N", "30"))
EVAL_SEED = int(_env("EVAL_SEED", "17"))
CONCURRENCY = int(_env("CONCURRENCY", "6"))
