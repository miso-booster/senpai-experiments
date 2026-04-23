from pathlib import Path

from app.rq1.aggregate_rankings import default_rq1_out_root as aggregate_rq1_out_root
from app.rq1.aggregate_rankings import default_rq1_runs_dir as aggregate_rq1_runs_dir
from app.rq1.generate_rankings import _resolve_run_dir as resolve_rq1_generate_run_dir
from app.rq1.generate_rankings import default_rq1_out_root as generate_rq1_out_root
from app.rq1.generate_rankings import default_rq1_runs_dir as generate_rq1_runs_dir
from app.rq2.aggregate_metrics import default_rq2_out_dir, default_rq2_runs_dir
from app.rq2.fallback_answer_join import default_rq2_out_dir as fallback_rq2_out_dir
from app.setup_configuration import (
    OUT_DIR,
    RUNS_DIR,
    resolve_experiment_dirname,
    resolve_runs_dir,
    sanitize_path_component,
)


def test_sanitize_path_component_slugifies_model_labels() -> None:
    assert sanitize_path_component("GPT-5 Codex") == "gpt-5-codex"
    assert sanitize_path_component("GPT-4.1 mini") == "gpt-4-1-mini"


def test_resolve_runs_dir_uses_model_bucket_when_model_label_is_present() -> None:
    assert resolve_experiment_dirname(rq2=True) == "architecture_comparison"
    assert resolve_experiment_dirname(rq3=True) == "advanced_prompt_arch_comparison"
    assert resolve_experiment_dirname(rq4=True) == "guardrail_test"
    assert resolve_runs_dir("architecture_comparison") == RUNS_DIR / "architecture_comparison"
    assert resolve_runs_dir("architecture_comparison", "GPT-5 Codex") == (
        RUNS_DIR / "architecture_comparison" / "by_model" / "gpt-5-codex"
    )


def test_rq1_and_rq2_defaults_match_model_scoped_layout() -> None:
    expected_runs = RUNS_DIR / "architecture_comparison" / "by_model" / "gpt-4-1-mini"
    expected_rq1_out = OUT_DIR / "RQ1" / "by_model" / "gpt-4-1-mini"
    expected_rq2_out = OUT_DIR / "RQ2_architecture_metrics" / "by_model" / "gpt-4-1-mini"

    assert generate_rq1_runs_dir("GPT-4.1 mini") == expected_runs
    assert aggregate_rq1_runs_dir("GPT-4.1 mini") == expected_runs
    assert generate_rq1_out_root("GPT-4.1 mini") == expected_rq1_out
    assert aggregate_rq1_out_root("GPT-4.1 mini") == expected_rq1_out
    assert default_rq2_runs_dir("GPT-4.1 mini") == expected_runs
    assert default_rq2_out_dir("GPT-4.1 mini") == expected_rq2_out
    assert fallback_rq2_out_dir("GPT-4.1 mini") == expected_rq2_out


def test_resolve_run_dir_ignores_non_run_directories(tmp_path: Path) -> None:
    (tmp_path / "by_model" / "gpt-5-codex").mkdir(parents=True)
    legacy_run = tmp_path / "20260423_120000_000"
    legacy_run.mkdir()
    (legacy_run / "results.xlsx").touch()

    resolved = resolve_rq1_generate_run_dir(tmp_path, None)

    assert resolved == legacy_run
