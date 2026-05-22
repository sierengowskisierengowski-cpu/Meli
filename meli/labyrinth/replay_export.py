"""
Replay export — convert a Labyrinth replay JSONL into an asciinema v2
`.cast` file so the user can share / embed / re-watch sessions in any
asciinema-compatible player (asciinema CLI, asciinema-player web embed,
GitHub README, etc.).

asciinema cast v2 format:
  Line 1: JSON header object
  Line 2+: 3-element arrays [t_seconds_float, "o", "output_text"]

We synthesize realistic terminal output from our higher-level events
(connect/login/command/canary/disconnect). Commands appear typed out
followed by a fake prompt+newline; canary trips render as bracketed
red-text notes; disconnect shows a synthetic banner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HEADER_DEFAULTS = {
    "version": 2,
    "width": 100,
    "height": 30,
    "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
}


@dataclass
class ExportOptions:
    width: int = 100
    height: int = 30
    title: str = "Meli Labyrinth replay"
    # ANSI color escapes for visual variety in the cast.
    color_canary: str = "\x1b[1;31m"        # bold red
    color_meta: str = "\x1b[2;37m"          # dim white
    color_login: str = "\x1b[1;33m"         # bold yellow
    color_tripwire: str = "\x1b[1;35m"      # bold magenta
    color_reset: str = "\x1b[0m"


def _line(t: float, text: str) -> list:
    return [round(float(t), 4), "o", text]


def _prompt(user: str = "root", host: str = "srv") -> str:
    return f"{user}@{host}:~# "


def export(events: Iterable[dict], opts: ExportOptions | None = None) -> str:
    """Render an iterable of replay events as an asciinema v2 cast string."""
    opts = opts or ExportOptions()

    header = dict(HEADER_DEFAULTS)
    header.update({
        "width": opts.width,
        "height": opts.height,
        "title": opts.title,
    })

    out_lines: list[str] = [json.dumps(header, separators=(",", ":"))]

    user = "root"
    host = "srv"
    sent_prompt = False

    for ev in events:
        t = float(ev.get("t", 0.0))
        kind = ev.get("kind", "")
        if kind == "connect":
            ip = ev.get("ip", "")
            proto = ev.get("proto") or ev.get("protocol", "")
            text = (f"{opts.color_meta}[connect: {ip} via {proto}]"
                    f"{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))
        elif kind == "login_fail":
            u = ev.get("user", "")
            p = ev.get("password", "")
            text = (f"{opts.color_login}login: {u}  password: {p}  "
                    f"-> FAILED{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))
        elif kind == "login_ok":
            u = ev.get("user", "") or "root"
            user = u or user
            text = (f"{opts.color_login}login: {u}  -> OK"
                    f"{opts.color_reset}\r\n"
                    f"Welcome to {host}.\r\n")
            out_lines.append(json.dumps(_line(t, text)))
            # First prompt
            out_lines.append(json.dumps(_line(t + 0.05, _prompt(user, host))))
            sent_prompt = True
        elif kind == "command":
            cmd = str(ev.get("text", ""))
            # Type out: each char ~30ms apart, plus newline + fake output line
            if not sent_prompt:
                out_lines.append(json.dumps(_line(t, _prompt(user, host))))
                sent_prompt = True
            base = t
            for i, ch in enumerate(cmd[:1024]):
                out_lines.append(json.dumps(_line(base + i * 0.03, ch)))
            out_lines.append(json.dumps(
                _line(base + len(cmd) * 0.03 + 0.02, "\r\n")))
            # Synthetic response: we don't always have the real one in the
            # replay log (responses aren't recorded by default), so a
            # short placeholder keeps the cast watchable.
            resp_t = base + len(cmd) * 0.03 + 0.08
            out_lines.append(json.dumps(_line(resp_t, "")))
            # Next prompt at t+~0.1s
            out_lines.append(json.dumps(
                _line(resp_t + 0.05, _prompt(user, host))))
        elif kind == "canary":
            text = (f"{opts.color_canary}"
                    f"[!! CANARY: {ev.get('token_id','?')} "
                    f"({ev.get('severity','?')}) — "
                    f"{ev.get('summary','')}]{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))
        elif kind == "tripwire":
            text = (f"{opts.color_tripwire}"
                    f"[tripwire: {ev.get('label','?')} ({ev.get('severity','?')}) "
                    f"+{ev.get('score','?')}]{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))
        elif kind == "disconnect":
            text = (f"{opts.color_meta}[disconnect — "
                    f"{ev.get('duration', 0):.1f}s, "
                    f"{ev.get('commands', 0)} cmds, "
                    f"bot {ev.get('bot_score','?')}/{ev.get('bot_confidence','?')}]"
                    f"{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))
        elif kind == "truncated":
            text = (f"{opts.color_meta}[... replay truncated: "
                    f"{ev.get('reason','cap')} ...]{opts.color_reset}\r\n")
            out_lines.append(json.dumps(_line(t, text)))

    return "\n".join(out_lines) + "\n"


def export_file(replay_path: Path, out_path: Path,
                opts: ExportOptions | None = None) -> Path:
    """Read a replay JSONL and write an asciinema cast to `out_path`.
    Returns the output path."""
    from meli.labyrinth import replay
    events = list(replay.load_session(replay_path))
    cast = export(events, opts=opts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(cast, encoding="utf-8")
    return out_path
