"""Settings: layered YAML + env-var overrides + Secret Manager fallback."""

from __future__ import annotations

import pytest

from tongue_doctor.settings import (
    SecretNotFoundError,
    Settings,
    get_settings,
    load_secret,
    reset_settings_cache,
)


def test_default_settings_load() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.env in {"dev", "prod"}
    assert settings.loop.max_iterations == 6
    assert settings.retrieval.bm25_top_k == 50
    assert settings.eval.prescription_leak_is_gate is True


def test_settings_models_yaml_loaded() -> None:
    """All agents in the active loop must have an entry in config/models.yaml.

    The courtroom-style ``prosecutor`` / ``devils_advocate`` keys were retired
    in 2026-05-02's convergence-loop refactor; they're replaced by
    ``defender`` / ``critic`` / ``convergence_checker``.
    """
    settings = get_settings()
    expected_keys = {
        "reasoner",
        "defender",
        "critic",
        "convergence_checker",
        "must_not_miss_sweeper",
        "judge",
        "safety_reviewer",
        "synthesizer",
        "router",
        "multimodal_processor",
        "research_prescriber",
        "extraction_offline",
    }
    missing = expected_keys - set(settings.models.keys())
    assert not missing, f"Missing model assignments: {missing}"


def test_env_var_overrides_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    reset_settings_cache()
    settings = get_settings()
    assert settings.logging.level == "WARNING"
    assert settings.gcp.project == "test-project"


def test_load_secret_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_SECRET_MANAGER", "false")
    monkeypatch.setenv("MY_SECRET", "shh")
    reset_settings_cache()
    assert load_secret("my_secret") == "shh"


def test_load_secret_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_SECRET_MANAGER", "false")
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    reset_settings_cache()
    with pytest.raises(SecretNotFoundError):
        load_secret("does_not_exist")


def test_load_secret_with_secret_manager_requires_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("USE_SECRET_MANAGER", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    reset_settings_cache()
    with pytest.raises(SecretNotFoundError, match="GOOGLE_CLOUD_PROJECT"):
        load_secret("anything")


def test_settings_paths_resolve_to_repo() -> None:
    settings = get_settings()
    assert settings.prompts_dir.is_dir(), settings.prompts_dir
    assert settings.config_dir.is_dir(), settings.config_dir
    assert (settings.config_dir / "default.yaml").is_file()
