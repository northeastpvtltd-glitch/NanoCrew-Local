<p align="center">
  <strong>NanoCrew-Local</strong><br>
  <em>Build any AI-powered company — runs on the laptop you already own</em>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" />
  <img alt="License: AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-blue" />
  <img alt="Ollama" src="https://img.shields.io/badge/LLM-Ollama-orange?logo=data:image/svg+xml;base64," />
  <img alt="Claude" src="https://img.shields.io/badge/LLM-Claude-blueviolet" />
  <img alt="OpenAI" src="https://img.shields.io/badge/LLM-OpenAI--compatible-green" />
  <img alt="OpenClaw" src="https://img.shields.io/badge/OpenClaw-integrated-red" />
  <img alt="Telegram Bot" src="https://img.shields.io/badge/interface-Telegram-26A5E4?logo=telegram&logoColor=white" />
  <img alt="Hardware" src="https://img.shields.io/badge/target-16GB%20RAM%20·%20no%20GPU-critical" />
</p>

---

## What Is This?

**NanoCrew-Local** lets any user build any type of AI-powered company — a startup, a marketing agency, a law firm, a support center, a security ops team, a content studio — and run it entirely on the hardware they already own.

A **crew** is a YAML file. An **agent** is an employee: a job title, a role, and a system prompt that _is_ their brain. Work flows down the org chart — each agent's output becomes the next agent's input. Send a task via Telegram; your company handles it locally. Nothing leaves your machine.

```yaml
# example: a 3-person content studio
name: "Content Studio"
agents:
  - name: "Brief Writer" # receives your raw idea
    role: "Turn a topic into a detailed content brief"
    system_prompt: "You are a senior content strategist..."
    temperature: 0.5
  - name: "Copywriter" # receives the brief
    role: "Write a first draft from the brief"
    system_prompt: "You are a professional copywriter..."
    temperature: 0.7
  - name: "Editor" # receives the draft
    role: "Polish the copy and prepare it for publishing"
    system_prompt: "You are a meticulous editor..."
    temperature: 0.3
```

This is the entire mental model. The rest is plumbing.

### Philosophy

Inspired by Karpathy's **nanoGPT** — _"the simplest, fastest repository… plain and readable, very easy to hack to your needs"_:

- **One file** — all logic in `core_orchestrator.py`. No package to install; just clone and run.
- **YAML = org chart** — no code required to define a new company or add employees
- **One dial** — more agents = bigger pipeline. Everything else is automatic.
- **No giant config objects** — no model factories, no if-then-else monsters
- **Maximally forkable** — clone, remove what you don't need, add what you do

### Any Company. Any Industry.

| Company Type     | Example Pipeline                                     |
| ---------------- | ---------------------------------------------------- |
| Tech Startup     | CEO Adviser → Developer → Product Writer             |
| Marketing Agency | Strategist → Copywriter → Analytics Reporter         |
| Customer Support | Triage Agent → Resolver → Escalation Manager         |
| Legal Firm       | Intake → Researcher → Brief Writer                   |
| Security Ops     | Analyst → Engineer → Reporter _(ships by default)_   |
| Content Studio   | Brief Writer → Copywriter → Editor                   |
| Finance Team     | Data Collector → Analyst → CFO Summary               |
| HR Department    | Screener → Interview Planner → Offer Writer          |
| E-Commerce       | Product Researcher → Listing Writer → SEO Reviewer   |
| Healthcare Admin | Intake → Clinical Advisor → Documentation Specialist |

Drop a YAML file in `crews/` and your new company is live on the next bot restart.

### Why Local?

