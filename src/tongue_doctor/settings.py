"""Layered configuration.

Load order (deepest wins):
1. ``config/default.yaml`` — committed defaults.
2. ``config/{env}.yaml`` — per-environment overlay.
3. Selected env vars (``LOG_LEVEL``, ``GOOGLE_CLOUD_PROJECT``, ``TRACING_ENABLED``, ...).
4. Secret Manager (lazy, only when ``settings.secrets.use_secret_manager``).

The result is a frozen :class:`Settings` instance, exposed via :func:`get_settings`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = REPO_ROOT / "prompts"


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    renderer: Literal["json", "console", "auto"] = "auto"


class TracingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = False
    sample_rate: float = 1.0


class GcpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project: str = ""
    region: str = "me-central1"
    fallback_region: str = "europe-west4"


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    use_secret_manager: bool = False


class LoopConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_iterations: int = 6
    alert_iterations_p95: int = 6
    commit_threshold_confidence: Literal["low", "medium", "high"] = "high"


class AuthorityBoost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tier_1: float = 1.5
    tier_2: float = 1.2
    tier_3: float = 1.0


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bm25_top_k: int = 50
    dense_top_k: int = 50
    fused_top_k: int = 50
    rerank_top_k: int = 10
    final_top_k: int = 5
    authority_boost: AuthorityBoost = Field(default_factory=AuthorityBoost)
    embedding_model: str = "text-embedding-005"
    reranker: str = "cohere-rerank-3"
    ontology_expansion: bool = True


class MultimodalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    storage_bucket_template: str = "{project}-attachments"
    max_attachment_mb: int = 25
    modalities_enabled: list[str] = Field(default_factory=list)


class Features(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    router_enabled: bool = False
    reasoner_enabled: bool = False
    retriever_enabled: bool = False
    devils_advocate_enabled: bool = False
    must_not_miss_enabled: bool = False
    research_prescriber_enabled: bool = False
    safety_reviewer_enabled: bool = False
    synthesizer_enabled: bool = False
    multimodal_enabled: bool = False


class FirestoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    emulator_host: str = ""
    case_retention_days: int = 90


class PremiumCacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ttl_days: int = 90
    rate_limit_per_hour: int = 30


class EvalWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: float = 0.10
    red_flags: float = 0.10
    problem_representation: float = 0.05
    differential: float = 0.20
    must_not_miss: float = 0.20
    workup: float = 0.10
    multimodal: float = 0.10
    citation: float = 0.05
    disclaimer: float = 0.05


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    default_slice: str = "chest_pain"
    llm_judge_provider: str = "vertex_gemini"
    llm_judge_model_assignment_key: str = "synthesizer"
    weights: EvalWeights = Field(default_factory=EvalWeights)
    prescription_leak_is_gate: bool = True


class Settings(BaseModel):
    """Frozen application settings.

    Loaded once at process start via :func:`get_settings`. All downstream code reads from this
    object — never from os.environ or YAML directly — so test-time overrides have a single
    surface area.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: Literal["dev", "prod"] = "dev"
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    gcp: GcpConfig = Field(default_factory=GcpConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    multimodal: MultimodalConfig = Field(default_factory=MultimodalConfig)
    features: Features = Field(default_factory=Features)
    firestore: FirestoreConfig = Field(default_factory=FirestoreConfig)
    premium_cache: PremiumCacheConfig = Field(default_factory=PremiumCacheConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)

    prompts: dict[str, int | None] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)

    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def prompts_dir(self) -> Path:
        return PROMPTS_DIR

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{path} did not parse to a mapping (got {type(loaded).__name__}).")
    return loaded


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for k, v in over.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    if v := os.environ.get("TONGUE_DOCTOR_ENV"):
        raw["env"] = v
    if v := os.environ.get("LOG_LEVEL"):
        raw.setdefault("logging", {})["level"] = v
    if v := os.environ.get("GOOGLE_CLOUD_PROJECT"):
        raw.setdefault("gcp", {})["project"] = v
    if v := os.environ.get("GOOGLE_CLOUD_REGION"):
        raw.setdefault("gcp", {})["region"] = v
    if v := os.environ.get("GOOGLE_CLOUD_FALLBACK_REGION"):
        raw.setdefault("gcp", {})["fallback_region"] = v
    if v := os.environ.get("USE_SECRET_MANAGER"):
        raw.setdefault("secrets", {})["use_secret_manager"] = _truthy(v)
    if v := os.environ.get("TRACING_ENABLED"):
        raw.setdefault("tracing", {})["enabled"] = _truthy(v)
    if v := os.environ.get("FIRESTORE_EMULATOR_HOST"):
        raw.setdefault("firestore", {})["emulator_host"] = v
    return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the frozen Settings singleton.

    Cached. Use :func:`reset_settings_cache` in tests when overriding env vars.
    """
    env = os.environ.get("TONGUE_DOCTOR_ENV", "dev")
    base = _load_yaml(CONFIG_DIR / "default.yaml")
    overlay = _load_yaml(CONFIG_DIR / f"{env}.yaml")
    raw = _deep_merge(base, overlay)
    raw["models"] = _load_yaml(CONFIG_DIR / "models.yaml")
    raw = _apply_env_overrides(raw)
    return Settings.model_validate(raw)


def reset_settings_cache() -> None:
    """Clear the cached Settings — for tests that mutate env vars."""
    get_settings.cache_clear()


class SecretNotFoundError(RuntimeError):
    """Raised when a requested secret cannot be loaded."""


def load_secret(name: str) -> str:
    """Load a secret by canonical name.

    When ``settings.secrets.use_secret_manager`` is False, falls back to ``os.environ[NAME.upper()]``.
    When True, the Secret Manager client is required — wiring lands in Phase 1.
    """
    settings = get_settings()
    env_key = name.upper()
    if not settings.secrets.use_secret_manager:
        v = os.environ.get(env_key)
        if v is None or v == "":
            raise SecretNotFoundError(
                f"Secret {name!r} not found in env (tried {env_key}) and Secret Manager is disabled."
            )
        return v
    if not settings.gcp.project:
        raise SecretNotFoundError(
            f"Cannot load secret {name!r} from Secret Manager: GOOGLE_CLOUD_PROJECT is unset "
            "(open kickoff item 21)."
        )
    raise NotImplementedError(
        "Secret Manager client wiring lands in Phase 1. "
        "Until then, set USE_SECRET_MANAGER=false and supply secrets via env vars."
    )
