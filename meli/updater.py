"""In-app updater for Meli.

Checks GitHub Releases for a newer tag, downloads the published release
tarball (prefers a ``meli-X.Y.Z.tar.gz`` asset; falls back to GitHub's
auto-generated source tarball if no custom asset is published), verifies
an optional sibling ``.sha256``, extracts it into a temp directory, and
runs ``install.sh`` under ``pkexec`` so the venv under ``/opt/meli`` is
rebuilt cleanly. User-scope installs (``install.sh --user``) skip pkexec.

Author: Joseph Sierengowski.
License: MIT.

Design notes
------------
- No third-party HTTP client — stdlib ``urllib`` only, so the updater
  works on a fresh Python install before any pip work happens.
- All work is staged in ``~/.cache/meli/updates/<version>/`` and the
  staging dir is cleaned up on completion.
- ``check_for_update()`` is safe to call from a background thread; it
  performs at most one HTTP round-trip and respects a 10s timeout.
- ``download_and_install()`` returns an opaque ``InstallProcess``
  handle whose ``poll()`` method is suitable for ``GLib.timeout_add``.
- Modelled on GodsApp v0.6.0's updater (same author, same patterns).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import structlog

from meli import __version__
from meli.config import get_config

log = structlog.get_logger(__name__)


# ── version comparison ────────────────────────────────────────────────────
_VERSION_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|b|rc|alpha|beta|dev)\.?(\d+)?)?"
)


def parse_version(v: str) -> tuple[int, int, int, int, int]:
    """Return a sortable 5-tuple. Pre-releases sort below their final."""
    m = _VERSION_RE.match(v.strip())
    if not m:
        return (0, 0, 0, 0, 0)
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre_kind = (m.group(4) or "").lower()
    pre_num = int(m.group(5) or 0)
    pre_rank = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, "dev": -1}.get(
        pre_kind, 99
    )
    return (major, minor, patch, pre_rank, pre_num)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# ── update info ───────────────────────────────────────────────────────────
@dataclass
class UpdateInfo:
    version: str            # "2.4.0"
    tag: str                # "v2.4.0"
    name: str               # human-readable release title
    notes: str              # markdown body
    asset_url: str          # tarball download URL
    asset_name: str         # e.g. "meli-2.4.0.tar.gz" or "Meli-<sha>.tar.gz"
    asset_size: int         # bytes (0 for source archives)
    sha256_url: Optional[str]
    published_at: str       # ISO-8601
    prerelease: bool


@dataclass
class _Progress:
    stage: str = "idle"
    bytes_done: int = 0
    bytes_total: int = 0
    message: str = ""


# ── settings helpers ──────────────────────────────────────────────────────
DEFAULT_OWNER = "sierengowskisierengowski-cpu"
DEFAULT_REPO = "Meli"
DEFAULT_FEED_TEMPLATE = "https://api.github.com/repos/{owner}/{repo}/releases"

_DEFAULTS = {
    "auto_check": True,
    "check_interval_hours": 24,
    "include_prereleases": False,
    "user_scope": False,
    "feed_url": "",
    "last_check_at": "",
    "last_seen_version": "",
    "skipped_version": "",
}


def _s(key: str):
    cfg = get_config()
    return cfg.get("updates", key, default=_DEFAULTS[key])


def _set(key: str, value) -> None:
    get_config().set("updates", key, value)


def _feed_url() -> str:
    custom = _s("feed_url") or ""
    if custom:
        return custom
    return DEFAULT_FEED_TEMPLATE.format(owner=DEFAULT_OWNER, repo=DEFAULT_REPO)


# ── feed fetching ─────────────────────────────────────────────────────────
def _http_get_json(url: str, *, timeout: float = 10.0) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Meli/{__version__} (in-app updater)",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _pick_release(releases: list, allow_prerelease: bool) -> Optional[dict]:
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not allow_prerelease:
            continue
        return rel
    return None


def _extract_update_info(rel: dict) -> Optional[UpdateInfo]:
    tag = str(rel.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    if not version:
        return None

    assets = rel.get("assets") or []
    tarball = next(
        (
            a for a in assets
            if a.get("name", "").endswith(".tar.gz")
            and "meli" in a.get("name", "").lower()
        ),
        None,
    )

    if tarball:
        asset_url = str(tarball["browser_download_url"])
        asset_name = str(tarball["name"])
        asset_size = int(tarball.get("size") or 0)
        sha = next(
            (
                a for a in assets
                if a.get("name") == f"{asset_name}.sha256"
                or (
                    a.get("name", "").endswith(".sha256")
                    and a.get("name", "").startswith(asset_name.split(".tar.gz")[0])
                )
            ),
            None,
        )
        sha256_url = str(sha["browser_download_url"]) if sha else None
    else:
        # Fall back to GitHub's auto-generated source archive so the
        # updater works even before any custom assets are uploaded.
        tarball_url = rel.get("tarball_url")
        if not tarball_url:
            return None
        asset_url = str(tarball_url)
        asset_name = f"Meli-{version}.tar.gz"
        asset_size = 0
        sha256_url = None

    return UpdateInfo(
        version=version,
        tag=tag,
        name=str(rel.get("name") or tag),
        notes=str(rel.get("body") or ""),
        asset_url=asset_url,
        asset_name=asset_name,
        asset_size=asset_size,
        sha256_url=sha256_url,
        published_at=str(rel.get("published_at") or ""),
        prerelease=bool(rel.get("prerelease")),
    )


# ── public API ────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    current_version: str
    info: Optional[UpdateInfo]   # None means "you're up to date"
    error: Optional[str] = None


def check_for_update(
    *,
    allow_prerelease: Optional[bool] = None,
    record: bool = True,
) -> CheckResult:
    """Hit the releases feed once and return whether a newer version exists.

    Safe to call from a background thread. Never raises — failures are
    returned in ``CheckResult.error``.
    """
    if allow_prerelease is None:
        allow_prerelease = bool(_s("include_prereleases"))

    try:
        data = _http_get_json(_feed_url(), timeout=10.0)
    except urllib.error.HTTPError as e:
        return CheckResult(__version__, None, f"HTTP {e.code} from updates feed")
    except urllib.error.URLError as e:
        return CheckResult(__version__, None, f"network error: {e.reason}")
    except Exception as e:
        return CheckResult(__version__, None, f"{type(e).__name__}: {e}")

    releases = data if isinstance(data, list) else []
    rel = _pick_release(releases, allow_prerelease)
    info = _extract_update_info(rel) if rel else None

    if record:
        try:
            _set("last_check_at", datetime.now(timezone.utc).isoformat())
            if info:
                _set("last_seen_version", info.version)
        except Exception:
            log.exception("failed to persist updates.last_check_at")

    if not info:
        return CheckResult(
            __version__, None,
            None if rel else "no published releases found",
        )
    if not is_newer(info.version, __version__):
        return CheckResult(__version__, None)
    return CheckResult(__version__, info)


# ── download + install ────────────────────────────────────────────────────
def _cache_root() -> Path:
    base = Path(
        os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    ) / "meli"
    root = base / "updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _download(
    url: str,
    dest: Path,
    *,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = 60.0,
) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Meli/{__version__} (in-app updater)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with dest.open("wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    try:
                        progress_cb(done, total)
                    except Exception:
                        pass


def _verify_sha256(tarball: Path, sha_url: str) -> bool:
    import hashlib
    try:
        with urllib.request.urlopen(sha_url, timeout=10.0) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
    except Exception:
        log.warning("sha256 fetch failed — proceeding unverified")
        return True
    expected = text.split()[0].lower() if text else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        log.warning("malformed sha256 file — proceeding unverified")
        return True
    h = hashlib.sha256()
    with tarball.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        log.error("sha256 mismatch", expected=expected, actual=actual)
        return False
    log.info("sha256 verified", digest=actual)
    return True


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> Path:
    dest_resolved = dest.resolve()
    members = []
    for m in tar.getmembers():
        member_path = (dest / m.name).resolve()
        try:
            member_path.relative_to(dest_resolved)
        except ValueError:
            raise RuntimeError(f"refusing path-traversing entry: {m.name}")
        members.append(m)
    tar.extractall(dest, members=members)
    tops = {Path(m.name).parts[0] for m in members if m.name}
    if len(tops) == 1:
        return dest / next(iter(tops))
    return dest


def _find_installer(root: Path) -> Optional[Path]:
    """install.sh is normally at the top of the archive; GitHub source
    tarballs nest it one level deeper under ``<Repo>-<sha>/``."""
    candidate = root / "install.sh"
    if candidate.exists():
        return candidate
    for child in root.iterdir():
        if child.is_dir() and (child / "install.sh").exists():
            return child / "install.sh"
    return None


@dataclass
class InstallProcess:
    """Wraps the running install subprocess + a small mutable progress
    record so the UI can poll without blocking.
    """
    proc: subprocess.Popen
    log_path: Path
    install_root: Path
    stage: str = "installing"
    _final_rc: Optional[int] = field(default=None)

    def poll(self) -> Optional[int]:
        if self._final_rc is not None:
            return self._final_rc
        rc = self.proc.poll()
        if rc is None:
            return None
        self._final_rc = rc
        self.stage = "ok" if rc == 0 else "failed"
        return rc

    def tail(self, n: int = 4096) -> str:
        try:
            with self.log_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - n))
                return f.read().decode("utf-8", errors="replace")
        except Exception:
            return ""

    def cancel(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass


def download_and_install(
    info: UpdateInfo,
    *,
    user_scope: Optional[bool] = None,
    progress_cb: Optional[Callable[[_Progress], None]] = None,
) -> InstallProcess:
    """Download the release tarball, verify it, extract it, and launch
    ``install.sh`` (under pkexec by default). Returns an ``InstallProcess``
    the caller can poll from the GTK main loop.
    """
    if user_scope is None:
        user_scope = bool(_s("user_scope"))

    prog = _Progress(stage="downloading",
                     message=f"Downloading {info.asset_name}…")
    if progress_cb:
        progress_cb(prog)

    stage_dir = _cache_root() / info.version
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    tarball = stage_dir / info.asset_name

    def _on_bytes(done: int, total: int) -> None:
        prog.bytes_done = done
        prog.bytes_total = total or info.asset_size
        if progress_cb:
            progress_cb(prog)

    _download(info.asset_url, tarball, progress_cb=_on_bytes)

    if info.sha256_url:
        prog.stage = "verifying"
        prog.message = "Verifying signature…"
        if progress_cb:
            progress_cb(prog)
        if not _verify_sha256(tarball, info.sha256_url):
            raise RuntimeError("sha256 verification failed — refusing to install")

    prog.stage = "extracting"
    prog.message = "Extracting archive…"
    if progress_cb:
        progress_cb(prog)
    extract_dir = stage_dir / "src"
    extract_dir.mkdir(exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tar:
        top = _safe_extract(tar, extract_dir)

    installer = _find_installer(top)
    if not installer:
        raise RuntimeError(
            f"install.sh not found in archive (looked in {top})"
        )
    installer.chmod(0o755)
    install_root = installer.parent

    prog.stage = "installing"
    prog.message = "Running install.sh…"
    if progress_cb:
        progress_cb(prog)
    log_path = stage_dir / "install.log"
    if user_scope:
        cmd = ["bash", str(installer), "--user"]
    elif shutil.which("pkexec"):
        cmd = ["pkexec", "bash", str(installer)]
    else:
        log.warning("pkexec missing — falling back to --user install")
        cmd = ["bash", str(installer), "--user"]

    log_fh = log_path.open("wb")
    proc = subprocess.Popen(
        cmd,
        cwd=str(install_root),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env={**os.environ, "MELI_INSTALLER_NONINTERACTIVE": "1"},
    )
    return InstallProcess(
        proc=proc,
        log_path=log_path,
        install_root=install_root,
        stage="installing",
    )


# ── background-check helper for app startup ───────────────────────────────
def should_auto_check() -> bool:
    """True iff auto_check is enabled and we haven't checked recently."""
    if not bool(_s("auto_check")):
        return False
    last = str(_s("last_check_at") or "")
    if not last:
        return True
    try:
        when = datetime.fromisoformat(last)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    now = datetime.now(timezone.utc)
    interval = max(1, int(_s("check_interval_hours") or 24))
    return (now - when).total_seconds() >= interval * 3600


def skip_version(version: str) -> None:
    """Mark a version as skipped so the auto-check toast won't re-prompt."""
    _set("skipped_version", version)


def is_skipped(version: str) -> bool:
    return str(_s("skipped_version") or "") == version
