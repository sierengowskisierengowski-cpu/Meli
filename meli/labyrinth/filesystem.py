"""
Procedurally generated fake filesystem for the Labyrinth tarpit.

The attacker thinks they're walking through a real Linux box. They are
walking through a deterministic-but-shifting hallucination that closes
doors behind them.

Design:
  * Every directory's contents are generated on demand from a seed,
    so we never store the full tree (it's infinite).
  * The seed = hash(canonical_path, session.displacement). The
    `displacement` integer increments on every `cd ..` so the attacker
    "returns" to a different version of the parent every time. They
    rarely notice — the structure looks similar enough.
  * Filenames look real: chosen from a curated pool of plausible Linux
    filenames + procedurally combined prefixes/suffixes. The pool is
    hand-curated rather than Markov-generated because Markov chains on
    short filenames produce obvious garbage ("sshdgrjk.cnf").
  * File "contents" are generated on read using extension-aware
    templates (.conf → fake INI, .log → fake syslog, .py → fake
    boilerplate, etc.).

This module is pure-Python, stdlib-only, importable without GTK.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

# ── Filename pools ──────────────────────────────────────────────────────
# Curated to look like a real Ubuntu/Debian box. Hand-picked.

_SYS_FILES = [
    "hosts", "hostname", "passwd", "shadow", "group", "fstab", "crontab",
    "motd", "issue", "resolv.conf", "profile", "bashrc", "bash.bashrc",
    "environment", "sudoers", "machine-id", "os-release", "timezone",
    "shells", "nsswitch.conf", "hosts.allow", "hosts.deny", "modules",
]
_CONFIG_FILES = [
    "sshd_config", "ssh_config", "nginx.conf", "apache2.conf", "my.cnf",
    "php.ini", "sysctl.conf", "redis.conf", "mongod.conf", "haproxy.cfg",
    "supervisord.conf", "fail2ban.conf", "logrotate.conf", "rsyslog.conf",
    "ntp.conf", "smb.conf", "named.conf", "dhcpd.conf", "exports",
]
_LOG_FILES = [
    "syslog", "auth.log", "kern.log", "dmesg", "boot.log", "daemon.log",
    "mail.log", "messages", "secure", "wtmp", "btmp", "lastlog", "faillog",
    "ufw.log", "nginx-access.log", "nginx-error.log", "mysql-slow.log",
]
_SCRIPT_FILES = [
    "main.py", "app.py", "server.py", "utils.py", "config.py", "models.py",
    "worker.py", "tasks.py", "settings.py", "requirements.txt",
    "package.json", "README.md", "Makefile", "Dockerfile", "docker-compose.yml",
    "manage.py", "wsgi.py", "gunicorn.conf", "entrypoint.sh", "init.sh",
]
_DATA_FILES = [
    "backup.sql", "dump.tar.gz", "archive.zip", "data.csv", "users.json",
    "export.xml", "snapshot.bin", "cache.db", "session.dat", "history.log",
]
_HIDDEN_FILES = [
    ".bash_history", ".bashrc", ".profile", ".ssh", ".gnupg", ".aws",
    ".docker", ".npm", ".cache", ".local", ".config",
]
_USER_DIRS = [
    "ubuntu", "admin", "deploy", "root", "www-data", "backup", "git",
    "postgres", "mysql", "redis", "jenkins", "ec2-user", "pi", "debian",
]
_PROJECT_DIRS = [
    "webapp", "api", "services", "backend", "frontend", "scripts", "tools",
    "deploy", "infra", "ansible", "terraform", "ci", "docs", "tests",
    "data", "logs", "tmp", "vendor", "build", "dist", "src", "lib",
]

# Realistic directory listings keyed by canonical path. Anything not in
# this map falls through to procedurally-generated contents based on
# whatever the path "feels like" (a user home, /etc, /var/log, etc.).
_CANONICAL_LAYOUT: dict[str, list[tuple[str, str]]] = {
    "/": [
        ("bin", "d"), ("boot", "d"), ("dev", "d"), ("etc", "d"),
        ("home", "d"), ("lib", "d"), ("media", "d"), ("mnt", "d"),
        ("opt", "d"), ("proc", "d"), ("root", "d"), ("run", "d"),
        ("sbin", "d"), ("srv", "d"), ("sys", "d"), ("tmp", "d"),
        ("usr", "d"), ("var", "d"),
    ],
    "/etc": [(n, "f") for n in _SYS_FILES[:10]] + [
        ("ssh", "d"), ("nginx", "d"), ("apache2", "d"), ("systemd", "d"),
        ("cron.d", "d"), ("apt", "d"), ("init.d", "d"),
    ],
    "/etc/ssh": [
        ("sshd_config", "f"), ("ssh_config", "f"),
        ("ssh_host_rsa_key", "f"), ("ssh_host_rsa_key.pub", "f"),
        ("ssh_host_ecdsa_key", "f"), ("ssh_host_ecdsa_key.pub", "f"),
        ("ssh_host_ed25519_key", "f"), ("ssh_host_ed25519_key.pub", "f"),
    ],
    "/var": [
        ("backups", "d"), ("cache", "d"), ("crash", "d"), ("lib", "d"),
        ("local", "d"), ("lock", "d"), ("log", "d"), ("mail", "d"),
        ("opt", "d"), ("run", "d"), ("spool", "d"), ("tmp", "d"), ("www", "d"),
    ],
    "/var/log": [(n, "f") for n in _LOG_FILES],
    "/root": [(n, "f") for n in (".bashrc", ".profile", ".bash_history")] + [
        (".ssh", "d"), (".config", "d"),
    ],
    "/home": [(u, "d") for u in _USER_DIRS[:4]],
    "/tmp": [],  # often empty
    "/proc": [
        ("cpuinfo", "f"), ("meminfo", "f"), ("version", "f"), ("uptime", "f"),
        ("loadavg", "f"), ("stat", "f"), ("self", "d"), ("net", "d"),
    ],
}

# ── Session-scoped procedural FS ────────────────────────────────────────


@dataclass
class FakeFS:
    """One procedurally-generated filesystem per attacker session.

    Doors-close-behind is implemented via `displacement`: every `cd ..`
    bumps it, which shifts the seed for every subsequent procedural
    directory the attacker visits. They navigate through what feels
    like the same box but is subtly different on every traversal.
    """
    session_seed: int                     # per-session base seed
    cwd: str = "/root"                    # current "working directory"
    home: str = "/root"                   # set per login (root by default)
    displacement: int = 0                 # bumps on every cd ..
    # Per-path content cache (path → list[(name,kind)]) — keeps a single
    # `ls` reproducible across repeated calls within the same displacement
    # epoch. Cleared whenever displacement changes (doors-close trick).
    _dir_cache: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # Optional session context for canary-token triggering. Set by the
    # owning LabyrinthSession / SSHSession right after construction.
    # When unset, FakeFS still works but canary trips are no-ops (the
    # token content is still returned so the FS looks correct).
    session_id: str = ""
    peer_ip: str = ""
    protocol: str = "telnet"
    dst_port: int = 2323

    # ---- navigation ---------------------------------------------------

    def resolve(self, target: str) -> str:
        """Canonicalize a path relative to cwd. Always returns absolute."""
        if not target or target == ".":
            return self.cwd
        if target == "~":
            return self.home
        if target.startswith("~/"):
            target = self.home.rstrip("/") + "/" + target[2:]
        if not target.startswith("/"):
            target = self.cwd.rstrip("/") + "/" + target
        # Normalize: collapse //, resolve . and ..
        parts: list[str] = []
        for part in target.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def chdir(self, target: str) -> str:
        """Change directory. Every `cd ..` shifts displacement (the
        defining Labyrinth trick). Every other cd just moves. Always
        succeeds — there is no "no such file or directory" in the maze.
        """
        # Was this a "go up" move? Bump displacement to shift the world.
        if target == ".." or target.endswith("/.."):
            self.displacement += 1
            self._dir_cache.clear()
        resolved = self.resolve(target)
        self.cwd = resolved or "/"
        return self.cwd

    # ---- listing ------------------------------------------------------

    def list_dir(self, path: str | None = None) -> list[tuple[str, str]]:
        """Return [(name, kind)] for the given path. kind is 'd' or 'f'.
        Stable within a displacement epoch so multiple `ls` calls in a
        row produce the same output.

        Canary-token paths whose directory matches `p` are merged into
        the listing so an attacker `ls`-ing /root/.aws actually sees
        `credentials`, /etc/wireguard sees `wg0.conf`, etc.
        """
        p = self.resolve(path) if path else self.cwd
        if p in self._dir_cache:
            return self._dir_cache[p]
        layout = _CANONICAL_LAYOUT.get(p)
        if layout is not None:
            entries = list(layout)
        else:
            entries = self._procedurally_generate(p)
        # Merge canary bait files whose parent dir == p
        merged = self._merge_canaries(p, entries)
        self._dir_cache[p] = merged
        return merged

    @staticmethod
    def _merge_canaries(dir_path: str, entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
        from meli.labyrinth import canary
        prefix = dir_path.rstrip("/") + "/"
        existing_names = {n for n, _ in entries}
        for cpath in canary.all_paths():
            if not cpath.startswith(prefix):
                continue
            tail = cpath[len(prefix):]
            if "/" in tail:
                # Canary lives in a deeper sub-dir; surface that sub-dir
                # as a directory entry so `ls` here looks plausible and
                # the attacker can `cd` into it.
                top = tail.split("/", 1)[0]
                if top not in existing_names:
                    entries.append((top, "d"))
                    existing_names.add(top)
            else:
                if tail not in existing_names:
                    entries.append((tail, "f"))
                    existing_names.add(tail)
        entries.sort(key=lambda x: (x[1] != "d", x[0]))
        return entries

    def _procedurally_generate(self, path: str) -> list[tuple[str, str]]:
        """Generate a plausible directory listing for an unknown path."""
        seed_str = f"{path}:{self.session_seed}:{self.displacement}"
        h = hashlib.md5(seed_str.encode()).digest()
        rng = random.Random(int.from_bytes(h[:8], "big"))

        entries: list[tuple[str, str]] = []
        flavor = self._flavor_of(path)

        if flavor == "user_home":
            # Realistic home directory: dotfiles + a few project dirs
            for f in (".bashrc", ".profile", ".bash_history", ".viminfo"):
                entries.append((f, "f"))
            for d in (".ssh", ".cache", ".config", ".local"):
                if rng.random() < 0.7:
                    entries.append((d, "d"))
            for d in rng.sample(_PROJECT_DIRS, k=rng.randint(1, 4)):
                entries.append((d, "d"))
        elif flavor == "var_log":
            for f in rng.sample(_LOG_FILES, k=rng.randint(6, 12)):
                entries.append((f, "f"))
        elif flavor == "etc":
            for f in rng.sample(_CONFIG_FILES, k=rng.randint(4, 8)):
                entries.append((f, "f"))
            for d in rng.sample(["nginx", "apache2", "systemd", "cron.d", "init.d"],
                                k=rng.randint(1, 3)):
                entries.append((d, "d"))
        elif flavor == "project":
            for f in rng.sample(_SCRIPT_FILES, k=rng.randint(3, 7)):
                entries.append((f, "f"))
            for d in rng.sample(["src", "lib", "tests", "docs", "scripts", "data"],
                                k=rng.randint(0, 3)):
                entries.append((d, "d"))
        else:
            # Generic dir: mix of files and subdirs
            for f in rng.sample(_SCRIPT_FILES + _DATA_FILES, k=rng.randint(2, 6)):
                entries.append((f, "f"))
            for d in rng.sample(_PROJECT_DIRS, k=rng.randint(0, 3)):
                entries.append((d, "d"))

        # Dedupe (procedural sampling can collide) and sort
        seen: set[str] = set()
        unique: list[tuple[str, str]] = []
        for name, kind in entries:
            if name not in seen:
                seen.add(name)
                unique.append((name, kind))
        unique.sort(key=lambda x: (x[1] != "d", x[0]))
        return unique

    @staticmethod
    def _flavor_of(path: str) -> str:
        if path.startswith("/home/") or path == "/root":
            depth = path.count("/")
            if depth <= 2:
                return "user_home"
            return "project"
        if path.startswith("/var/log"):
            return "var_log"
        if path.startswith("/etc"):
            return "etc"
        if path.startswith(("/opt", "/srv", "/usr/local")):
            return "project"
        return "generic"

    # ---- reading ------------------------------------------------------

    def read_file(self, path: str) -> str:
        """Return plausible content for `cat <path>`. Procedural.

        Canary-token paths short-circuit to the bait content AND fire
        a CRITICAL alert + bot-score bump via canary.trigger(). The
        attacker sees realistic-looking secrets; we see the trip.
        """
        resolved = self.resolve(path)
        from meli.labyrinth import canary
        token_id = canary.is_canary(resolved)
        if token_id is not None:
            token = canary.get(token_id)
            if token is not None:
                # Only trigger when we know which session is reading —
                # avoids stray triggers from constructed FakeFS instances
                # used in tests / one-off code paths.
                if self.session_id and self.peer_ip:
                    try:
                        canary.trigger(token_id, self.session_id, self.peer_ip,
                                       protocol=self.protocol,
                                       dst_port=self.dst_port,
                                       command=f"cat {path}")
                    except Exception:
                        pass
                return token.content
        from meli.labyrinth.fake_contents import contents_for
        return contents_for(resolved, self.session_seed, self.displacement)


def new_session_seed() -> int:
    """A fresh non-cryptographic seed for one Labyrinth session."""
    import os
    return int.from_bytes(os.urandom(8), "big")
