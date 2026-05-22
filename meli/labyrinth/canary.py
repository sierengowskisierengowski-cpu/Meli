"""
Canary tokens for the Labyrinth tarpit.

A canary token is a bait file planted in the fake filesystem that fires
a CRITICAL alert the moment an attacker reads it. Reading `cat /root/.aws/
credentials` in a real environment is a high-confidence "this person is
exfiltrating" signal — in the maze, it's a free CRITICAL with a juicy
context payload (which token, which session, which IP) that the operator
sees in the Alerts view within seconds.

Each token has:
  * `path`            — absolute path inside the fake FS that triggers it
  * `summary`         — one-line "what an attacker thinks this is"
  * `content`         — the realistic-looking bait shown when read
  * `severity`        — INFO / LOW / MEDIUM / HIGH / CRITICAL
                        (used by Meli's classification pipeline)
  * `bot_signal`      — name added to the BotProfile when tripped
  * `score_bump`      — points added to the session's bot score on trip

Design choices:
  * The "credential material" is patently fake (AKIAFAKE..., RSA blocks
    that don't decode, password 'changeme'). We never want a real secret
    in source. The point is to look real to a *quick eyeballing* — the
    moment the attacker tries to USE one of these on real AWS, the call
    fails. They keep typing in the maze. We keep collecting telemetry.
  * Per-session dedup: a single attacker who `cat`s the same file three
    times only trips the canary once. Without this, a botnet looping
    over wget/cat would generate hundreds of duplicate CRITICAL alerts
    and the operator would tune them out.
  * Module-level state is keyed by session_id so the dedup automatically
    clears when the session ends (we discard via `discard_session`).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass(frozen=True)
class CanaryToken:
    token_id: str
    path: str
    summary: str
    content: str
    severity: str = "CRITICAL"
    bot_signal: str = "canary_trip"
    score_bump: int = 20


# ── Bait content (all FAKE — never reuse a real secret here) ────────────


_FAKE_AWS_CREDS = """[default]
aws_access_key_id = AKIA-FAKE7-TARPIT-HONEY
aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
region = us-east-1

[production]
aws_access_key_id = AKIA-FAKE-PRODUCTION-XX
aws_secret_access_key = QWxLkRrSv/HoneypotTarpit/Sierengowski/X
region = us-west-2
"""

_FAKE_SSH_KEY = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBfQUtFLU1FTEktSEFOTkVZUE9URURUQVJQSVRRSVZWVjAAAAAJgAAAAt
c3NoLWVkMjU1MTkAAAAgX0FLRS1NRUxJLUhPTkVZUE9URURUQVJQSVRRSVZWVjAAAAAQ
QURNSU5UQVJQSVRGQUtFRFNJRVJFTk1FTEkAAAAAAAAAAA==
-----END OPENSSH PRIVATE KEY-----
"""

_FAKE_ENV = """# production .env — do not commit
DATABASE_URL=postgres://app_prod:prodSecret123!@db-prod-internal.lan:5432/orders
REDIS_URL=redis://:r3disPassw0rd@cache.lan:6379/0
STRIPE_SECRET_KEY=sk_live_FAKE-TARPIT-HONEYPOT-DO-NOT-USE-KEY
SENDGRID_API_KEY=SG.FAKE-tarpit-honeypot-api-key.XXX-NOT-REAL-XXX
JWT_SECRET=ThisIsAFakeJwtSecretForTarpitOnlyDoNotUse
ADMIN_PASSWORD=changeme
"""

_FAKE_SHADOW = """root:$6$fakeSalt$bX0FAKEhashForTARPITbaitONLYneverREALusedZ:19500:0:99999:7:::
admin:$6$saltyFake$Y9wTarpitHoneyPotBaitFakeHashShadowFile.X:19500:0:99999:7:::
deploy:$6$honeyPot$T1qTarpitTrapFakeShadowHashNotARealHash.X:19500:0:99999:7:::
"""

