"""
Fake shell command handlers for the Labyrinth tarpit.

Each entry in COMMANDS maps a Unix command name to a callable with signature:

    def handler(session: SessionLike, args: list[str]) -> str

where `session` is duck-typed (same surface works for both the asyncio
LabyrinthSession in shell.py and the sync SSHSession in ssh_server.py):

    session.fs              FakeFS
    session.username        str
    session.peer_ip         str
    session.command_history list[str]
    session.requested_exit  bool          (set True to end the session)

Handlers return a string (may contain \\n; the caller converts to \\r\\n for
SSH). Returning "" or None emits nothing. Handlers must never raise — callers
wrap them in try/except anyway, but raising makes logs noisy.

The set of commands is deliberately realistic: Mirai/Gafgyt loaders need ls,
cd, wget, chmod, busybox. Human pen-testers reach for id, whoami, uname, ip,
ps, cat, find. The handlers produce plausible output drawn from the session's
FakeFS so cross-referencing commands (ls /etc then cat /etc/passwd) produces
consistent results.
"""
from __future__ import annotations

import os
import random
import shlex
import textwrap
import time
from typing import Any, Callable

import structlog

log = structlog.get_logger()

# Type alias for the duck-typed session surface expected by handlers.
_Session = Any   # LabyrinthSession | SSHSession

HandlerFunc = Callable[[_Session, list[str]], str]


# ── helpers ──────────────────────────────────────────────────────────────


def unknown_response(cmd: str) -> str:
    """Return a bash-style 'command not found' message."""
    cmd_safe = (cmd or "").split()[0][:64] if cmd else ""
    return f"bash: {cmd_safe}: command not found\n"


def _hostname(session: _Session) -> str:
    try:
        h = session.fs.read_file("/etc/hostname")
        return (h or "").strip() or "srv-prod-01"
    except Exception:
        return "srv-prod-01"


def _fake_pid() -> int:
    return random.randint(10000, 60000)


def _fmt_size(n: int) -> str:
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n}{unit}"
        n //= 1024
    return f"{n}P"


# ── individual handlers ───────────────────────────────────────────────────


def _cmd_ls(session: _Session, args: list[str]) -> str:
    long_fmt = any(a.startswith("-") and "l" in a for a in args)
    all_files = any(a.startswith("-") and "a" in a for a in args)
    # Determine target path.
    paths = [a for a in args if not a.startswith("-")]
    target = paths[0] if paths else "."

    try:
        p = session.fs._norm(target)
        if session.fs.is_dir(p):
            entries = session.fs.listdir(p)
            if all_files:
                entries = [".", ".."] + entries
        elif session.fs.is_file(p):
            entries = [os.path.basename(p)]
            p = os.path.dirname(p)
        else:
            return f"ls: cannot access '{target}': No such file or directory\n"
    except Exception:
        return f"ls: cannot access '{target}': No such file or directory\n"

    if not entries:
        return ""

    if long_fmt:
        lines = []
        total = random.randint(4, 32) * 8
        lines.append(f"total {total}")
        for name in entries:
            full = p.rstrip("/") + "/" + name if p != "/" else "/" + name
            is_d = session.fs.is_dir(full)
            perm = "drwxr-xr-x" if is_d else "-rw-r--r--"
            size = 4096 if is_d else random.randint(100, 65536)
            t = time.strftime("%b %d %H:%M")
            lines.append(f"{perm}  2 root root {size:8d} {t} {name}")
        return "\n".join(lines) + "\n"
    else:
        return "  ".join(entries) + "\n"


def _cmd_cd(session: _Session, args: list[str]) -> str:
    target = args[0] if args else session.fs.home
    try:
        norm = session.fs._norm(target)
        if not session.fs.is_dir(norm):
            return f"bash: cd: {target}: No such file or directory\n"
        session.fs.cwd = norm
    except Exception:
        return f"bash: cd: {target}: No such file or directory\n"
    return ""


def _cmd_pwd(session: _Session, args: list[str]) -> str:
    return session.fs.cwd + "\n"


