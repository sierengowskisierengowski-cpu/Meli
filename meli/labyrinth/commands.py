"""
Fake shell commands for the Labyrinth maze.

Each command takes (session, args) and returns a string (possibly empty)
to send back to the attacker. Commands NEVER actually execute anything —
they return procedurally-generated plausible output and log the attempt
through the session's sink so it lands in Meli's normal pipeline.

The 15 commands implemented here cover ~95% of what brute-force botnets
and curious attackers actually type in the first 10 minutes of a session.
Unknown commands are handled by the shell with a procedural fallback.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from meli.labyrinth.shell import LabyrinthSession


# ── ls / dir ────────────────────────────────────────────────────────────


def cmd_ls(session: "LabyrinthSession", args: list[str]) -> str:
    long_mode = any(a.startswith("-") and "l" in a for a in args)
    show_all  = any(a.startswith("-") and "a" in a for a in args)

    # Extract first non-flag arg as the target path
    target = next((a for a in args if not a.startswith("-")), None)
    entries = session.fs.list_dir(target)
    if not show_all:
        entries = [(n, k) for n, k in entries if not n.startswith(".")]

    if not long_mode:
        # Two-column output (typical terminal width approximation)
        return "  ".join(n for n, _ in entries) + ("\n" if entries else "")

    # Long mode — fake but plausible -l output
    out_lines = [f"total {len(entries) * 4}"]
    now = datetime.now(timezone.utc) - timedelta(days=3)
    for n, k in entries:
        perms = "drwxr-xr-x" if k == "d" else "-rw-r--r--"
        size = 4096 if k == "d" else (1024 + abs(hash(n)) % 65000)
        ts = now + timedelta(minutes=abs(hash(n)) % 10000)
        out_lines.append(
            f"{perms} 1 root root {size:>7} {ts.strftime('%b %d %H:%M')} {n}"
        )
    return "\n".join(out_lines) + "\n"


# ── cd / pwd ────────────────────────────────────────────────────────────


def cmd_cd(session: "LabyrinthSession", args: list[str]) -> str:
    target = args[0] if args else session.fs.home
    session.fs.chdir(target)
    return ""  # real cd is silent


def cmd_pwd(session: "LabyrinthSession", _args: list[str]) -> str:
    return session.fs.cwd + "\n"


# ── cat ─────────────────────────────────────────────────────────────────


def cmd_cat(session: "LabyrinthSession", args: list[str]) -> str:
    if not args:
        return ""  # real cat blocks on stdin — we just return nothing
    out = []
    for path in args:
        if path.startswith("-"):
            continue
        out.append(session.fs.read_file(path))
    return "".join(out)


# ── whoami / id / w / who ──────────────────────────────────────────────


def cmd_whoami(session: "LabyrinthSession", _args: list[str]) -> str:
    return session.username + "\n"


def cmd_id(session: "LabyrinthSession", _args: list[str]) -> str:
    if session.username == "root":
        return "uid=0(root) gid=0(root) groups=0(root)\n"
    return (
        f"uid=1000({session.username}) gid=1000({session.username}) "
        f"groups=1000({session.username}),27(sudo),100(users)\n"
    )


def cmd_w(session: "LabyrinthSession", _args: list[str]) -> str:
    now = datetime.now(timezone.utc)
    uptime = "up  6 days, 14:32"
    rng = random.Random(session.fs.session_seed)
    load = f"{rng.uniform(0.05, 1.2):.2f}, {rng.uniform(0.1, 0.9):.2f}, {rng.uniform(0.1, 0.7):.2f}"
    return (
        f" {now.strftime('%H:%M:%S')} {uptime},  1 user,  load average: {load}\n"
        "USER     TTY      FROM             LOGIN@   IDLE   JCPU   PCPU WHAT\n"
        f"{session.username:<8} pts/0    {session.peer_ip:<15}  "
        f"{now.strftime('%H:%M')}    0.00s  0.04s  0.00s w\n"
    )


def cmd_who(session: "LabyrinthSession", _args: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return (
        f"{session.username:<8} pts/0        "
        f"{now.strftime('%Y-%m-%d %H:%M')} ({session.peer_ip})\n"
    )


# ── uname ───────────────────────────────────────────────────────────────


def cmd_uname(session: "LabyrinthSession", args: list[str]) -> str:
    # Combine flags into one string for easy checking
    flags = "".join(a.lstrip("-") for a in args if a.startswith("-"))
    if not flags:
        return "Linux\n"
    parts = []
    if "a" in flags or "s" in flags:
        parts.append("Linux")
    if "a" in flags or "n" in flags:
        parts.append("ubuntu-prod-01")
    if "a" in flags or "r" in flags:
        parts.append("5.15.0-91-generic")
    if "a" in flags or "v" in flags:
        parts.append("#101-Ubuntu SMP Tue Nov 14 13:30:08 UTC 2023")
    if "a" in flags or "m" in flags:
        parts.append("x86_64")
    if "a" in flags or "o" in flags:
        parts.append("GNU/Linux")
    return " ".join(parts) + "\n"


# ── ps ──────────────────────────────────────────────────────────────────


_FAKE_PROCS = [
    ("root",     1,    "/sbin/init"),
    ("root",     2,    "[kthreadd]"),
    ("root",   421,    "/usr/lib/systemd/systemd-journald"),
    ("root",   438,    "/usr/lib/systemd/systemd-udevd"),
    ("systemd-network", 502, "/usr/lib/systemd/systemd-networkd"),
    ("root",   612,    "/usr/sbin/sshd -D"),
    ("root",   704,    "/usr/sbin/cron -f"),
    ("root",   712,    "/usr/sbin/rsyslogd -n"),
    ("www-data", 891,  "nginx: worker process"),
    ("root",   903,    "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock"),
    ("postgres", 1102, "postgres: 14/main: checkpointer"),
    ("redis",  1245,   "/usr/bin/redis-server 127.0.0.1:6379"),
]


def cmd_ps(_session: "LabyrinthSession", args: list[str]) -> str:
    flags = "".join(a.lstrip("-") for a in args if a.startswith("-"))
    full = ("a" in flags and "u" in flags) or "f" in flags or "e" in flags
    if not full:
        return (
            "    PID TTY          TIME CMD\n"
            "  12001 pts/0    00:00:00 bash\n"
            "  12042 pts/0    00:00:00 ps\n"
        )
    lines = ["USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"]
    rng = random.Random(42)
    for user, pid, cmd in _FAKE_PROCS:
        cpu = rng.uniform(0.0, 1.5)
        mem = rng.uniform(0.1, 5.0)
        vsz = rng.randint(20000, 800000)
        rss = rng.randint(800, 64000)
        lines.append(
            f"{user:<12} {pid:>5} {cpu:>4.1f} {mem:>4.1f} "
            f"{vsz:>6} {rss:>5} ?        Ss   Nov14   0:0{rng.randint(0, 9)} {cmd}"
        )
    return "\n".join(lines) + "\n"


# ── netstat ────────────────────────────────────────────────────────────


def cmd_netstat(_session: "LabyrinthSession", _args: list[str]) -> str:
    return (
        "Active Internet connections (only servers)\n"
        "Proto Recv-Q Send-Q Local Address           Foreign Address         State\n"
        "tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN\n"
        "tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN\n"
        "tcp        0      0 0.0.0.0:443             0.0.0.0:*               LISTEN\n"
        "tcp        0      0 127.0.0.1:5432          0.0.0.0:*               LISTEN\n"
        "tcp        0      0 127.0.0.1:6379          0.0.0.0:*               LISTEN\n"
        "tcp6       0      0 :::22                   :::*                    LISTEN\n"
    )


# ── wget / curl ────────────────────────────────────────────────────────


def cmd_wget(_session: "LabyrinthSession", args: list[str]) -> str:
    url = next((a for a in args if "://" in a or a.startswith("www.")), None)
    if not url:
        return "wget: missing URL\n"
    # Pretend the download succeeds. Real Mirai variants check the exit
    # code, not the file content, so this is enough to make them think
    # they got their payload through.
    rng = random.Random(hash(url) & 0xFFFFFFFF)
    size = rng.randint(8000, 250000)
    return (
        f"--{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}--  {url}\n"
        f"Resolving {url.split('/')[2] if '://' in url else url}... done.\n"
        f"Connecting to host... connected.\n"
        f"HTTP request sent, awaiting response... 200 OK\n"
        f"Length: {size} ({size // 1024}K)\n"
        f"Saving to: '{url.rsplit('/', 1)[-1] or 'index.html'}'\n\n"
        f"100%[======================================>] {size} 1.2MB/s in 0.{rng.randint(1, 9)}s\n\n"
        f"'{url.rsplit('/', 1)[-1] or 'index.html'}' saved [{size}/{size}]\n"
    )


def cmd_curl(_session: "LabyrinthSession", args: list[str]) -> str:
    url = next((a for a in args if "://" in a), None)
    if not url:
        return "curl: try 'curl --help' for more information\n"
    rng = random.Random(hash(url) & 0xFFFFFFFF)
    return "{\"status\":\"ok\",\"version\":\"1.0\",\"id\":%d}\n" % rng.randint(1000, 9999)


# ── housekeeping fakes ────────────────────────────────────────────────


def cmd_rm(_session: "LabyrinthSession", _args: list[str]) -> str:
    return ""  # silent success, like real rm


def cmd_mkdir(_session: "LabyrinthSession", _args: list[str]) -> str:
    return ""


def cmd_history(session: "LabyrinthSession", _args: list[str]) -> str:
    lines = []
    for i, cmd in enumerate(session.command_history[-50:], start=1):
        lines.append(f"  {i:>4}  {cmd}")
    return "\n".join(lines) + ("\n" if lines else "")


def cmd_echo(_session: "LabyrinthSession", args: list[str]) -> str:
    return " ".join(args) + "\n"


def cmd_uptime(_session: "LabyrinthSession", _args: list[str]) -> str:
    now = datetime.now(timezone.utc)
    return f" {now.strftime('%H:%M:%S')} up  6 days, 14:32,  1 user,  load average: 0.42, 0.31, 0.28\n"


def cmd_df(_session: "LabyrinthSession", _args: list[str]) -> str:
    return (
        "Filesystem      Size  Used Avail Use% Mounted on\n"
        "/dev/sda1        40G   18G   20G  48% /\n"
        "tmpfs           2.0G     0  2.0G   0% /dev/shm\n"
        "tmpfs           400M  1.2M  399M   1% /run\n"
        "/dev/sda2       100G   42G   53G  45% /var\n"
    )


def cmd_free(_session: "LabyrinthSession", _args: list[str]) -> str:
    return (
        "               total        used        free      shared  buff/cache   available\n"
        "Mem:         4039280     1850240     1103880       12480     1085160     1893744\n"
        "Swap:        2097148           0     2097148\n"
    )


def cmd_clear(_session: "LabyrinthSession", _args: list[str]) -> str:
    # ANSI clear screen + home cursor
    return "\x1b[2J\x1b[H"


def cmd_exit(session: "LabyrinthSession", _args: list[str]) -> str:
    session.requested_exit = True
    return ""  # the shell loop handles teardown


# ── registry ─────────────────────────────────────────────────────────


COMMANDS: dict[str, Callable[["LabyrinthSession", list[str]], str]] = {
    "ls": cmd_ls, "dir": cmd_ls, "ll": cmd_ls,
    "cd": cmd_cd, "pwd": cmd_pwd,
    "cat": cmd_cat, "less": cmd_cat, "more": cmd_cat, "head": cmd_cat, "tail": cmd_cat,
    "whoami": cmd_whoami, "id": cmd_id,
    "w": cmd_w, "who": cmd_who, "users": cmd_who,
    "uname": cmd_uname,
    "ps": cmd_ps,
    "netstat": cmd_netstat, "ss": cmd_netstat,
    "wget": cmd_wget, "curl": cmd_curl,
    "rm": cmd_rm, "unlink": cmd_rm,
    "mkdir": cmd_mkdir, "touch": cmd_mkdir,
    "history": cmd_history,
    "echo": cmd_echo,
    "uptime": cmd_uptime,
    "df": cmd_df, "free": cmd_free,
    "clear": cmd_clear,
    "exit": cmd_exit, "logout": cmd_exit, "quit": cmd_exit,
}


def unknown_response(cmd: str) -> str:
    """The default 'bash: ...: command not found' line for everything else."""
    return f"bash: {cmd}: command not found\n"
