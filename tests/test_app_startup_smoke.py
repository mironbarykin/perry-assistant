from __future__ import annotations

from perry_assistant.app import build_services


def test_build_services_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_TOKEN", "smoke-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    services = build_services()
    assert services.config.data_dir.exists()
    assert services.config.logs_dir.exists()
    assert services.config.notification_file.exists()

