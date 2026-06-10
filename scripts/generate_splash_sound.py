#!/usr/bin/env python3
"""
Generate meli/assets/sounds/splash.wav procedurally.

Stdlib only — no numpy, no scipy. Produces a ~1.8s "honey drip + low
amber chime" suitable for the startup splash. Re-run this script any
time the splash sound needs to be regenerated.

The sound is composed of three layers, summed and normalised:
  1. Three honey drops at t=0.05, 0.35, 0.70 — short low-pass plops.
  2. A soft amber chime starting at t=0.90 — two stacked sines
     (220 Hz + 330 Hz) with exponential decay, evoking a struck bowl.
  3. A breathy noise sweep underneath the chime for warmth.
"""
from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DURATION    = 1.8          # seconds
N_SAMPLES   = int(SAMPLE_RATE * DURATION)
OUT_PATH    = Path(__file__).resolve().parent.parent / "assets" / "sounds" / "splash.wav"


def _drop(buf: list[float], t_start: float, base_freq: float = 90.0, length: float = 0.18) -> None:
    """Render a single honey-drop plop into buf, mixing additively."""
    start = int(t_start * SAMPLE_RATE)
    n     = int(length * SAMPLE_RATE)
    rng   = random.Random(int(t_start * 1000))
    for i in range(n):
        if start + i >= N_SAMPLES:
            break
        # Pitch slides downward — that's what makes it sound "wet"
        freq = base_freq * (1.0 - 0.55 * (i / n))
        # Exponential attack-decay envelope: fast attack, slow tail
        env = math.exp(-3.5 * i / n) * (1.0 - math.exp(-40.0 * i / n))
        # Body tone + a small amount of low-passed noise for the splash texture
        sample  = math.sin(2.0 * math.pi * freq * i / SAMPLE_RATE) * 0.65
        sample += math.sin(2.0 * math.pi * (freq * 1.5) * i / SAMPLE_RATE) * 0.20
        sample += (rng.random() * 2 - 1) * 0.15 * math.exp(-12.0 * i / n)
        buf[start + i] += sample * env * 0.55


def _chime(buf: list[float], t_start: float, length: float = 0.85) -> None:
    """Render the warm amber chime — two stacked sines with slow decay."""
    start = int(t_start * SAMPLE_RATE)
    n     = int(length * SAMPLE_RATE)
    for i in range(n):
        if start + i >= N_SAMPLES:
            break
        env = math.exp(-2.4 * i / n)
        # Fundamental + perfect fifth → warm, not metallic
        sample  = math.sin(2.0 * math.pi * 220.0 * i / SAMPLE_RATE) * 0.55
        sample += math.sin(2.0 * math.pi * 330.0 * i / SAMPLE_RATE) * 0.35
        # Subtle shimmer from a detuned octave
        sample += math.sin(2.0 * math.pi * 441.0 * i / SAMPLE_RATE) * 0.10
        buf[start + i] += sample * env * 0.40


def _breath(buf: list[float], t_start: float, length: float = 0.85) -> None:
    """Low-amplitude pink-ish noise bed underneath the chime for warmth."""
    start = int(t_start * SAMPLE_RATE)
    n     = int(length * SAMPLE_RATE)
    rng   = random.Random(0xBEEF)
    # Simple 1-pole low-pass on white noise → approximate pink
    prev = 0.0
    for i in range(n):
        if start + i >= N_SAMPLES:
            break
        white = rng.random() * 2 - 1
        prev  = prev * 0.92 + white * 0.08
        env   = math.exp(-1.8 * i / n) * (1.0 - math.exp(-25.0 * i / n))
        buf[start + i] += prev * env * 0.18


def main() -> None:
    buf = [0.0] * N_SAMPLES

    # Three drops at increasing pitch — feels like the pot is filling up
    _drop(buf, t_start=0.05, base_freq=80.0,  length=0.18)
    _drop(buf, t_start=0.35, base_freq=95.0,  length=0.18)
    _drop(buf, t_start=0.70, base_freq=115.0, length=0.20)

    # Soft sustained amber bloom
    _chime(buf,  t_start=0.90, length=0.88)
    _breath(buf, t_start=0.90, length=0.88)

    # Normalise to avoid clipping, with ~6 dB of headroom
    peak = max(abs(s) for s in buf) or 1.0
    scale = 0.78 / peak
    pcm = [int(max(-32767, min(32767, s * scale * 32767))) for s in buf]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT_PATH), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

    print(f"wrote {OUT_PATH}  ({OUT_PATH.stat().st_size:,} bytes, {DURATION:.2f}s @ {SAMPLE_RATE} Hz mono)")


if __name__ == "__main__":
    main()
