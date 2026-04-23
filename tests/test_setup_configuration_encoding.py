from app.architecture import Architecture
from app.setup_configuration import build_env, load_default_model_label


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
