"""Configuration backups in a git repository (one file per device, one commit per change).

Falls back to plain versioned files when ``git`` is not on the PATH.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

_lock = threading.Lock()


@dataclass
class BackupRef:
    location: str
    sha256: str
    commit: str | None


class BackupStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or get_settings().backup_dir).resolve()
        self.git = shutil.which("git")

    def _git(self, *args: str) -> str:
        assert self.git
        result = subprocess.run(
            [self.git, "-C", str(self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _ensure_repo(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.git and not (self.root / ".git").exists():
            self._git("init", "-q")
            self._git("config", "user.name", "hatch-backup")
            self._git("config", "user.email", "hatch-backup@localhost")

    def save(self, *, site: str, hostname: str, config: str, message: str) -> BackupRef:
        digest = hashlib.sha256(config.encode()).hexdigest()
        with _lock:
            self._ensure_repo()
            path = self.root / site / f"{hostname}.cfg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(config, encoding="utf-8")
            commit = None
            if self.git:
                rel = path.relative_to(self.root).as_posix()
                self._git("add", rel)
                status = self._git("status", "--porcelain", "--", rel)
                if status:
                    self._git("commit", "-q", "-m", message, "--", rel)
                commit = self._git("rev-parse", "--short", "HEAD")
            return BackupRef(location=str(path), sha256=digest, commit=commit)
