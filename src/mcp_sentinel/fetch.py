"""Safe, shallow clones of untrusted repositories.

Clones never run hooks, never prompt for credentials, skip LFS downloads and check
symlinks out as plain files. Nothing cloned here is ever executed.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HOSTS = {"github.com", "gitlab.com", "codeberg.org", "bitbucket.org"}
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
CLONE_TIMEOUT = 180


class FetchError(RuntimeError):
    pass


def normalize_repo_url(raw: str) -> tuple[str, str | None] | None:
    """Return (canonical https URL, subfolder) for a known forge, or None if unsafe."""
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if any(s in (".", "..") or not _SEGMENT.match(s) for s in segments):
        return None

    if host == "gitlab.com":
        cut = segments.index("-") if "-" in segments else len(segments)
        repo, rest = segments[:cut], segments[cut + 1 :]
        if len(repo) < 2:
            return None
        sub = rest[2:] if len(rest) > 2 and rest[0] in ("tree", "blob") else []
    else:
        if len(segments) < 2:
            return None
        repo, rest = segments[:2], segments[2:]
        sub = rest[2:] if len(rest) > 2 and rest[0] in ("tree", "blob", "src") else []

    repo[-1] = repo[-1].removesuffix(".git")
    url = f"https://{host}/" + "/".join(s.lower() for s in repo)
    return url, ("/".join(sub) or None)


def _git(*args: str, cwd: Path | None = None) -> str:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_ASKPASS": "echo",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    safe = ["-c", "core.hooksPath=/dev/null", "-c", "core.symlinks=false"]
    safe += ["-c", "protocol.file.allow=never", "-c", "protocol.ext.allow=never"]
    result = subprocess.run(
        ["git", *safe, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=CLONE_TIMEOUT,
        check=False,
    )
    if result.returncode != 0:
        raise FetchError(
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git failed"
        )
    return result.stdout.strip()


def clone(url: str, cache_dir: Path) -> tuple[Path, str]:
    """Shallow-clone ``url`` into the cache (reusing an existing clone). Returns (path, commit)."""
    if normalize_repo_url(url) is None:
        raise FetchError(f"refusing to clone {url!r}")
    dest = Path(cache_dir) / hashlib.sha1(url.encode()).hexdigest()[:16]
    if not (dest / ".git").is_dir():
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            _git("clone", "--depth", "1", "--single-branch", "--no-tags", "--quiet", url, str(dest))
        except (FetchError, subprocess.TimeoutExpired) as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise FetchError(str(exc)) from exc
    return dest, _git("rev-parse", "HEAD", cwd=dest)


def remote_head(url: str) -> str:
    """Commit SHA of the remote default branch, without cloning anything."""
    if normalize_repo_url(url) is None:
        raise FetchError(f"refusing to contact {url!r}")
    try:
        out = _git("ls-remote", url, "HEAD")
    except subprocess.TimeoutExpired as exc:
        raise FetchError("ls-remote timed out") from exc
    sha = out.split()[0] if out else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise FetchError("no HEAD on remote")
    return sha
