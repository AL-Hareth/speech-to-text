"""Repo security scan: hardcoded secrets + banned dangerous calls. Exit 1 on any finding."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", ".venv312", "build", "dist", "__pycache__", ".pytest_cache", "node_modules"}
TEXT_EXT = {".py", ".bat", ".ps1", ".yml", ".yaml", ".iss", ".md", ".txt", ".in", ".json", ".spec", ".cfg", ".toml"}

SECRETS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "AWS key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    "HF token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "OpenAI/Anthropic key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    "Slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "generic secret assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
}
BANNED = {  # only checked in shipped code
    "pickle": re.compile(r"\bimport pickle\b|\bpickle\.(?:load|loads|dump)\b|\bcPickle\b|\bjoblib\.load\b"),
    "shell=True": re.compile(r"shell\s*=\s*True"),
    "eval": re.compile(r"(?<![\w.])eval\("),
    "exec": re.compile(r"(?<![\w.])exec\("),
    "os.system": re.compile(r"\bos\.system\("),
    "unsafe torch.load": re.compile(r"weights_only\s*=\s*False"),
    "allow_pickle": re.compile(r"allow_pickle\s*=\s*True"),
    "remote code": re.compile(r"trust_remote_code\s*=\s*True"),
    "yaml.load": re.compile(r"\byaml\.load\((?![^)]*SafeLoader)"),
}


def files(base: Path):
    for p in base.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.suffix in TEXT_EXT:
            yield p


def main() -> int:
    findings = []
    for p in files(ROOT):
        if p.name == "security_scan.py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, rx in SECRETS.items():
            for m in rx.finditer(text):
                findings.append(f"{p.relative_to(ROOT)}: possible {name}")
    shipped = [*(ROOT / "app").rglob("*.py"), ROOT / "lecturescribe.py", ROOT / "lecturescribe_cli.py"]
    for p in shipped:
        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]          # ignore comments
            for name, rx in BANNED.items():
                if rx.search(code):
                    findings.append(f"{p.relative_to(ROOT)}:{no}: banned {name}")
    for f in findings:
        print(f)
    print(f"security_scan: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