- **No per-token bills** — Ollama runs the model on your own hardware
- **Privacy first** — data never leaves your machine
- **Air-gap friendly** — works without any internet after initial setup
- **Research and education** — full agentic AI without GPU access

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
│  │ (LLM)   │   │ (code   │   │ (LLM)   │               │
│  │         │   │  loop?) │   │         │               │
│  └─────────┘   └─────────┘   └─────────┘               │
│       │             │             │                      │
│       └─────────────┴─────────────┘                      │
│              sequential only  🔒                         │
└──────────────────────┬──────────────────────────────────┘
                       │  one request at a time
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Multi-Provider LLM                          │
│                                                         │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐     │
│  │  Ollama  │  │  Claude   │  │ OpenAI-compatible │     │
│  │  (local) │  │  (API)    │  │ (OpenAI/Groq/...)│     │
│  └──────────┘  └───────────┘  └──────────────────┘     │
│                                                         │
│         asyncio.Lock guarantees single                  │
│         inference — never OOM on 16 GB                  │
└─────────────────────────────────────────────────────────┘
```

**Key Innovation: Time-Shared LLM Access.** An `asyncio.Lock` inside the LLM client guarantees that only **one** inference runs at a time, across all providers, users, and agents. No concurrent model loads, no RAM spikes, no OOM kills. Agents execute strictly sequentially — each one's output becomes the next one's input.

---

## Features

| Feature                      | Details                                                                                              |
| ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| **YAML-Driven Crews**        | Define agent teams as drop-in `.yaml` files in `crews/`. No code changes needed.                     |
| **Multi-Provider LLM**       | Ollama (local), Claude API, OpenAI-compatible (Groq, Together, vLLM). Per-agent model override.      |
| **Time-Shared LLM**          | `asyncio.Lock` ensures single-inference execution — safe on 16 GB RAM.                               |
| **Coding Agent Loop**        | Agents with `can_code: true` write code → execute → read output → self-correct (up to N iterations). |
| **Hardware Awareness**       | Pre-flight RAM checks warn you before a pipeline exceeds available memory.                           |
| **Sandboxed Code Execution** | Agents can run whitelisted system commands (opt-in, read-only, audited).                             |
| **OpenClaw Integration**     | Bidirectional bridge: accept tasks from OpenClaw, send results back. REST API + WebSocket.            |
| **Telegram Interface**       | Full bot with `/scan`, `/crew list`, `/crew info`, `/crew run`, `/status`.                           |
| **Live Dashboard**           | Local web UI at `http://127.0.0.1:8585` — real-time agent activity, system metrics, AI suggestions.  |
| **Whitelist Auth**           | Only approved Telegram usernames can issue commands. Fail-closed.                                    |
| **OS Auto-Detection**        | Command whitelists adapt to Linux or Windows automatically.                                          |
| **Single-File Core**         | All logic in one `core_orchestrator.py`. Clone and run.                                              |
| **Ultra-Light Deps**         | 5 packages: `python-telegram-bot`, `python-dotenv`, `psutil`, `pyyaml`, `aiohttp`.                   |

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

## Live Dashboard

NanoCrew-Local ships with a **local web dashboard** that launches automatically alongside the bot.

**Default URL:** `http://127.0.0.1:8585`

### What You See

| Panel                | Description                                                                    |
| -------------------- | ------------------------------------------------------------------------------ |
| **System Resources** | Real-time CPU, RAM, and disk usage with color-coded progress bars              |
| **Ollama Status**    | Model name, online/offline status, LLM lock state, code execution toggle       |
| **Companies**        | All loaded crews with their agents — active agents glow green during pipelines |
| **Live Activity**    | Timestamped feed of agent starts and completions, streamed via WebSocket       |
| **AI Suggestions**   | One-click button asks your LLM to analyze your setup and suggest improvements  |

### Configuration

```ini
# In .env
DASHBOARD_HOST=127.0.0.1   # Bind address (default: localhost only)
DASHBOARD_PORT=8585         # Port (default: 8585)
```

The dashboard requires **no authentication** — it binds to `127.0.0.1` by default (localhost only, not reachable from the network). If you change `DASHBOARD_HOST` to `0.0.0.0`, the dashboard becomes network-accessible — only do this on trusted networks.

---

## Creating Your Company

1. Copy `crews/_template.yaml` to a new file (e.g., `crews/my_company.yaml`).
2. Define your agents (employees) in pipeline order — each one's output feeds the next.
3. Restart the bot. It auto-discovers all `*.yaml` files in `crews/`.

