<p align="center">
  <strong>NanoCrew-Local</strong><br>
  <em>Multi-Agent AI on the Edge — No Cloud, No GPU, No Compromises</em>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" />
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green" />
  <img alt="Ollama" src="https://img.shields.io/badge/LLM-Ollama-orange?logo=data:image/svg+xml;base64," />
  <img alt="Telegram Bot" src="https://img.shields.io/badge/interface-Telegram-26A5E4?logo=telegram&logoColor=white" />
  <img alt="Hardware" src="https://img.shields.io/badge/target-16GB%20RAM%20·%20no%20GPU-critical" />
</p>

---

## What Is This?

**NanoCrew-Local** is an open-source Multi-Agent System (MAS) framework purpose-built for **hardware-constrained edge deployments**. It runs entirely on commodity hardware — an Intel Core i5, 16 GB RAM, no dedicated GPU — and delivers autonomous, multi-step AI workflows controlled via Telegram.

The default use-case is **continuous local device anomaly and fraud detection**: you send a natural-language instruction to a Telegram bot, and a pipeline of specialized AI agents triages the request, inspects your system with real commands, and reports findings — all without a single byte leaving your machine.

### Why Does This Matter?

Most multi-agent frameworks assume cloud-scale resources. NanoCrew-Local proves that **meaningful agentic AI can run on the hardware already on your desk**. This makes it ideal for:

- **Air-gapped security operations** where data cannot leave the premises
- **IoT edge nodes** with limited compute budgets
- **Privacy-first personal automation** with zero cloud dependency
- **Research and education** on multi-agent systems without GPU access

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Telegram Bot                        │
│              (whitelisted user auth)                     │
└──────────────────────┬──────────────────────────────────┘
                       │  /scan, /crew run
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Core Orchestrator                       │
│         (sequential pipeline engine)                     │
│                                                         │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐               │
│  │ Agent 1 │──▶│ Agent 2 │──▶│ Agent N │               │
│  │ (LLM)   │   │ (LLM +  │   │ (LLM)   │               │
│  │         │   │  exec?) │   │         │               │
│  └─────────┘   └─────────┘   └─────────┘               │
│       │             │             │                      │
│       └─────────────┴─────────────┘                      │
│              sequential only  🔒                         │
└──────────────────────┬──────────────────────────────────┘
                       │  one request at a time
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Ollama (Local LLM)                          │
│         http://localhost:11434                           │
│         default model: gemma4:4b                        │
│                                                         │
│         asyncio.Lock guarantees single                  │
│         inference — never OOM on 16 GB                  │
└─────────────────────────────────────────────────────────┘
```

**Key Innovation: Time-Shared LLM Access.** An `asyncio.Lock` inside the LLM client guarantees that only **one** Ollama inference runs at a time, across all users and all agents. No concurrent model loads, no RAM spikes, no OOM kills. Agents execute strictly sequentially — each one's output becomes the next one's input.

---

## Features

| Feature                      | Details                                                                          |
| ---------------------------- | -------------------------------------------------------------------------------- |
| **YAML-Driven Crews**        | Define agent teams as drop-in `.yaml` files in `crews/`. No code changes needed. |
| **Time-Shared LLM**          | `asyncio.Lock` ensures single-inference execution — safe on 16 GB RAM.           |
| **Hardware Awareness**       | Pre-flight RAM checks warn you before a pipeline exceeds available memory.       |
| **Sandboxed Code Execution** | Agents can run whitelisted system commands (opt-in, read-only, audited).         |
| **Telegram Interface**       | Full bot with `/scan`, `/crew list`, `/crew info`, `/crew run`, `/status`.       |
| **Whitelist Auth**           | Only approved Telegram usernames can issue commands. Fail-closed.                |
| **OS Auto-Detection**        | Command whitelists adapt to Linux or Windows automatically.                      |
| **Single-File Core**         | All logic in one `core_orchestrator.py` (~900 lines). Clone and run.             |
| **Ultra-Light Deps**         | 4 packages: `python-telegram-bot`, `python-dotenv`, `psutil`, `pyyaml`.          |

---

## Quick Start

### Prerequisites

- **Python 3.11+**
- **Ollama** installed and running ([ollama.com](https://ollama.com))
- A **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)

### 1. Clone and Install

```bash
git clone https://github.com/your-org/nanocrew-local.git
cd nanocrew-local
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Pull the Default Model

```bash
ollama pull gemma4:4b
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```ini
TELEGRAM_BOT_TOKEN=your-token-from-botfather
ALLOWED_USERNAMES=your_telegram_username
```

### 4. Run

```bash
python core_orchestrator.py
```

Open Telegram, find your bot, and send `/start`.

---

## Telegram Commands

| Command                          | Description                                 |
| -------------------------------- | ------------------------------------------- |
| `/start`                         | Welcome message and list available crews    |
| `/help`                          | Same as `/start`                            |
| `/scan <instruction>`            | Run the default crew on your instruction    |
| `/crew list`                     | List all loaded crews                       |
| `/crew info <name>`              | Show crew details and agent roster          |
| `/crew run <name> <instruction>` | Run a specific crew                         |
| `/status`                        | System health: Ollama, RAM, CPU, lock state |

**Example:**

```
/scan check for unusual network connections on high ports
```

---

## Creating Custom Crews

1. Copy `crews/_template.yaml` to a new file (e.g., `crews/log_analysis.yaml`).
2. Define your agents in pipeline order — each one's output feeds the next.
3. Restart the bot. It auto-discovers all `*.yaml` files in `crews/`.

```yaml
name: "Log Analysis"
description: "Analyze system logs for errors and anomalies."
recommended_max_ram_gb: 16

