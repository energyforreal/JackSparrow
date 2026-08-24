"""Guards for the WSL Google Colab CLI helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from feature_store.transformer_btcusd.contract import FUSION_BUNDLE_DIR_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]
COLAB_DIR = REPO_ROOT / "scripts" / "colab"
RUN_SH = COLAB_DIR / "run_colab_cli.sh"
SETUP_SH = COLAB_DIR / "setup_wsl_colab_cli.sh"
RUN_PS1 = COLAB_DIR / "run_colab_cli.ps1"
SETUP_PS1 = COLAB_DIR / "setup_wsl_colab_cli.ps1"


def test_colab_cli_helper_files_exist() -> None:
    for path in (RUN_SH, SETUP_SH, RUN_PS1, SETUP_PS1):
        assert path.is_file(), path


def test_run_colab_cli_sh_uses_bundle_name_and_cli_verbs() -> None:
    text = RUN_SH.read_text(encoding="utf-8")
    assert FUSION_BUNDLE_DIR_NAME in text
    for token in (
        "colab exec",
        "colab download",
        "export/${BUNDLE_DIR_NAME}.zip",
        "colab stop",
        "colab sessions",
        "--gpu",
        "--timeout",
        "transformer_btcusd_next_candle_research.ipynb",
    ):
        assert token in text, token
    assert "\r" not in text


def test_setup_wsl_colab_cli_installs_official_package() -> None:
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "google-colab-cli" in text
    assert "uv tool install" in text
    assert "jupyter-kernel-client==0.15.0" in text
    assert "Ubuntu-24.04" in text
    assert "\r" not in text


def test_windows_trampolines_pin_ubuntu_distro() -> None:
    for path in (RUN_PS1, SETUP_PS1):
        text = path.read_text(encoding="utf-8")
        assert 'Distro = "Ubuntu-24.04"' in text
        assert "docker-desktop" not in text.lower() or "does not change" in text.lower() or "Does not change" in text


def test_readme_documents_wsl_colab_cli() -> None:
    readme = (COLAB_DIR / "README.md").read_text(encoding="utf-8")
    assert "setup_wsl_colab_cli.ps1" in readme
    assert "run_colab_cli.ps1" in readme
    assert "colab sessions" in readme


def _wsl_ubuntu_available() -> bool:
    if shutil.which("wsl") is None:
        return False
    listed = subprocess.run(
        ["wsl", "-l", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    names = listed.stdout.replace("\x00", "")
    return "Ubuntu-24.04" in names


@pytest.mark.skipif(not _wsl_ubuntu_available(), reason="Ubuntu-24.04 WSL distro not installed")
def test_colab_cli_shell_scripts_parse() -> None:
    for rel in ("scripts/colab/run_colab_cli.sh", "scripts/colab/setup_wsl_colab_cli.sh"):
        result = subprocess.run(
            [
                "wsl",
                "-d",
                "Ubuntu-24.04",
                "--cd",
                str(REPO_ROOT),
                "--",
                "bash",
                "-n",
                rel,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