_FAKE_PASSWORDS_TXT = """=== infra creds (sync to vault later) ===
prod-db          : prod_admin / Pr0dDb$ecretFAKE
prod-redis       : (no user)  / r3disPassw0rd
prod-grafana     : admin      / Gr@fan@FakeAdm1n
staging-ssh      : deploy     / dep1oyMeTarpit!
backup-rsync     : backup     / backupF@keBait2024
=== end ===
"""

_FAKE_WG_CONF = """[Interface]
Address = 10.66.66.1/24
ListenPort = 51820
PrivateKey = FAKEtarpitPrivateKeyXXXXXXXXXXXXXXXXXXXXXXX=

[Peer]
PublicKey  = FAKEtarpitPeerPublicKeyHoneypotBaitXXXXXXX=
PresharedKey = FAKEtarpitPSKHoneypotBaitDoNotUseXXXXX=
AllowedIPs = 10.66.66.2/32
"""

_FAKE_DB_DUMP = """-- PostgreSQL database dump
-- Dumped from database version 15.3
-- Server version 15.3

SET statement_timeout = 0;
SET client_encoding = 'UTF8';

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(255),
    password_hash character varying(255),
    api_token character varying(64)
);

COPY public.users (id, email, password_hash, api_token) FROM stdin;
1\tadmin@example.com\t$2b$12$FakeHashForTarpitBaitOnlyXX\tfake_tarpit_token_001
2\tdeploy@example.com\t$2b$12$FakeHashForTarpitBaitOnlyYY\tfake_tarpit_token_002
[... truncated, file is 4.2GB ...]
"""


# ── Token catalog ───────────────────────────────────────────────────────


CANARY_TOKENS: dict[str, CanaryToken] = {
    "aws_creds": CanaryToken(
        token_id="aws_creds",
        path="/root/.aws/credentials",
        summary="AWS access keys (~/.aws/credentials)",
        content=_FAKE_AWS_CREDS,
        severity="CRITICAL",
        bot_signal="canary_aws_creds",
        score_bump=25,
    ),
    "ssh_key": CanaryToken(
        token_id="ssh_key",
        path="/root/.ssh/id_rsa",
        summary="SSH private key",
        content=_FAKE_SSH_KEY,
        severity="CRITICAL",
        bot_signal="canary_ssh_key",
        score_bump=25,
    ),
    "env_file": CanaryToken(
        token_id="env_file",
        path="/opt/app/.env",
        summary="Production .env with DB/Stripe/JWT secrets",
        content=_FAKE_ENV,
        severity="CRITICAL",
        bot_signal="canary_env",
        score_bump=20,
    ),
    "shadow": CanaryToken(
        token_id="shadow",
        path="/etc/shadow",
        summary="/etc/shadow (read attempt)",
        content=_FAKE_SHADOW,
        severity="HIGH",
        bot_signal="canary_shadow",
        score_bump=20,
    ),
    "passwords_txt": CanaryToken(
        token_id="passwords_txt",
        path="/home/admin/passwords.txt",
        summary="Plaintext password file in admin home",
        content=_FAKE_PASSWORDS_TXT,
        severity="CRITICAL",
        bot_signal="canary_passwords",
        score_bump=20,
    ),
    "wireguard": CanaryToken(
        token_id="wireguard",
        path="/etc/wireguard/wg0.conf",
        summary="WireGuard VPN config",
        content=_FAKE_WG_CONF,
        severity="HIGH",
        bot_signal="canary_wireguard",
        score_bump=15,
    ),
    "db_dump": CanaryToken(
        token_id="db_dump",
        path="/var/backups/db_dump.sql",
        summary="Database dump (users table)",
        content=_FAKE_DB_DUMP,
        severity="HIGH",
        bot_signal="canary_db_dump",
        score_bump=15,
    ),
}


# Pre-computed reverse index: absolute path → token_id. The session's
# FakeFS does case-sensitive exact-path matching against this.
_PATH_INDEX: dict[str, str] = {t.path: tid for tid, t in CANARY_TOKENS.items()}


def all_paths() -> list[str]:
    """Every canary path. FakeFS uses this to seed bait into listings."""
    return list(_PATH_INDEX.keys())


def is_canary(path: str) -> str | None:
    """Returns the token_id matching `path`, or None."""
    return _PATH_INDEX.get(path)


