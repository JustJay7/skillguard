import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import linux_runner


@pytest.mark.parametrize("backend", ["colima", "lima"])
def test_insufficient_disk_never_starts_or_creates_vm_state(tmp_path, monkeypatch, backend):
    root = tmp_path / "skillguard"
    root.mkdir()
    monkeypatch.setattr(linux_runner.shutil, "which", lambda name: "/bin/colima")
    monkeypatch.setattr(linux_runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=60))

    def unexpected_start(*args, **kwargs):
        raise AssertionError("VM creation attempted despite insufficient disk space")

    monkeypatch.setattr(linux_runner.subprocess, "run", unexpected_start)
    report = linux_runner.start(root, backend)
    assert report["status"] == "blocked"
    assert report["additional_bytes_needed"] == report["minimum_free_bytes"] - 60
    assert not (tmp_path / "work/linux-runner").exists()


def test_config_directories_exist_before_native_tool_and_no_home_override(tmp_path):
    root = tmp_path / "skillguard"
    root.mkdir()
    original_home = os.environ.get("HOME")
    env = linux_runner.prepare_environment(root)
    for name in ("COLIMA_HOME", "COLIMA_CACHE_HOME", "DOCKER_CONFIG", "LIMA_HOME"):
        path = Path(env[name])
        assert path.is_dir()
        assert path.is_relative_to(tmp_path / "work/linux-runner")
    assert env.get("HOME") == original_home
