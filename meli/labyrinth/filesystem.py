"""
Procedurally-generated fake filesystem for the Labyrinth tarpit.

Each session gets its own FakeFS seeded from a per-session random value so
attackers who compare notes see slightly different trees. The structure is
close enough to a real Debian/Ubuntu box to fool automated scanners: standard
directory skeleton, a plausible /proc/cpuinfo, a /etc/passwd, and so on.

Canary token paths (from meli.labyrinth.canary) are injected into the tree
automatically so `ls /root/.aws/` and `cat /root/.aws/credentials` produce
realistic output and fire the alert when read.

Public API:
    seed  = new_session_seed()          # random uint64 — deterministic per session
    fs    = FakeFS(session_seed=seed)
    fs.session_id = "abc123"            # set before first read_file call
    fs.peer_ip    = "1.2.3.4"
    fs.protocol   = "telnet"
    fs.dst_port   = 2323
    fs.cwd                              # current working directory (str)
    fs.home                             # home directory (str, settable)
    fs.resolve(path)                    # normalise path to absolute
    fs.listdir(path)                    # list directory entries
    fs.exists(path) -> bool
    fs.is_dir(path) -> bool
    fs.read_file(path) -> str | None    # returns content; fires canary if bait
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterator

import structlog

log = structlog.get_logger()


def new_session_seed() -> int:
    """Return a random uint64 to seed one session's filesystem."""
    return random.getrandbits(64)


# ---------------------------------------------------------------------------
# Static tree — shared skeleton; variable sections injected at construction.
# Keys are absolute paths.  Values are either a set (directory) or str (file).
# ---------------------------------------------------------------------------

_STATIC_DIRS: frozenset[str] = frozenset([
    "/",
    "/bin", "/sbin", "/usr", "/usr/bin", "/usr/sbin", "/usr/local",
    "/usr/local/bin", "/usr/local/sbin",
    "/lib", "/lib64", "/lib/x86_64-linux-gnu",
    "/etc", "/etc/apt", "/etc/apt/sources.list.d",
    "/etc/ssh", "/etc/systemd", "/etc/systemd/system",
    "/etc/cron.d", "/etc/cron.daily",
    "/etc/wireguard",
    "/tmp", "/var", "/var/log", "/var/tmp", "/var/run",
    "/var/backups",
    "/home", "/root", "/root/.ssh", "/root/.aws",
    "/opt", "/opt/app",
    "/proc", "/proc/net",
    "/dev",
    "/run",
])