def get(token_id: str) -> CanaryToken | None:
    return CANARY_TOKENS.get(token_id)


# ── per-session dedup ───────────────────────────────────────────────────


_tripped_lock = threading.Lock()
# session_id → set of token_ids already tripped this session
_tripped: dict[str, set[str]] = {}
# Defense-in-depth cap. discard_session() is called from the normal
# telnet/SSH finally blocks, but if a session crashes hard the entry
# would leak forever. _TRIPPED_MAX_SESSIONS bounds the dict; when we
# overshoot, we evict the oldest insertion (insertion order is
# preserved by dict in Python 3.7+).
_TRIPPED_MAX_SESSIONS = 4096


def already_tripped(session_id: str, token_id: str) -> bool:
    with _tripped_lock:
        return token_id in _tripped.get(session_id, set())


def mark_tripped(session_id: str, token_id: str) -> bool:
    """Mark token as tripped for this session. Returns True if this is
    the first trip (and the caller should emit the alert), False if it
    was already tripped earlier this session.

    Bounded by _TRIPPED_MAX_SESSIONS — oldest sessions evicted FIFO
    when the cap is hit. This is defense-in-depth against missed
    discard_session() calls; under normal disconnect flow the entry
    is freed promptly by the finally block in shell.py / ssh_server.py.
    """
    with _tripped_lock:
        s = _tripped.get(session_id)
        if s is None:
            # Evict oldest if we're at the cap, before inserting.
            while len(_tripped) >= _TRIPPED_MAX_SESSIONS:
                try:
                    oldest = next(iter(_tripped))
                    _tripped.pop(oldest, None)
                except StopIteration:
                    break
            s = set()
            _tripped[session_id] = s
        if token_id in s:
            return False
        s.add(token_id)
        return True


def discard_session(session_id: str) -> None:
    """Free per-session dedup state. Call on session end."""
    with _tripped_lock:
        _tripped.pop(session_id, None)


# ── trigger ─────────────────────────────────────────────────────────────


def trigger(token_id: str, session_id: str, peer_ip: str,
            protocol: str = "telnet", dst_port: int = 2323,
            command: str = "") -> bool:
    """Fire a canary trip. Returns True if the alert was emitted (first
    trip this session), False if it was deduped.

    This routes the event through the standard Labyrinth sink so it
    flows through the normal classification + alert + UI pipeline. The
    severity carried in `parsed_data` lets classification rules promote
    it to CRITICAL automatically, and the Alerts view picks it up.
    """
    token = get(token_id)
    if token is None:
        return False
    if not mark_tripped(session_id, token_id):
        return False

    # Bump the session's bot score — humans on legitimate boxes do not
    # cat /etc/shadow or /root/.aws/credentials. Any trip is a strong
    # adversarial signal regardless of timing characteristics.
    try:
        from meli.labyrinth import botdetect
        prof = botdetect.profile_for(session_id, peer_ip, protocol=protocol)
        prof.on_canary_trip(token.bot_signal, token.score_bump)
    except Exception:
        pass

    # Emit a dedicated canary event via the sink. We import lazily so
    # the canary module has no hard dep on sink (circular-import safe).
    try:
        from meli.labyrinth import sink
        sink.emit_canary(
            session_id=session_id,
            peer_ip=peer_ip,
            token_id=token.token_id,
            path=token.path,
            summary=token.summary,
            severity=token.severity,
            protocol=protocol,
            dst_port=dst_port,
            command=command,
        )
    except Exception as e:
        log.warning("canary sink emit failed", token=token_id, error=str(e))

    # Mirror the trip into the per-session replay log so playback
    # surfaces canary hits inline at the right moment.
    try:
        from meli.labyrinth import replay
        replay.record(session_id, peer_ip, protocol, "canary",
                      token_id=token.token_id, path=token.path,
                      summary=token.summary, severity=token.severity)
    except Exception:
        pass

    log.info("canary tripped",
             token=token_id, ip=peer_ip, session=session_id,
             protocol=protocol, severity=token.severity)
    return True