```yaml
name: "Marketing Agency"
description: "Plan and write marketing campaigns from a single brief."
recommended_max_ram_gb: 16

agents:
  - name: "Strategist"
    role: "Develop a campaign strategy from the raw brief"
    system_prompt: |
      You are a senior marketing strategist.
      Receive a raw campaign brief and produce a structured strategy:
      target audience, key message, channels, tone of voice.
    temperature: 0.6

  - name: "Copywriter"
    role: "Write campaign copy from the strategy"
    system_prompt: |
      You receive a marketing strategy.
      Write compelling ad copy, email subject lines, and social posts.
      Match the tone and targeting from the strategy exactly.
    temperature: 0.7

  - name: "Analytics Reporter"
    role: "Suggest KPIs and success metrics for the campaign"
    system_prompt: |
      You receive campaign copy and strategy.
      Propose specific, measurable KPIs and a reporting cadence.
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

## Multi-Provider LLM

NanoCrew-Local defaults to **Ollama** (free, local, private) but can route agent requests to **Claude** or any **OpenAI-compatible** endpoint.

### Setup

Add API keys to your `.env`:

```ini
# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI / Groq / Together / local vLLM
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1   # Change for other providers
```

### Per-Agent Model Override

In any crew YAML, set `model:` with a provider prefix:

```yaml
agents:
  - name: "Strategist"
    model: claude:claude-sonnet-4-20250514 # Uses Claude API
    # model: openai:gpt-4o              # Uses OpenAI-compatible API
    # model: ollama:gemma4:4b            # Explicit Ollama (same as default)
    # model: gemma4:4b                   # No prefix → uses DEFAULT_PROVIDER
```

### Mixing Providers in One Crew

```yaml
agents:
  - name: "Planner"
    model: claude:claude-sonnet-4-20250514 # Cloud for complex reasoning
    role: "Plan the approach"
    system_prompt: "..."

  - name: "Executor"
    model: ollama:gemma4:4b # Local for fast, simple tasks
    role: "Execute the plan"
    system_prompt: "..."
```

The `asyncio.Lock` applies across all providers — only one inference at a time, regardless of backend. This keeps RAM safe when mixing local and cloud models.

---

## Coding Agent

The **coding agent loop** lets agents write code, execute it in a sandbox, read the output, and self-correct — like Claude Code or Open Interpreter, but integrated into your crew pipeline.

### Enabling

```ini
# In .env
ENABLE_CODE_AGENT=true
CODE_AGENT_MAX_ITERATIONS=5    # Max write-execute-fix cycles
CODE_AGENT_TIMEOUT=60          # Seconds per execution
```

Then set `can_code: true` on the relevant agent(s) in your crew YAML:

````yaml
agents:
  - name: "Coder"
    can_code: true
    role: "Write and execute code"
    system_prompt: "Write code in ```python blocks..."
    temperature: 0.2
````

### How It Works