# Static files: path -> content (kept short so they look plausible).
_STATIC_FILES: dict[str, str] = {
    "/etc/hostname": "srv-prod-01\n",
    "/etc/shells": "/bin/sh\n/bin/bash\n/usr/bin/bash\n/bin/dash\n/bin/zsh\n",
    "/etc/issue": "Ubuntu 22.04.3 LTS \\n \\l\n",
    "/etc/debian_version": "bookworm/sid\n",
    "/etc/motd": (
        "\n"
        "Welcome to Ubuntu 22.04.3 LTS (GNU/Linux 5.15.0-91-generic x86_64)\n\n"
        " * Documentation:  https://help.ubuntu.com\n"
        " * Management:     https://landscape.canonical.com\n"
        " * Support:        https://ubuntu.com/advantage\n\n"
        "0 updates can be applied immediately.\n\n"
    ),
    "/etc/passwd": (
        "root:x:0:0:root:/root:/bin/bash\n"
        "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        "bin:x:2:2:bin:/bin:/usr/sbin/nologin\n"
        "sys:x:3:3:sys:/dev:/usr/sbin/nologin\n"
        "www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n"
        "syslog:x:104:110::/home/syslog:/usr/sbin/nologin\n"
        "admin:x:1000:1000:Admin,,,:/home/admin:/bin/bash\n"
        "deploy:x:1001:1001:Deploy,,,:/home/deploy:/bin/bash\n"
    ),
    "/etc/group": (
        "root:x:0:\n"
        "daemon:x:1:\n"
        "sudo:x:27:admin\n"
        "admin:x:1000:\n"
        "deploy:x:1001:\n"
    ),
    "/etc/ssh/sshd_config": (
        "Port 22\nAddressFamily any\nListenAddress 0.0.0.0\n"
        "PermitRootLogin yes\nPasswordAuthentication yes\n"
        "ChallengeResponseAuthentication no\n"
        "X11Forwarding yes\nPrintMotd no\n"
        "AcceptEnv LANG LC_*\nSubsystem sftp /usr/lib/openssh/sftp-server\n"
    ),
    "/etc/crontab": (
        "SHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin\n\n"
        "17 *    * * *   root    cd / && run-parts --report /etc/cron.hourly\n"
        "25 6    * * *   root    test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.daily )\n"
        "47 6    * * 7   root    test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.weekly )\n"
        "52 6    1 * *   root    test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.monthly )\n"
    ),
    "/etc/os-release": (
        'PRETTY_NAME="Ubuntu 22.04.3 LTS"\n'
        'NAME="Ubuntu"\nVERSION_ID="22.04"\nVERSION="22.04.3 LTS (Jammy Jellyfish)"\n'
        'VERSION_CODENAME=jammy\nID=ubuntu\nID_LIKE=debian\n'
        'HOME_URL="https://www.ubuntu.com/"\n'
        'SUPPORT_URL="https://help.ubuntu.com/"\n'
        'BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"\n'
    ),
    "/proc/version": (
        "Linux version 5.15.0-91-generic (buildd@lcy02-amd64-020) "
        "(gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0, GNU ld (GNU Binutils for Ubuntu) 2.38) "
        "#101-Ubuntu SMP Tue Nov 14 13:30:08 UTC 2023\n"
    ),
    "/proc/uptime": "1234567.89 4321234.56\n",
    "/proc/loadavg": "0.08 0.04 0.01 1/312 31427\n",
    "/proc/net/dev": (
        "Inter-|   Receive                                                |  Transmit\n"
        " face |bytes    packets errs drop fifo frame compressed multicast"
        "|bytes    packets errs drop fifo colls carrier compressed\n"
        "    lo: 12345678    4321    0    0    0     0          0         0"
        "  12345678    4321    0    0    0     0       0          0\n"
        "  eth0: 987654321  654321    0    0    0     0          0      1234"
        "  123456789  234567    0    0    0     0       0          0\n"
    ),
    "/var/log/auth.log": (
        "Nov 14 12:01:22 srv-prod-01 sshd[1234]: Accepted password for "
        "admin from 10.0.0.5 port 54321 ssh2\n"
        "Nov 14 12:01:22 srv-prod-01 sshd[1234]: pam_unix(sshd:session): "
        "session opened for user admin by (uid=0)\n"
    ),
    "/root/.bash_history": (
        "ls -la\npwd\nwhoami\nid\nuname -a\ncat /etc/passwd\nifconfig\n"
        "netstat -tlnp\nps aux\ndf -h\nfree -m\n"
    ),
    "/root/.bashrc": (
        "# ~/.bashrc: executed by bash(1) for non-login shells.\n"
        "export PS1='\\u@\\h:\\w\\$ '\n"
        "export HISTSIZE=1000\nexport HISTFILESIZE=2000\n"
        "alias ls='ls --color=auto'\nalias ll='ls -alF'\nalias la='ls -A'\n"
    ),
    "/root/.profile": (
        "# ~/.profile: executed by the command interpreter for login shells.\n"
        "if [ -n \"$BASH_VERSION\" ]; then\n"
        "    if [ -f \"$HOME/.bashrc\" ]; then\n"
        "        . \"$HOME/.bashrc\"\n"
        "    fi\nfi\n"
    ),
    "/home/admin/.bash_history": (
        "sudo apt update\nsudo apt upgrade -y\n"
        "sudo systemctl status nginx\ntail -f /var/log/nginx/error.log\n"
    ),
    "/opt/app/.env.example": (
        "# Copy to .env and fill in real values\n"
        "DATABASE_URL=postgres://user:password@localhost:5432/appdb\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "SECRET_KEY=changeme\n"
    ),
    "/var/backups/README": "Automated backups stored here. See /etc/cron.daily/backup.\n",
    "/tmp/.X0-lock": "1234\n",
}

