# Bifrost - Local AI-Powered EDR Engine

Bifrost is an autonomous, local Endpoint Detection and Response (EDR) and AI-powered Anti-Virus engine built in pure Rust. Leveraging IBM Granite 3.3 2B running entirely offline, Bifrost delivers sub-250ms threat verdicts on raw system telemetry without relying on cloud APIs or external network connections.

## Overview

Traditional EDRs rely on cloud agents and continuous network access. Bifrost flips this model:

- **Zero-Cloud Design**: All AI analysis runs 100% locally. No SaaS, no API keys, no data leaving your machine.
- **Sub-250ms Verdicts**: Fast-path heuristics combined with a 4-bit quantized local model.
- **Dual-Component Architecture**:
  - **Bifrost (Inference Engine)**: Rust runner managing the local GGUF model via `llama-cpp-2`.
  - **Bifrost Daemon (Telemetry Monitor)**: Real-time `/proc` monitor that delegates suspicious events to the AI core.

## Features

- IBM Granite 3.3 2B fine-tuned for security threat detection
- Pure Rust performance - single native binary
- Real-time `/proc` process discovery
- Local logging to `/var/log/bifrost` and quarantine to `/var/bifrost/quarantine`
- Fast-path trusted process bypass (0ms for known-good processes)
- systemd service support

## Requirements

- Linux with `/proc` support
- Rust 2021 toolchain
- Optional: NVIDIA GPU with CUDA for faster hardware acceleration (libnccl required)

## Quick Start

Get Bifrost's interactive terminal dashboard and telemetry daemon running in under 5 minutes:

### 1. Build the Bifrost Binary
To compile on standard **CPU** (default, no CUDA Toolkit or GPU required):
```bash
cargo build --release
```
To compile with **CUDA** hardware acceleration enabled:
```bash
cargo build --release --features cuda
```

### 2. Set Up a GGUF Model
Bifrost requires a local GGUF model file. Download any quantized LLM (e.g. `ibm-granite/granite-3.3-2b-instruct` or similar) in GGUF format (Q4_K_M is recommended, ~1.4GB) and place it under `models/`:
```bash
mkdir -p models
# Place/download your GGUF model here:
# curl -L -o models/bifrost-q4.gguf <model_download_url>
```
If your GGUF file is located elsewhere or named differently, point the environment variable directly to it:
```bash
export BIFROST_MODEL="/path/to/your/model.gguf"
```

### 3. Run the Demo Dashboard
Execute the release binary with no arguments. This runs the internal demo suite and displays the control panel:
```bash
# Set default model path if not using the environment variable
mkdir -p models && touch models/bifrost-q4.gguf # Create a placeholder file to verify compilation
./target/release/bifrost
```
*Note: A valid, non-empty GGUF model is required for inference test runs. To skip model execution and just verify process scanning, launch the telemetry daemon directly.*

### 4. Start the Telemetry Monitor Daemon
To watch `/proc` in real-time, log verdicts to `/var/log/bifrost/`, and quarantine anomalies:
```bash
sudo BIFROST_MODEL=models/bifrost-q4.gguf ./target/release/bifrost-daemon
```

---

## Install (via script)

```bash
curl -fsSLO https://raw.githubusercontent.com/sierengowskisierengowski-cpu/Meli/main/install.sh && less install.sh && sudo bash install.sh
```

## Usage

```bash
# Set model path
export BIFROST_MODEL=/path/to/bifrost-q4.gguf

# Demo mode (runs 5 built-in tests)
./target/release/bifrost

# CLI mode (used by daemon)
./target/release/bifrost --guard "process event string"
./target/release/bifrost --alert "suspicious event description"
./target/release/bifrost --query "security question"
```

## Daemon

```bash
sudo mkdir -p /var/log/bifrost /var/bifrost/quarantine
export BIFROST_MODEL=/path/to/bifrost-q4.gguf
export BIFROST_BIN=/path/to/target/release/bifrost
sudo -E ./target/release/bifrost-daemon

# Or as systemd service
sudo systemctl enable --now bifrost-daemon
tail -f /var/log/bifrost/bifrost.log
```

## Performance

| Mode | Latency |
|------|---------|
| Guard | ~250ms |
| Alert | ~250ms |
| Query | ~1-4s |
| Trusted (cached) | 0ms |

## Training

See TRAINING.md for the full fine-tuning pipeline.

## Disclaimer

Bifrost is an experimental security research project. Use in controlled environments and security labs. Not a substitute for production-hardened EDR solutions.

## Author

Joseph Sierengowski - GowskiNet Security Lab

