from app.architecture import Architecture
from app.setup_configuration import build_env, load_architectures, load_default_model_label
import pytest


def test_build_env_forces_utf8_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)

    arch = Architecture(id="test", cmd=["python"])
    env = build_env(arch, "20260302_000000_000")

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["LANG"] == "C.UTF-8"
    assert env["LC_ALL"] == "C.UTF-8"


def test_load_default_model_label_reads_top_level_field(tmp_path) -> None:
    config_path = tmp_path / "architectures.json"
    config_path.write_text(
        (
            '{'
            '"model_label": "gpt-4.1-mini",'
            '"architectures": [{"id": "a1", "cmd": ["python"]}]'
            '}'
        ),
        encoding="utf-8",
    )

    assert load_default_model_label(str(config_path)) == "gpt-4.1-mini"


def test_load_architectures_supports_shared_defaults_and_templates(tmp_path) -> None:
    config_path = tmp_path / "architectures.json"
    config_path.write_text(
        """
        {
          "variables": {
            "root": "/tmp/automation"
          },
          "defaults": {
            "cwd": "{root}/{project_dir}",
            "cmd": ["{cwd}/.venv/bin/python", "-m", "app.main"],
            "env_file": "{root}/configs/.env"
          },
          "architectures": [
            {"id": "agentic_architecture", "project_dir": "agentic"}
          ]
        }
        """,
        encoding="utf-8",
    )

    archs = load_architectures(str(config_path))

    assert len(archs) == 1
    assert archs[0].id == "agentic_architecture"
    assert archs[0].cwd == "/tmp/automation/agentic"
    assert archs[0].cmd == ["/tmp/automation/agentic/.venv/bin/python", "-m", "app.main"]
    assert archs[0].env_file == "/tmp/automation/configs/.env"


def test_load_architectures_requires_non_empty_cmd_after_template_resolution(tmp_path) -> None:
    config_path = tmp_path / "architectures.json"
    config_path.write_text(
        """
        {
          "architectures": [
            {"id": "agentic_architecture"}
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define a non-empty 'cmd' list"):
        load_architectures(str(config_path))


def test_load_architectures_requires_cmd_items_to_be_non_empty_strings(tmp_path) -> None:
    config_path = tmp_path / "architectures.json"
    config_path.write_text(
        """
        {
          "architectures": [
            {"id": "agentic_architecture", "cmd": ["python", 123, ""]}
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected a non-empty list of non-empty strings"):
        load_architectures(str(config_path))