def _cmd_cat(session: _Session, args: list[str]) -> str:
    if not args:
        return ""
    out = []
    for fname in args:
        if fname.startswith("-"):
            continue
        try:
            content = session.fs.read_file(fname)
            if content is None:
                out.append(f"cat: {fname}: No such file or directory")
            else:
                out.append(content.rstrip("\n"))
        except Exception:
            out.append(f"cat: {fname}: No such file or directory")
    return "\n".join(out) + "\n" if out else ""


def _cmd_echo(session: _Session, args: list[str]) -> str:
    no_newline = args and args[0] == "-n"
    parts = args[1:] if no_newline else args
    text = " ".join(parts)
    return text if no_newline else text + "\n"


def _cmd_whoami(session: _Session, args: list[str]) -> str:
    return (session.username or "root") + "\n"


def _cmd_id(session: _Session, args: list[str]) -> str:
    user = session.username or "root"
    if user == "root":
        return "uid=0(root) gid=0(root) groups=0(root)\n"
    return f"uid=1000({user}) gid=1000({user}) groups=1000({user}),27(sudo)\n"


def _cmd_uname(session: _Session, args: list[str]) -> str:
    all_flag = any("a" in a for a in args if a.startswith("-"))
    kernel = "5.15.0-91-generic"
    arch = "x86_64"
    hostname = _hostname(session)
    if all_flag:
        return (
            f"Linux {hostname} {kernel} #101-Ubuntu SMP Tue Nov 14 "
            f"13:30:08 UTC 2023 {arch} {arch} {arch} GNU/Linux\n"
        )
    return f"Linux\n"


def _cmd_hostname(session: _Session, args: list[str]) -> str:
    return _hostname(session) + "\n"


def _cmd_ip(session: _Session, args: list[str]) -> str:
    if not args or args[0] in ("a", "addr", "address"):
        return (
            "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN\n"
            "    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00\n"
            "    inet 127.0.0.1/8 scope host lo\n"
            "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP qlen 1000\n"
            "    link/ether 52:54:00:ab:cd:ef brd ff:ff:ff:ff:ff:ff\n"
            "    inet 10.0.2.15/24 brd 10.0.2.255 scope global dynamic eth0\n"
        )
    if args[0] == "r" or args[0] == "route":
        return (
            "default via 10.0.2.1 dev eth0 proto dhcp metric 100\n"
            "10.0.2.0/24 dev eth0 proto kernel scope link src 10.0.2.15 metric 100\n"
        )
    return ""


def _cmd_ifconfig(session: _Session, args: list[str]) -> str:
    return (
        "eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n"
        "        inet 10.0.2.15  netmask 255.255.255.0  broadcast 10.0.2.255\n"
        "        ether 52:54:00:ab:cd:ef  txqueuelen 1000  (Ethernet)\n"
        "        RX packets 654321  bytes 987654321 (987.6 MB)\n"
        "        TX packets 234567  bytes 123456789 (123.4 MB)\n\n"
        "lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n"
        "        inet 127.0.0.1  netmask 255.0.0.0\n"
        "        loop  txqueuelen 1000  (Local Loopback)\n"
    )


def _cmd_ps(session: _Session, args: list[str]) -> str:
    lines = [
        "  PID TTY          TIME CMD",
        f"{_fake_pid()} pts/0    00:00:00 bash",
        f"{_fake_pid()} pts/0    00:00:00 ps",
    ]
    if any("a" in a or "e" in a for a in args if a.startswith("-")):
        # Extended process list
        lines = [
            "  PID TTY      STAT   TIME COMMAND",
            "    1 ?        Ss     0:01 /sbin/init",
            "  234 ?        Ss     0:00 /lib/systemd/systemd-journald",
            "  312 ?        Ss     0:00 /lib/systemd/systemd-udevd",
            "  501 ?        Ss     0:01 /usr/sbin/sshd -D",
            f" {_fake_pid()} pts/0    Ss     0:00 bash",
            f" {_fake_pid()} pts/0    R+     0:00 ps {''.join(args)}",
        ]
    return "\n".join(lines) + "\n"


def _cmd_w(session: _Session, args: list[str]) -> str:
    t = time.strftime("%H:%M:%S")
    user = session.username or "root"
    return (
        f" {t} up 14 days, 3:22,  1 user,  load average: 0.08, 0.04, 0.01\n"
        f"USER     TTY      FROM             LOGIN@   IDLE JCPU   PCPU WHAT\n"
        f"{user:<8s} pts/0    {session.peer_ip:<16s} {t}   0.00s  0.04s  0.00s -bash\n"
    )


