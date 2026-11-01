"""Phase 6: release hygiene — everything that is downloaded or executed is pinned."""
from __future__ import annotations

import re
import subprocess  # nosec B404
import sys
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parent.parent
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def test_all_models_pinned_https():
    assert config.HF_ENDPOINT.startswith("https://")
    for name, spec in {**config.MODELS, **config.AUX_MODELS}.items():
        assert SHA40.match(spec["revision"] or ""), f"{name} revision not pinned"
    for spec in config.AUX_MODELS.values():
        assert not any(p.endswith((".bin", ".pt", ".pkl")) for p in spec["patterns"])  # no pickle weights


def test_ffmpeg_download_pinned():
    ps = (ROOT / "packaging" / "get_ffmpeg.ps1").read_text()
    assert re.search(r'\$Sha256 = "[0-9a-f]{64}"', ps) and '$Url = "https://' in ps


def test_workflow_actions_pinned_and_least_privilege():
    wf = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text()
    uses = re.findall(r"uses:\s*([^\s#]+)", wf)
    assert uses and all(re.search(r"@[0-9a-f]{40}$", u) for u in uses), uses
    assert "permissions:\n  contents: read" in wf and "secrets." not in wf


def test_requirements_hash_locked():
    for f in ("requirements.txt", "requirements-build.txt"):
        text = (ROOT / f).read_text()
        pins = re.findall(r"^([A-Za-z0-9_.-]+)==", text, re.M)
        assert pins and text.count("--hash=sha256:") >= len(pins)


def test_security_scan_clean():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "security_scan.py")],  # nosec B603
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout
