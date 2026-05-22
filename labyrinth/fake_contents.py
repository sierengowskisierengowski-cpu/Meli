"""
Fake file contents for the Labyrinth maze.

`contents_for(path, seed, displacement)` returns plausible-looking text
content for any path the attacker tries to `cat`. Procedural so the same
path always returns the same content within a displacement epoch.

The point isn't perfect accuracy — it's that the content reads like a
real Linux box at a glance, so the attacker spends another five minutes
digging through it before they get suspicious.

A handful of canonical paths get hard-coded responses (cat /etc/shadow
is the classic attacker first move and deserves a specific taunt).
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone


def _seeded(path: str, seed: int, displacement: int) -> random.Random:
    h = hashlib.md5(f"{path}:{seed}:{displacement}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


# ── Hardcoded content for high-value attacker targets ──────────────────

_HARDCODED: dict[str, str] = {
    "/etc/passwd": (
        "root:x:0:0:root:/root:/bin/bash\n"
        "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        "bin:x:2:2:bin:/bin:/usr/sbin/nologin\n"
        "sys:x:3:3:sys:/dev:/usr/sbin/nologin\n"
        "sync:x:4:65534:sync:/bin:/bin/sync\n"
        "www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n"
        "backup:x:34:34:backup:/var/backups:/usr/sbin/nologin\n"
        "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        "systemd-network:x:101:102:systemd Network Management,,,:/run/systemd:/usr/sbin/nologin\n"
        "sshd:x:104:65534::/run/sshd:/usr/sbin/nologin\n"
        "ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash\n"
    ),
    "/etc/shadow": (
        # A breadcrumb taunt — anyone who cats /etc/shadow gets a free
        # "got ya" early. Most attacker scripts grep for "$6$" so we
        # give them a valid-looking but harmless hash to chase.
        "root:HAHAHA_NICE_TRY:19234:0:99999:7:::\n"
        "daemon:*:19234:0:99999:7:::\n"
        "bin:*:19234:0:99999:7:::\n"
        "sys:*:19234:0:99999:7:::\n"
        "ubuntu:$6$xyzNICETRY$0123456789abcdef0123456789abcdef0123456789abcd:19234:0:99999:7:::\n"
        "honey:GOT_YA_FRIEND:19234:0:99999:7:::\n"
    ),
    "/etc/hostname": "ubuntu-prod-01\n",
    "/etc/os-release": (
        'NAME="Ubuntu"\n'
        'VERSION="22.04.3 LTS (Jammy Jellyfish)"\n'
        'ID=ubuntu\n'
        'ID_LIKE=debian\n'
        'PRETTY_NAME="Ubuntu 22.04.3 LTS"\n'
        'VERSION_ID="22.04"\n'
        'HOME_URL="https://www.ubuntu.com/"\n'
        'SUPPORT_URL="https://help.ubuntu.com/"\n'
        'BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"\n'
    ),
    "/proc/cpuinfo": (
        "processor\t: 0\n"
        "vendor_id\t: GenuineIntel\n"
        "cpu family\t: 6\n"
        "model\t\t: 85\n"
        "model name\t: Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz\n"
        "stepping\t: 4\n"
        "microcode\t: 0x2006b06\n"
        "cpu MHz\t\t: 2400.000\n"
        "cache size\t: 35840 KB\n"
        "physical id\t: 0\n"
        "siblings\t: 4\n"
        "core id\t\t: 0\n"
        "cpu cores\t: 4\n"
        "bogomips\t: 4800.00\n"
    ),
    "/proc/meminfo": (
        "MemTotal:        4039280 kB\n"
        "MemFree:         2103440 kB\n"
        "MemAvailable:    3206712 kB\n"
        "Buffers:           45120 kB\n"
        "Cached:           928904 kB\n"
        "SwapCached:            0 kB\n"
        "Active:           928012 kB\n"
        "Inactive:         580128 kB\n"
    ),
    "/proc/version": (
        "Linux version 5.15.0-91-generic (buildd@lcy02-amd64-074) "
        "(gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0, GNU ld (GNU Binutils for "
        "Ubuntu) 2.38) #101-Ubuntu SMP Tue Nov 14 13:30:08 UTC 2023\n"
    ),
}


# ── Procedural content by file extension ───────────────────────────────


def _conf_content(path: str, rng: random.Random) -> str:
    name = path.rsplit("/", 1)[-1]
    keys = ["bind_address", "port", "max_connections", "timeout", "log_level",
            "verbose", "user", "pid_file", "data_dir", "cache_size", "workers"]
    rng.shuffle(keys)
    lines = [
        f"# {name} — auto-generated configuration",
        f"# Last modified: 2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        "",
        "[main]",
    ]
    for k in keys[:6]:
        v = rng.choice(["true", "false", str(rng.randint(1, 9999)),
                        f'"/var/{rng.choice(["log", "run", "lib"])}/{name}.d"'])
        lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n"


def _log_content(path: str, rng: random.Random) -> str:
    """Generate plausible syslog-style log lines."""
    services = ["systemd", "sshd", "cron", "nginx", "kernel", "dhclient", "snapd"]
    msgs = [
        "Started Daily apt download activities.",
        "Accepted publickey for ubuntu from {ip} port {port} ssh2",
        "(CRON) info (No MTA installed, discarding output)",
        "client {ip} closed keepalive connection",
        "GET /api/v1/health HTTP/1.1 200 OK",
        "request DHCPREQUEST of {ip} on eth0",
        "Reloaded configuration.",
        "Time has been changed",
        "user session opened",
    ]
    lines = []
    now = datetime.now(timezone.utc) - timedelta(hours=2)
    for i in range(rng.randint(12, 24)):
        ts = now + timedelta(minutes=i * rng.randint(1, 6))
        svc = rng.choice(services)
        msg = rng.choice(msgs).format(
            ip=f"10.0.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
            port=rng.randint(30000, 60000),
        )
        pid = rng.randint(100, 9999)
        lines.append(
            f"{ts.strftime('%b %d %H:%M:%S')} ubuntu-prod-01 {svc}[{pid}]: {msg}"
        )
    return "\n".join(lines) + "\n"


def _python_content(rng: random.Random) -> str:
    return (
        '"""Application module."""\n'
        "from __future__ import annotations\n\n"
        "import os\n"
        "import sys\n"
        "import logging\n\n"
        "log = logging.getLogger(__name__)\n\n\n"
        "def main() -> int:\n"
        f'    log.info("starting workers=%d", {rng.randint(2, 16)})\n'
        '    return 0\n\n\n'
        'if __name__ == "__main__":\n'
        "    sys.exit(main())\n"
    )


def _env_content(rng: random.Random) -> str:
    # Realistic-looking but harmless. The keys are canaries — if anyone
    # ever tries them against a real service, we know they came from us.
    return (
        f"DB_HOST=db-prod-{rng.randint(1, 9)}.internal\n"
        f"DB_PORT=5432\n"
        f"DB_USER=appuser\n"
        f"DB_PASS=HONEYTRAP_{rng.randint(100000, 999999)}\n"
        f"REDIS_URL=redis://10.0.0.{rng.randint(2, 254)}:6379/0\n"
        f"AWS_ACCESS_KEY_ID=AKIA{''.join(rng.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567', k=16))}\n"
        f"AWS_SECRET_ACCESS_KEY={''.join(rng.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/+', k=40))}\n"
        f"SECRET_KEY={''.join(rng.choices('abcdef0123456789', k=64))}\n"
    )


def _bash_history_content(rng: random.Random) -> str:
    """Make .bash_history look like a sysadmin was last here. Drop a
    couple of breadcrumbs that will lead a curious attacker deeper into
    the maze (more time wasted = more intel for us)."""
    base = [
        "ls -la",
        "cd /var/log",
        "tail -f syslog",
        "sudo systemctl status nginx",
        "df -h",
        "free -m",
        "ps auxf",
        "netstat -tlnp",
        "vim /etc/nginx/nginx.conf",
        "git pull origin main",
        "docker ps",
        "kubectl get pods -A",
        "cat /root/credentials.txt",     # bait
        "scp backup.tar.gz admin@10.0.0.42:/backups/",  # bait
        f"mysql -h db-prod-{rng.randint(1, 9)}.internal -u root -p",
    ]
    rng.shuffle(base)
    return "\n".join(base[: rng.randint(8, 14)]) + "\n"


_CONF_EXTS = (".conf", ".cfg", ".ini", ".cnf", ".yml", ".yaml", ".toml")


def contents_for(path: str, seed: int, displacement: int) -> str:
    """Return the procedural content for `cat <path>`."""
    if path in _HARDCODED:
        return _HARDCODED[path]

    rng = _seeded(path, seed, displacement)
    name = path.rsplit("/", 1)[-1].lower()

    if name == ".bash_history":
        return _bash_history_content(rng)
    if name == ".env" or name.endswith(".env"):
        return _env_content(rng)
    if any(path.endswith(e) for e in _CONF_EXTS):
        return _conf_content(path, rng)
    if path.endswith((".log",)) or path.startswith("/var/log/"):
        return _log_content(path, rng)
    if path.endswith(".py"):
        return _python_content(rng)
    if path.endswith((".json",)):
        return '{\n  "version": "1.0",\n  "status": "ok",\n  "enabled": true\n}\n'
    if path.endswith((".sql",)):
        return (
            "-- backup\n"
            "CREATE TABLE users (id INT PRIMARY KEY, email TEXT, created_at TIMESTAMP);\n"
            f"INSERT INTO users VALUES (1, 'admin@example.com', '2024-01-01');\n"
        )
    if path.endswith((".sh",)):
        return "#!/bin/bash\nset -euo pipefail\necho \"starting\"\nexit 0\n"

    # Default: short, plausible plaintext
    return rng.choice([
        "OK\n",
        "enabled\n",
        "1\n",
        "# placeholder\n",
        "<empty>\n",
    ])