def _cmd_last(session: _Session, args: list[str]) -> str:
    user = session.username or "root"
    return (
        f"{user}    pts/0        {session.peer_ip}  "
        f"{time.strftime('%a %b %d %H:%M')} - still logged in\n"
        f"reboot   system boot  5.15.0-91-generic "
        f"{time.strftime('%a %b %d')} 08:14\n\n"
        f"wtmp begins Mon Oct 23 00:00:01 2023\n"
    )


def _cmd_df(session: _Session, args: list[str]) -> str:
    return (
        "Filesystem      1K-blocks     Used Available Use% Mounted on\n"
        "tmpfs             1008328     1092   1007236   1% /run\n"
        "/dev/sda1        61255332 15234432  43879116  26% /\n"
        "tmpfs             5041640        0   5041640   0% /dev/shm\n"
        "tmpfs                5120        4      5116   1% /run/lock\n"
        "/dev/sda15          106858     6186    100672   6% /boot/efi\n"
    )


def _cmd_free(session: _Session, args: list[str]) -> str:
    human = any("h" in a for a in args if a.startswith("-"))
    if human:
        return (
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:           7.9Gi       1.2Gi       5.4Gi        12Mi       1.3Gi       6.5Gi\n"
            "Swap:          2.0Gi          0B       2.0Gi\n"
        )
    return (
        "               total        used        free      shared  buff/cache   available\n"
        "Mem:        8241152     1234567     5602567      12342     1404018     6654321\n"
        "Swap:       2097148           0     2097148\n"
    )


def _cmd_top(session: _Session, args: list[str]) -> str:
    # Minimal stub — bots mostly run top to check CPU; we give them a
    # one-frame dump and return.
    return (
        "top - " + time.strftime("%H:%M:%S") +
        " up 14 days,  3:22,  1 user,  load average: 0.08, 0.04, 0.01\n"
        "Tasks:  89 total,   1 running,  88 sleeping,   0 stopped,   0 zombie\n"
        "%Cpu(s):  0.3 us,  0.1 sy,  0.0 ni, 99.6 id,  0.0 wa,  0.0 hi\n"
        "MiB Mem:   8048.0 total,   5471.6 free,   1209.3 used,   1367.1 buff/cache\n"
        "MiB Swap:   2048.0 total,   2048.0 free,      0.0 used.   6591.2 avail Mem\n\n"
        "  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND\n"
        f"{_fake_pid():5d} root      20   0   18852   3684   3100 R   0.3   0.0   0:00.01 top\n"
        "    1 root      20   0  169168  12588   8904 S   0.0   0.2   0:01.34 systemd\n"
    )


def _cmd_netstat(session: _Session, args: list[str]) -> str:
    return (
        "Active Internet connections (only servers)\n"
        "Proto Recv-Q Send-Q Local Address           Foreign Address         State\n"
        "tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN\n"
        "tcp        0      0 127.0.0.1:3306          0.0.0.0:*               LISTEN\n"
        "tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN\n"
        "tcp6       0      0 :::22                   :::*                    LISTEN\n"
    )


def _cmd_ss(session: _Session, args: list[str]) -> str:
    return _cmd_netstat(session, args)


def _cmd_wget(session: _Session, args: list[str]) -> str:
    # Give the impression of downloading, then fail (no outbound net).
    url = next((a for a in args if a.startswith("http")), "unknown")
    fname = url.split("/")[-1][:32] or "index.html"
    return (
        f"--{time.strftime('%Y-%m-%d %H:%M:%S')}--  {url}\n"
        f"Resolving {url.split('/')[2] if '/' in url else url}... "
        f"connect: Connection refused\n"
    )


def _cmd_curl(session: _Session, args: list[str]) -> str:
    url = next((a for a in args if a.startswith("http")), "")
    return f"curl: (7) Failed to connect to {url}: Connection refused\n"


def _cmd_chmod(session: _Session, args: list[str]) -> str:
    # Accept silently — bots call chmod +x then expect the next command to work.
    return ""