agents:
  - name: "Log Collector"
    role: "Gather and filter relevant log entries"
    can_execute: true # runs commands like journalctl, wevtutil
    system_prompt: |
      You are a log collection specialist...
    temperature: 0.3

  - name: "Anomaly Detector"
    role: "Identify patterns and anomalies in logs"
    system_prompt: |
      You receive filtered log data...
    temperature: 0.4
```

**Hardware guideline:** On 16 GB RAM with a 4B model, **3 agents** is the comfortable maximum per crew. Each additional agent adds context overhead.

---

## Code Execution

NanoCrew-Local can execute real system commands when agents need live data (network connections, process lists, log entries, etc.).

### Enabling

Set in your `.env` file:

```ini
ENABLE_CODE_EXECUTION=true
COMMAND_TIMEOUT=30
```

Then set `can_execute: true` on the relevant agent(s) in your crew YAML.

### Security Model

Code execution is **opt-in** and **defense-in-depth**:

| Layer                     | Protection                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Global kill switch**    | `ENABLE_CODE_EXECUTION=false` disables all execution system-wide                   |
| **Per-agent flag**        | Only agents with `can_execute: true` in YAML attempt execution                     |
| **Hardcoded whitelist**   | Only pre-approved read-only commands (frozen set in Python, not YAML-configurable) |
| **No shell mode**         | All commands use `exec()` — no shell metacharacter expansion                       |
| **Argument sanitization** | Shell metacharacters (`; &                                                         | $ \`` etc.) and path traversal (`../`) are blocked |
| **Clean environment**     | Subprocesses get a stripped env — no `.env` secrets leaked                         |
| **Temp working dir**      | Commands run in a disposable temp directory                                        |
| **Timeout**               | Hard kill after `COMMAND_TIMEOUT` seconds (default: 30)                            |
| **Output cap**            | Subprocess output truncated at 10 KB to prevent memory issues                      |
| **Audit logging**         | Every execution attempt (approved or blocked) is logged                            |

### Whitelisted Commands

**Linux:** `netstat`, `ss`, `ps`, `journalctl`, `systemctl`, `hostname`, `whoami`, `uptime`, `free`, `df`, `lsof`, `ip`, `cat`, `grep`, `ls`, `last`, `w`, `who`, `dmesg`, `route`, `arp`, `nslookup`, `ping`

**Windows:** `netstat`, `tasklist`, `ipconfig`, `hostname`, `whoami`, `systeminfo`, `wmic`, `wevtutil`, `findstr`, `type`, `dir`, `net`, `route`, `arp`, `nslookup`, `ping`

---

## Hardware Requirements

| Component   | Minimum                   | Recommended                 |
| ----------- | ------------------------- | --------------------------- |
| **CPU**     | Intel Core i5 (8th gen+)  | Any modern 4+ core CPU      |
| **RAM**     | 8 GB                      | 16 GB                       |
| **GPU**     | Not required              | Not required                |
| **Disk**    | 5 GB free (model storage) | 10 GB+                      |
| **OS**      | Linux or Windows          | Linux (lighter footprint)   |
| **Network** | Localhost only (Ollama)   | Telegram API access for bot |

**RAM Budget Breakdown (16 GB system):**

| Consumer                          | Estimate  |
| --------------------------------- | --------- |
| OS + system services              | ~4 GB     |
| Ollama + quantized 4B model       | ~4 GB     |
| Python process + pipeline context | ~1 GB     |
| **Headroom**                      | **~7 GB** |

---

## Project Structure

```
nanocrew-local/
├── core_orchestrator.py   # All framework logic (~900 lines)
├── requirements.txt       # 4 dependencies
├── .env.example           # Environment config template
├── LICENSE                # MIT
├── README.md              # This file
└── crews/
    ├── _template.yaml     # Documented template for new crews
    └── security_ops.yaml  # Default: anomaly & fraud detection
```

---

## Contributing

Contributions are welcome. This project values:

1. **Simplicity** — single-file core, minimal dependencies
2. **Safety** — defense-in-depth for code execution, fail-closed auth
3. **Resource discipline** — every feature must work on 16 GB RAM

To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Ensure your changes work on a 16 GB RAM system
4. Submit a pull request with a clear description

---

## License

[MIT](LICENSE) — free for personal, commercial, and research use.

---

<p align="center">
  Built for the machines you already own.<br>
  <strong>NanoCrew-Local</strong> — edge-native multi-agent AI.
</p>
