# Project Status: Bifrost

Bifrost is an autonomous, local Endpoint Detection and Response (EDR) and AI-powered Anti-Virus engine built in pure Rust. It leverages local GGUF format models (such as quantized IBM Granite 3.3 2B) to deliver sub-250ms threat verdicts on raw system telemetry without relying on cloud APIs or external network connections.

---

## 🟢 Working (Core Features)

- **Inference Engine (`bifrost`)**:
  - High-performance, pure Rust runner managing local GGUF models via `llama-cpp-2` bindings.
  - Interactive offline query system (`--query`) and fast threat verdict capabilities (`--guard`, `--alert`).
  - Safe pre-check logic for fast-path bypass (0ms execution time) of known-good/trusted system files and administration tools.
- **System Event Telemetry Monitor Daemon (`bifrost-daemon`)**:
  - Multi-threaded, real-time process monitoring by actively scanning `/proc`.
  - Detection of compound suspicious process behaviors (e.g. download-to-shell pipes, base64-execs, hidden directories executing, reverse shells, privilege escalation).
  - Rate-limited local logging (safely capped at 100 entries per second to protect system resources) to `/var/log/bifrost/bifrost.log`.
  - Quarantine mechanism that immediately terminates (`kill -9`) confirmed threats and moves malicious binaries to `/var/bifrost/quarantine`.
- **Flexible Hardware Compatibility**:
  - Out-of-the-box CPU execution support (default) with standard C/C++ compilation.
  - Optional CUDA-enabled hardware acceleration flag (`--features cuda`) for NVIDIA GPUs to speed up inference times.
- **Fully Passing Test Suite**:
  - Automated unit tests covering telemetry analysis patterns, path trust checking, and classification logic.

---

## 🟡 In Progress

- **Refining Fine-Tuning Pipeline**:
  - Streamlining and documenting dataset generation and custom adapter training scripts (located in `training/`).
- **Standardizing Systemd Services**:
  - Migration of system services from the old `jett-daemon.service` format to native, fully compatible `bifrost-daemon.service` configuration.
- **Extended OS Telemetry**:
  - Enhancing daemon's process telemetry to capture deeper metadata (parent PIDs, user group contexts, environment variable scans).

---

## 🔵 Planned (Future Roadmap)

- **Interactive UI Dashboard**:
  - Integration of an HTML/web-based or lightweight local desktop GUI to view processed threat telemetry, active blocklists, system status, and interactive logs (combining the telemetry power of Bifrost with the visual dashboard elements of the preceding Meli command center).
- **Advanced Kernel-Level Monitoring**:
  - Upgrading from `/proc` scanning to modern kernel-level trace probes using eBPF, enabling instant kernel event detection and reducing user-space polling overhead.
- **Distributed Agent Management**:
  - Multi-node log aggregation allowing a single centralized command center to receive and analyze telemetry alerts from multiple Bifrost EDR endpoints.