def _cmd_mkdir(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_rm(session: _Session, args: list[str]) -> str:
    # Accept silently — don't error on rm -rf since bots expect it to succeed.
    return ""


def _cmd_cp(session: _Session, args: list[str]) -> str:
    if not args:
        return "cp: missing file operand\n"
    return ""


def _cmd_mv(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_touch(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_find(session: _Session, args: list[str]) -> str:
    # Return a plausible-looking find output for common queries.
    start = next((a for a in args if a.startswith("/")), session.fs.cwd)
    name_filter = None
    for i, a in enumerate(args):
        if a == "-name" and i + 1 < len(args):
            name_filter = args[i + 1]
    if name_filter:
        # Pretend we found nothing for most queries.
        return ""
    entries = session.fs.listdir(start)
    lines = [start]
    for e in entries[:20]:
        lines.append(f"{start.rstrip('/')}/{e}")
    return "\n".join(lines) + "\n"


def _cmd_grep(session: _Session, args: list[str]) -> str:
    # Consume args silently; return nothing (file has nothing of interest).
    return ""


def _cmd_awk(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_sed(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_head(session: _Session, args: list[str]) -> str:
    fargs = [a for a in args if not a.startswith("-")]
    if not fargs:
        return ""
    return _cmd_cat(session, [fargs[0]])


def _cmd_tail(session: _Session, args: list[str]) -> str:
    return _cmd_head(session, args)


def _cmd_history(session: _Session, args: list[str]) -> str:
    if args and args[0] == "-c":
        return ""
    lines = []
    for i, cmd in enumerate(session.command_history[-50:], start=1):
        lines.append(f"  {i:4d}  {cmd}")
    return "\n".join(lines) + "\n" if lines else ""


def _cmd_env(session: _Session, args: list[str]) -> str:
    return (
        "SHELL=/bin/bash\n"
        f"HOME={session.fs.home}\n"
        f"LOGNAME={session.username or 'root'}\n"
        f"USER={session.username or 'root'}\n"
        "TERM=xterm-256color\n"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        "LANG=en_US.UTF-8\n"
        "HISTSIZE=1000\n"
    )


def _cmd_export(session: _Session, args: list[str]) -> str:
    # Silently accept any export command.
    return ""


def _cmd_bash(session: _Session, args: list[str]) -> str:
    # Subshell — just return a new prompt (the loop handles this).
    return ""


def _cmd_sh(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_busybox(session: _Session, args: list[str]) -> str:
    if not args:
        return (
            "BusyBox v1.35.0 (2023-01-01 12:00:00 UTC) multi-call binary.\n"
            "Usage: busybox [function [arguments]...]\n"
        )
    sub = args[0]
    handler = COMMANDS.get(sub)
    if handler is not None:
        return handler(session, args[1:])
    return ""


def _cmd_python(session: _Session, args: list[str]) -> str:
    return "python3: No such file or directory\n"


def _cmd_python3(session: _Session, args: list[str]) -> str:
    return "python3: error while loading shared libraries: cannot open shared object file\n"


def _cmd_perl(session: _Session, args: list[str]) -> str:
    return "perl: warning: Setting locale failed.\n"


def _cmd_nc(session: _Session, args: list[str]) -> str:
    return "nc: getaddrinfo for host: Temporary failure in name resolution\n"


def _cmd_ncat(session: _Session, args: list[str]) -> str:
    return _cmd_nc(session, args)


def _cmd_netcat(session: _Session, args: list[str]) -> str:
    return _cmd_nc(session, args)


def _cmd_sudo(session: _Session, args: list[str]) -> str:
    if not args:
        return "usage: sudo [-D level] -h | -K | -k | -V\n"
    if args[0] == "-l":
        return f"User {session.username or 'root'} may run the following commands on {_hostname(session)}:\n    (ALL : ALL) ALL\n"
    # Run the command
    sub = args[0]
    handler = COMMANDS.get(sub)
    if handler is not None:
        return handler(session, args[1:])
    return unknown_response(sub)


def _cmd_su(session: _Session, args: list[str]) -> str:
    # Silently succeed (we're already in the shell).
    return ""


def _cmd_passwd(session: _Session, args: list[str]) -> str:
    return "passwd: Authentication token manipulation error\n"


def _cmd_crontab(session: _Session, args: list[str]) -> str:
    if "-l" in args:
        content = session.fs.read_file("/etc/crontab") or ""
        return content
    return ""


def _cmd_systemctl(session: _Session, args: list[str]) -> str:
    if not args:
        return ""
    if args[0] == "status":
        svc = args[1] if len(args) > 1 else "unknown"
        return (
            f"● {svc}.service\n"
            f"   Loaded: loaded (/lib/systemd/system/{svc}.service; enabled)\n"
            f"   Active: active (running) since "
            f"{time.strftime('%a %Y-%m-%d %H:%M:%S UTC')}; 14 days ago\n"
        )
    return ""


def _cmd_service(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_kill(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_pkill(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_apt(session: _Session, args: list[str]) -> str:
    return "E: Could not open lock file /var/lib/dpkg/lock - open (13: Permission denied)\n"


def _cmd_apt_get(session: _Session, args: list[str]) -> str:
    return _cmd_apt(session, args)


def _cmd_dpkg(session: _Session, args: list[str]) -> str:
    return "dpkg: error: requested operation requires superuser privilege\n"


def _cmd_which(session: _Session, args: list[str]) -> str:
    if not args:
        return ""
    cmd = args[0]
    known = {
        "ls": "/bin/ls", "cat": "/bin/cat", "bash": "/bin/bash",
        "sh": "/bin/sh", "python3": "/usr/bin/python3",
        "wget": "/usr/bin/wget", "curl": "/usr/bin/curl",
        "chmod": "/bin/chmod", "id": "/usr/bin/id",
    }
    return known.get(cmd, "") + ("\n" if cmd in known else "")


def _cmd_type(session: _Session, args: list[str]) -> str:
    if not args:
        return ""
    cmd = args[0]
    builtins = {"cd", "export", "echo", "history", "type", "alias", "read"}
    if cmd in builtins:
        return f"{cmd} is a shell builtin\n"
    path = _cmd_which(session, [cmd]).strip()
    if path:
        return f"{cmd} is {path}\n"
    return f"bash: type: {cmd}: not found\n"


def _cmd_date(session: _Session, args: list[str]) -> str:
    return time.strftime("%a %d %b %Y %H:%M:%S %Z") + "\n"


def _cmd_uptime(session: _Session, args: list[str]) -> str:
    return (
        " " + time.strftime("%H:%M:%S") +
        " up 14 days,  3:22,  1 user,  load average: 0.08, 0.04, 0.01\n"
    )


def _cmd_alias(session: _Session, args: list[str]) -> str:
    if not args:
        return (
            "alias ll='ls -alF'\nalias la='ls -A'\nalias l='ls -CF'\n"
            "alias grep='grep --color=auto'\n"
        )
    return ""


def _cmd_unset(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_read(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_printf(session: _Session, args: list[str]) -> str:
    if not args:
        return ""
    fmt = args[0]
    # Very minimal printf: just strip format specifiers and return remaining args.
    try:
        rest = " ".join(args[1:])
        return fmt.replace("%s", rest).replace("\\n", "\n").replace("\\t", "\t")
    except Exception:
        return ""


def _cmd_nproc(session: _Session, args: list[str]) -> str:
    try:
        content = session.fs.read_file("/proc/cpuinfo") or ""
        count = content.count("processor\t: ")
        return str(max(1, count)) + "\n"
    except Exception:
        return "4\n"


def _cmd_lscpu(session: _Session, args: list[str]) -> str:
    return (
        "Architecture:            x86_64\n"
        "CPU op-mode(s):          32-bit, 64-bit\n"
        "Thread(s) per core:      2\n"
        "Core(s) per socket:      4\n"
        "Socket(s):               1\n"
        "CPU(s):                  8\n"
        "Model name:              Intel(R) Core(TM) i7-10700K CPU @ 3.80GHz\n"
        "CPU MHz:                 3800.000\n"
        "L3 cache:                16384K\n"
    )


def _cmd_arch(session: _Session, args: list[str]) -> str:
    return "x86_64\n"


def _cmd_lsb_release(session: _Session, args: list[str]) -> str:
    if "-a" in args:
        return (
            "No LSB modules are available.\n"
            "Distributor ID:\tUbuntu\n"
            "Description:\tUbuntu 22.04.3 LTS\n"
            "Release:\t22.04\n"
            "Codename:\tjammy\n"
        )
    return "Ubuntu 22.04.3 LTS\n"


def _cmd_exit(session: _Session, args: list[str]) -> str:
    session.requested_exit = True
    return ""


def _cmd_logout(session: _Session, args: list[str]) -> str:
    session.requested_exit = True
    return ""


def _cmd_clear(session: _Session, args: list[str]) -> str:
    # ANSI clear screen + cursor home.
    return "\x1b[2J\x1b[H"


def _cmd_reset(session: _Session, args: list[str]) -> str:
    return "\x1b[2J\x1b[H"


def _cmd_true(session: _Session, args: list[str]) -> str:
    return ""


def _cmd_false(session: _Session, args: list[str]) -> str:
    return ""


# ── COMMANDS registry ─────────────────────────────────────────────────────

COMMANDS: dict[str, HandlerFunc] = {
    # Navigation
    "ls": _cmd_ls,
    "dir": _cmd_ls,
    "ll": _cmd_ls,
    "cd": _cmd_cd,
    "pwd": _cmd_pwd,
    # File operations
    "cat": _cmd_cat,
    "less": _cmd_cat,
    "more": _cmd_cat,
    "echo": _cmd_echo,
    "head": _cmd_head,
    "tail": _cmd_tail,
    "grep": _cmd_grep,
    "find": _cmd_find,
    "awk": _cmd_awk,
    "sed": _cmd_sed,
    "chmod": _cmd_chmod,
    "mkdir": _cmd_mkdir,
    "rm": _cmd_rm,
    "cp": _cmd_cp,
    "mv": _cmd_mv,
    "touch": _cmd_touch,
    "printf": _cmd_printf,
    # Identity / system info
    "whoami": _cmd_whoami,
    "id": _cmd_id,
    "uname": _cmd_uname,
    "hostname": _cmd_hostname,
    "arch": _cmd_arch,
    "nproc": _cmd_nproc,
    "lscpu": _cmd_lscpu,
    "lsb_release": _cmd_lsb_release,
    "date": _cmd_date,
    "uptime": _cmd_uptime,
    # Network
    "ip": _cmd_ip,
    "ifconfig": _cmd_ifconfig,
    "netstat": _cmd_netstat,
    "ss": _cmd_ss,
    "wget": _cmd_wget,
    "curl": _cmd_curl,
    "nc": _cmd_nc,
    "ncat": _cmd_ncat,
    "netcat": _cmd_netcat,
    # Process
    "ps": _cmd_ps,
    "top": _cmd_top,
    "w": _cmd_w,
    "last": _cmd_last,
    "kill": _cmd_kill,
    "pkill": _cmd_pkill,
    # Resources
    "df": _cmd_df,
    "free": _cmd_free,
    # Shell / scripting
    "env": _cmd_env,
    "export": _cmd_export,
    "history": _cmd_history,
    "alias": _cmd_alias,
    "unset": _cmd_unset,
    "read": _cmd_read,
    "which": _cmd_which,
    "type": _cmd_type,
    # Shell execution
    "bash": _cmd_bash,
    "sh": _cmd_sh,
    "busybox": _cmd_busybox,
    "python": _cmd_python,
    "python3": _cmd_python3,
    "perl": _cmd_perl,
    # Privilege escalation
    "sudo": _cmd_sudo,
    "su": _cmd_su,
    "passwd": _cmd_passwd,
    # Scheduling / services
    "crontab": _cmd_crontab,
    "systemctl": _cmd_systemctl,
    "service": _cmd_service,
    # Package management
    "apt": _cmd_apt,
    "apt-get": _cmd_apt_get,
    "dpkg": _cmd_dpkg,
    # Session
    "exit": _cmd_exit,
    "logout": _cmd_logout,
    "quit": _cmd_exit,
    "clear": _cmd_clear,
    "reset": _cmd_reset,
    # Misc
    "true": _cmd_true,
    "false": _cmd_false,
    "users": _cmd_w,
}
