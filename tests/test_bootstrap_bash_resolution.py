"""Cross-platform shell selection contracts for standalone release bootstraps."""

import pytest

from scripts import (
    bootstrap_release_tool,
    bootstrap_task7_release_check,
    bootstrap_task8_release_control,
)


BOOTSTRAPS = (
    bootstrap_release_tool,
    bootstrap_task7_release_check,
    bootstrap_task8_release_control,
)


@pytest.fixture(params=BOOTSTRAPS, ids=lambda bootstrap: bootstrap.__name__.split(".")[-1])
def bootstrap(request, monkeypatch):
    module = request.param
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    return module


@pytest.mark.parametrize("variable", ["ProgramFiles", "ProgramFiles(x86)"])
def test_windows_prefers_installed_git_bash_over_wsl(bootstrap, variable, tmp_path, monkeypatch):
    installation = tmp_path / "Program Files"
    executable = installation / "Git/bin/bash.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv(variable, str(installation))
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda _: pytest.fail("installed Git Bash must take priority over PATH"),
    )

    assert bootstrap._bash_executable() == str(executable)


def test_windows_allows_git_bash_from_path(bootstrap, tmp_path, monkeypatch):
    executable = tmp_path / "PortableGit/usr/bin/bash.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: str(executable))

    assert bootstrap._bash_executable() == str(executable)


@pytest.mark.parametrize("directory", ["System32", "Sysnative", "WindowsApps"])
def test_windows_rejects_wsl_and_app_aliases(bootstrap, directory, tmp_path, monkeypatch):
    executable = tmp_path / directory / "bash.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: str(executable))

    with pytest.raises(RuntimeError, match="Git Bash is required"):
        bootstrap._bash_executable()


def test_windows_reports_missing_git_bash(bootstrap, monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="Git Bash is required"):
        bootstrap._bash_executable()


def test_non_windows_retains_bash_command(bootstrap, monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda _: pytest.fail("non-Windows shell selection must remain unchanged"),
    )

    assert bootstrap._bash_executable() == "bash"