1. Agent receives the task (or previous agent's output)
2. LLM generates a response with fenced code blocks
3. Code is extracted and executed in a sandboxed subprocess
4. If execution fails, errors are fed back to the LLM
5. LLM fixes the code and tries again (up to `CODE_AGENT_MAX_ITERATIONS`)
6. Final output (conversation + execution results) passes to the next agent

### Security Model

| Layer                  | Protection                                                      |
| ---------------------- | --------------------------------------------------------------- |
| **Global kill switch** | `ENABLE_CODE_AGENT=false` disables all code execution           |
| **Per-agent flag**     | Only agents with `can_code: true` enter the code loop           |
| **Temp working dir**   | Code runs in a disposable temp directory                        |
| **Clean environment**  | No `.env` secrets leaked to subprocesses                        |
| **Timeout**            | Hard kill after `CODE_AGENT_TIMEOUT` seconds                    |
| **Output cap**         | Subprocess output truncated at 10 KB                            |
| **No shell mode**      | Python/Node exec'd directly — no shell metacharacter expansion  |
| **Iteration cap**      | Loop stops after `CODE_AGENT_MAX_ITERATIONS` (prevents runaway) |

### Included Crew: Dev Team

The `dev_team.yaml` crew ships by default with three agents:

- **Architect** — breaks the problem into a detailed implementation plan
- **Coder** (`can_code: true`) — writes and executes code, self-corrects on errors
- **Reviewer** — reviews the code for correctness, security, and style

```
/crew run dev_team write a Python script that finds duplicate files by hash
```

---

## OpenClaw Integration

NanoCrew-Local integrates bidirectionally with [OpenClaw](https://github.com/openclaw/openclaw) (354k+ stars), the personal AI assistant platform.

### What This Enables

| Direction | How It Works |
| --- | --- |
| **OpenClaw → NanoCrew** | OpenClaw routes tasks to NanoCrew crew pipelines via Gateway WebSocket. Your OpenClaw assistant can say "run the dev team on this" and trigger a full 3-agent pipeline. |
| **NanoCrew → OpenClaw** | NanoCrew can push results back into OpenClaw sessions — responses appear in your WhatsApp, Telegram, Slack, Discord, or any other connected channel. |
| **REST API** | Any tool (OpenClaw or not) can trigger crews via `POST /api/crew/run` — a universal HTTP endpoint. |

### Setup

**1. Enable in NanoCrew-Local:**

```ini
# In .env
ENABLE_OPENCLAW=true
OPENCLAW_GATEWAY_URL=ws://127.0.0.1:18789
OPENCLAW_API_TOKEN=your-token-here
OPENCLAW_DEFAULT_CREW=dev_team   # optional — crew for unspecified tasks
```

**2. Install the NanoCrew skill in OpenClaw:**

Copy the `openclaw-skill/` directory to your OpenClaw workspace:

```bash
cp -r openclaw-skill ~/.openclaw/workspace/skills/nanocrew
```

OpenClaw will discover the skill and can use it to run NanoCrew pipelines.

**3. Or use the REST API directly:**

```bash
# Run a crew pipeline
curl -X POST http://127.0.0.1:8585/api/crew/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "dev_team", "instruction": "Write a rate limiter in Python"}'

# List available crews
curl http://127.0.0.1:8585/api/crews

# Check system status
curl http://127.0.0.1:8585/api/status
```

### How the Gateway Connection Works

```
┌──────────────────────┐     WebSocket      ┌──────────────────────┐
│      OpenClaw        │◄──────────────────►│   NanoCrew-Local     │
│    (Gateway at       │   auto-reconnect   │  (OpenClawConnector) │
│  ws://127.0.0.1:     │                    │                      │
│       18789)         │   ──── task ────►  │  → PipelineEngine    │
│                      │   ◄── result ────  │  → Crew agents       │
│  WhatsApp/Telegram/  │                    │  → LLM (any provider)│
│  Slack/Discord/...   │                    │                      │
└──────────────────────┘                    └──────────────────────┘
```

The connector auto-reconnects if the Gateway restarts. Tasks from OpenClaw flow through the same crew pipeline as Telegram commands.

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
├── core_orchestrator.py       # All framework logic
├── dashboard.html             # Single-page local dashboard UI
├── requirements.txt           # 5 dependencies
├── .env.example               # Environment config template
├── LICENSE                    # AGPL-3.0
├── README.md                  # This file
├── openclaw-skill/            # OpenClaw skill package (copy to ~/.openclaw/workspace/skills/)
│   └── SKILL.md               # Skill definition for OpenClaw discovery
└── crews/
    ├── _template.yaml         # Documented template for new crews
    ├── security_ops.yaml      # Example: security operations crew
    ├── startup_team.yaml      # Example: tech startup team
    ├── customer_support.yaml  # Example: customer support pipeline
    ├── content_studio.yaml    # Example: content creation studio
    ├── dev_team.yaml          # Example: coding agent crew (Architect → Coder → Reviewer)
    ├── finance_team.yaml      # Example: finance team
    ├── legal_review.yaml      # Example: legal review crew
    └── health_wellness.yaml   # Example: health & wellness crew
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

[AGPL-3.0](LICENSE) — free to use, modify, and distribute. Network use requires source disclosure. See [LICENSE](LICENSE) for details.

---

<p align="center">
  Any company. Any industry. On the hardware you already own.<br>
  <strong>NanoCrew-Local</strong> — your AI workforce, running locally.
</p>