# Directory children index — built at module level (shared, read-only).
_DIR_CHILDREN: dict[str, set[str]] = {}
for _p in list(_STATIC_DIRS) + list(_STATIC_FILES.keys()):
    _parent = str(PurePosixPath(_p).parent)
    if _parent != _p:
        _DIR_CHILDREN.setdefault(_parent, set()).add(PurePosixPath(_p).name)
# Ensure top-level root is in the index.
_DIR_CHILDREN.setdefault("/", set())

# Home directories for common usernames — injected at FakeFS init time.
_HOME_DIRS: tuple[str, ...] = ("/home/admin", "/home/deploy")


# ---------------------------------------------------------------------------
# FakeFS
# ---------------------------------------------------------------------------

@dataclass
class FakeFS:
    """Per-session fake filesystem.

    All state is per-instance; the static tree (_STATIC_DIRS / _STATIC_FILES)
    is shared and read-only.  Session-specific files (e.g. a seeded /proc/
    cpuinfo that reports a unique CPU model) are built at init time and stored
    in ``_extra_files``.
    """
    session_seed: int = field(default_factory=new_session_seed)
    _cwd: str = field(default="/root", init=False, repr=False)
    home: str = field(default="/root", init=False)

    # Set by shell.py / ssh_server.py after construction so canary.trigger()
    # can attribute trips to this session.
    session_id: str = field(default="", init=False)
    peer_ip: str = field(default="", init=False)
    protocol: str = field(default="telnet", init=False)
    dst_port: int = field(default=2323, init=False)

    _extra_files: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _extra_dirs: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        rng = random.Random(self.session_seed)
        self._build_variable_files(rng)

    def _build_variable_files(self, rng: random.Random) -> None:
        """Seed the per-session variable entries."""
        # /proc/cpuinfo — vary CPU model so sessions look like different boxes.
        cpu_models = [
            "Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz",
            "Intel(R) Xeon(R) CPU E5-2670 v3 @ 2.30GHz",
            "AMD EPYC 7542 32-Core Processor",
            "Intel(R) Core(TM) i5-9400 CPU @ 2.90GHz",
            "Intel(R) Xeon(R) Silver 4214R CPU @ 2.40GHz",
        ]
        cpu_model = rng.choice(cpu_models)
        cores = rng.choice([2, 4, 8, 16])
        cpu_block = "\n".join(
            f"processor\t: {i}\n"
            f"vendor_id\t: GenuineIntel\n"
            f"cpu family\t: 6\n"
            f"model name\t: {cpu_model}\n"
            f"cpu MHz\t\t: {rng.uniform(2200.0, 4200.0):.3f}\n"
            f"cache size\t: {rng.choice([4096, 8192, 16384])} KB\n"
            f"bogomips\t: {rng.uniform(4000.0, 8000.0):.2f}\n"
            for i in range(cores)
        )
        self._extra_files["/proc/cpuinfo"] = cpu_block + "\n"

        # /etc/hosts — vary the hostname
        host_suffix = format(rng.getrandbits(16), "04x")
        hostname = f"srv-{host_suffix}"
        self._extra_files["/etc/hosts"] = (
            f"127.0.0.1\tlocalhost\n"
            f"127.0.1.1\t{hostname}\n"
            f"::1\t\tlocalhost ip6-localhost ip6-loopback\n"
            f"ff02::1\t\tip6-allnodes\n"
            f"ff02::2\t\tip6-allrouters\n"
        )
        self._extra_files["/etc/hostname"] = f"{hostname}\n"

        # Inject canary token paths so they appear in ls output.
        try:
            from meli.labyrinth import canary as _canary
            for path in _canary.all_paths():
                pp = PurePosixPath(path)
                parent = str(pp.parent)
                self._extra_dirs.add(parent)
                # Don't populate content here — read_file handles canary content.
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Path helpers
    # ------------------------------------------------------------------ #

    @property
    def cwd(self) -> str:
        return self._cwd

    @cwd.setter
    def cwd(self, value: str) -> None:
        self._cwd = value or "/"

    def resolve(self, path: str) -> str:
        """Resolve *path* relative to cwd, normalise /../ components."""
        if not path:
            return self._cwd
        if not path.startswith("/"):
            path = self._cwd.rstrip("/") + "/" + path
        # Pure normalisation without symlink resolution (this is a fake FS).
        return str(PurePosixPath("/").joinpath(
            *[p for p in path.split("/") if p]))

    def _norm(self, path: str) -> str:
        """Absolute normalised path."""
        raw = path if path.startswith("/") else self._cwd.rstrip("/") + "/" + path
        # Walk the components, resolving .. manually.
        parts: list[str] = []
        for part in raw.replace("\\", "/").split("/"):
            if part in ("", "."):
                continue
            elif part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts) if parts else "/"

    # ------------------------------------------------------------------ #
    # Tree queries
    # ------------------------------------------------------------------ #

    def exists(self, path: str) -> bool:
        p = self._norm(path)
        return (p in _STATIC_DIRS or p in _STATIC_FILES
                or p in self._extra_files or p in self._extra_dirs
                or self._is_canary_path(p))

    def is_dir(self, path: str) -> bool:
        p = self._norm(path)
        return p in _STATIC_DIRS or p in self._extra_dirs

    def is_file(self, path: str) -> bool:
        p = self._norm(path)
        return (p in _STATIC_FILES or p in self._extra_files
                or self._is_canary_path(p))

    def _is_canary_path(self, norm_path: str) -> bool:
        try:
            from meli.labyrinth import canary as _canary
            return _canary.is_canary(norm_path) is not None
        except Exception:
            return False

    def listdir(self, path: str = ".") -> list[str]:
        """Return a sorted list of entry names in *path*."""
        p = self._norm(path)
        entries: set[str] = set()

        # Entries from the static tree.
        if p in _DIR_CHILDREN:
            entries.update(_DIR_CHILDREN[p])

        # Extra dirs built at init time.
        for d in self._extra_dirs:
            nd = self._norm(d)
            if str(PurePosixPath(nd).parent) == p:
                entries.add(PurePosixPath(nd).name)

        # Extra files.
        for fp in self._extra_files:
            nf = self._norm(fp)
            if str(PurePosixPath(nf).parent) == p:
                entries.add(PurePosixPath(nf).name)

        # Canary token paths — inject into parent dirs.
        try:
            from meli.labyrinth import canary as _canary
            for cp in _canary.all_paths():
                ncp = self._norm(cp)
                if str(PurePosixPath(ncp).parent) == p:
                    entries.add(PurePosixPath(ncp).name)
        except Exception:
            pass

        return sorted(entries)

    def read_file(self, path: str) -> str | None:
        """Return the content of *path* as a string, or None if not found.

        Fires a canary alert if the path is a bait token and this session
        has never tripped it before.
        """
        p = self._norm(path)

        # Canary check first — any read of a canary path fires the alert
        # regardless of whether we have static content for it.
        try:
            from meli.labyrinth import canary as _canary
            token_id = _canary.is_canary(p)
            if token_id is not None:
                _canary.trigger(
                    token_id=token_id,
                    session_id=self.session_id,
                    peer_ip=self.peer_ip,
                    protocol=self.protocol,
                    dst_port=self.dst_port,
                    command=f"cat {path}",
                )
                token = _canary.get(token_id)
                if token is not None:
                    return token.content
        except Exception as exc:
            log.debug("canary check failed", path=p, error=str(exc))

        if p in self._extra_files:
            return self._extra_files[p]
        if p in _STATIC_FILES:
            return _STATIC_FILES[p]
        return None
