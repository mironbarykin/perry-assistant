from pathlib import Path


def test_build_script_contains_safety_features():
    content = Path("build.bat").read_text(encoding="utf-8")
    assert "setlocal EnableExtensions EnableDelayedExpansion" in content
    assert "docker build" in content
    assert "docker save" in content
    assert "scp -i" in content
    assert "LOCAL_DEPLOY_SCRIPT=scripts/deploy_remote.sh" in content
    assert "bash '%REMOTE_DEPLOY_SCRIPT%'" in content
    assert "--env-file" in content

