from pathlib import Path


def test_build_script_contains_safety_features():
    batch = Path("build.bat").read_text(encoding="utf-8")
    remote = Path("scripts/deploy_remote.sh").read_text(encoding="utf-8")

    assert "setlocal EnableExtensions EnableDelayedExpansion" in batch
    assert "docker build" in batch
    assert "docker save" in batch
    assert "scp -i" in batch
    assert "LOCAL_DEPLOY_SCRIPT=scripts/deploy_remote.sh" in batch
    assert "bash '%REMOTE_DEPLOY_SCRIPT%'" in batch
    assert "release=" in batch
    assert "debug" in batch
    assert "--env-file" in remote
    assert "PERRY_DEBUG" in remote
