#!/usr/bin/env python3
"""
NanoCrew-Local — Core Orchestrator
===================================
A general-purpose multi-agent system (MAS) framework optimized for
constrained local hardware.  Users define "crews" of AI agents via
YAML config files.  The framework routes tasks through the crew
pipeline sequentially, using a time-shared local LLM (Ollama) to
keep memory usage within safe bounds.

Architecture:
    Telegram Bot  ──>  PipelineEngine  ──>  LLMClient  ──>  Ollama
         │                   │
         │            Crew (YAML-defined)
         │            ├─ Agent 1  (gets raw instruction)
         │            ├─ Agent 2  (gets Agent 1 output)
         │            └─ Agent N  (gets Agent N-1 output)
         │
         └── sends final report back to user

Key constraint: asyncio.Lock inside LLMClient guarantees that only
ONE Ollama inference runs at a time — preventing OOM on 16 GB systems.

Usage:
    1. Copy .env.example to .env and fill in your values.
    2. Drop crew YAML files into the crews/ directory.
    3. python core_orchestrator.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import httpx
import psutil
import yaml
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# Configuration
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERNAMES: list[str] = [
    u.strip()
    for u in os.getenv("ALLOWED_USERNAMES", "").split(",")
    if u.strip()
]
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gemma4:4b")
CREWS_DIR: str = os.getenv("CREWS_DIR", "crews")
ENABLE_CODE_EXECUTION: bool = os.getenv("ENABLE_CODE_EXECUTION", "false").lower() in ("true", "1", "yes")
COMMAND_TIMEOUT: int = int(os.getenv("COMMAND_TIMEOUT", "30"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ============================================================
# Poor Man's Configurator — inspired by nanoGPT/configurator.py
# ============================================================
# Override any of the above config globals from the command line:
#   python core_orchestrator.py --OLLAMA_MODEL=llama3:8b --COMMAND_TIMEOUT=60
# Type is preserved: if the original is int, the override is cast to int.

def _apply_cli_overrides() -> None:
    """Parse --key=value args and override matching module globals."""
    from ast import literal_eval
    g = globals()
    for arg in sys.argv[1:]:
        if not arg.startswith("--") or "=" not in arg:
            continue
        key, val = arg.split("=", 1)
        key = key.lstrip("-")
        if key not in g:
            continue
        current = g[key]
        try:
            attempt = literal_eval(val)
        except (SyntaxError, ValueError):
            attempt = val
        # Coerce to the original type when possible.
        if isinstance(current, bool):
            attempt = str(attempt).lower() in ("true", "1", "yes")
        elif isinstance(current, int) and not isinstance(attempt, int):
            attempt = int(attempt)
        elif isinstance(current, float) and not isinstance(attempt, float):
            attempt = float(attempt)
        g[key] = attempt


_apply_cli_overrides()

# ============================================================
# Logging — colored output inspired by nanochat/common.py
# ============================================================

class _ColoredFormatter(logging.Formatter):
    """ANSI-colored log formatter.  Bold level names, highlighted numbers."""
    _COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    _RESET = "\033[0m"
    _BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        if color:
            record.levelname = f"{color}{self._BOLD}{record.levelname}{self._RESET}"
        msg = super().format(record)
        # Highlight numbers with units (e.g. "4.2 GB", "83%", "3 agents")
        if record.levelno == logging.INFO:
            msg = re.sub(
                r'(\d+\.?\d*\s*(?:GB|MB|KB|%|agents?|crews?|commands?|chars?|s)\b)',
                rf'{self._BOLD}\1{self._RESET}',
                msg,
            )
        return msg


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler()
    handler.setFormatter(_ColoredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    root.addHandler(handler)
    return logging.getLogger("nanocrew")


logger = _setup_logging()


# ============================================================
# Startup banner — inspired by nanoGPT / nanochat
# ============================================================

_BANNER = r"""
  _   _                    ____                   
 | \ | | __ _ _ __   ___  / ___|_ __ _____      __
 |  \| |/ _` | '_ \ / _ \| |   | '__/ _ \ \ /\ / /
 | |\  | (_| | | | | (_) | |___| | |  __/\ V  V / 
 |_| \_|\__,_|_| |_|\___/ \____|_|  \___| \_/\_/  
        Your AI workforce, running locally.
"""


def _print_banner() -> None:
    """Print the startup banner (only when stdout is a TTY)."""
    if sys.stdout.isatty():
        print(_BANNER)

# ============================================================
# Hardware-awareness constants
# ============================================================
# Conservative estimates used to warn users before a pipeline run.
# These are rough heuristics, not precise measurements.

MODEL_RAM_ESTIMATE_GB: float = 4.0   # ~4 GB for a quantized 4B model
SYSTEM_OVERHEAD_GB: float = 4.0      # OS + Python process + buffers
CONTEXT_PER_AGENT_GB: float = 0.3    # KV-cache growth per pipeline step

# Telegram message hard limit is 4096 chars; we leave a small margin.
TELEGRAM_MSG_LIMIT: int = 4000

# Maximum bytes of subprocess output before truncation.
COMMAND_OUTPUT_LIMIT: int = 10_240  # 10 KB

# ============================================================
# Command Whitelists (per OS)
# ============================================================
# These are HARDCODED — not user-configurable — to prevent prompt
# injection from escalating to arbitrary command execution.
# Only read-only system inspection commands are allowed.

LINUX_COMMANDS: frozenset[str] = frozenset({
    "netstat", "ss", "ps", "journalctl", "systemctl",
    "hostname", "whoami", "uptime", "free", "df",
    "lsof", "ip", "cat", "grep", "ls", "last",
    "w", "who", "dmesg", "route", "arp", "nslookup", "ping",
})

WINDOWS_COMMANDS: frozenset[str] = frozenset({
    "netstat", "tasklist", "ipconfig", "hostname", "whoami",
    "systeminfo", "wmic", "wevtutil", "findstr", "type",
    "dir", "net", "route", "arp", "nslookup", "ping",
})

# Characters that must never appear in command arguments.
# Prevents shell metacharacter injection.
_DANGEROUS_CHARS = re.compile(r'[;&|$`(){}\<>\n\r]')
_PATH_TRAVERSAL = re.compile(r'(^|[\\/])\.\.([\\/]|$)')


# ============================================================
# Data Classes
# ============================================================

@dataclass
class ExecutionResult:
    """Structured result of a sandboxed command execution."""
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    error: str | None = None
    timeout: bool = False

    @property
    def success(self) -> bool:
        return self.error is None and self.returncode == 0


@dataclass
class AgentProfile:
    """One agent in a crew — loaded from a YAML agent entry."""

    name: str
    role: str
    system_prompt: str
    temperature: float = 0.7
    model: str | None = None       # None → use global OLLAMA_MODEL
    options: dict | None = None    # Raw Ollama generation options passthrough
    can_execute: bool = False      # Whether this agent may run system commands


@dataclass
class Crew:
    """
    A named collection of agents with a defined pipeline order.
    Loaded from a single YAML file in the crews/ directory.
    """

    name: str
    description: str
    agents: list[AgentProfile]
    source_file: str
    recommended_max_ram_gb: float = 16.0

    # ----------------------------------------------------------
    # Factory: parse a YAML file into a Crew instance.
    # ----------------------------------------------------------
    @staticmethod
    def from_yaml(path: str) -> Crew:
        """Read a crew YAML file, validate it, and return a Crew."""
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping, got {type(data).__name__}")

        name = data.get("name")
        if not name:
            raise ValueError("Crew YAML must have a 'name' field")

        agents_raw = data.get("agents")
        if not agents_raw or not isinstance(agents_raw, list):
            raise ValueError("Crew YAML must have an 'agents' list with at least one entry")

        agents: list[AgentProfile] = []
        for idx, entry in enumerate(agents_raw):
            for required_key in ("name", "role", "system_prompt"):
                if required_key not in entry:
                    raise ValueError(
                        f"Agent #{idx + 1} in {Path(path).name} is missing '{required_key}'"
                    )
            agents.append(
                AgentProfile(
                    name=entry["name"],
                    role=entry["role"],
                    system_prompt=entry["system_prompt"].strip(),
                    temperature=float(entry.get("temperature", 0.7)),
                    model=entry.get("model"),
                    options=entry.get("options"),
                    can_execute=bool(entry.get("can_execute", False)),
                )
            )

        return Crew(
            name=name,
            description=data.get("description", ""),
            agents=agents,
            source_file=path,
            recommended_max_ram_gb=float(data.get("recommended_max_ram_gb", 16.0)),
        )


# ============================================================
# LLM Client — time-shared Ollama access
# ============================================================

class LLMClient:
    """
    Async HTTP client for the Ollama REST API.

    The critical feature is the asyncio.Lock inside generate():
    it guarantees that only ONE inference request is in flight at
    any time, across all crews and all concurrent Telegram users.
    This prevents Ollama from being double-loaded on RAM-constrained
    systems.
    """

    def __init__(self, base_url: str, default_model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._lock = asyncio.Lock()
        # Timeouts: 10 s connect, 5 min read (small models on CPU can be slow).
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        model: str | None = None,
        options: dict | None = None,
    ) -> str:
        """
        Send a prompt to Ollama and return the complete response text.

        Acquires the global lock before making the request — any other
        caller that reaches this method concurrently will await until
        the current inference finishes.
        """
        async with self._lock:
            payload: dict = {
                "model": model or self._default_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    **(options or {}),
                },
            }
            if system_prompt:
                payload["system"] = system_prompt

            logger.debug("Ollama request: model=%s, prompt length=%d", payload["model"], len(prompt))

            response = await self._client.post("/api/generate", json=payload)
            response.raise_for_status()

            data = response.json()
            text = data.get("response", "").strip()

            logger.debug("Ollama response: %d chars", len(text))
            return text

    async def health_check(self) -> bool:
        """Return True if Ollama is reachable and responding."""
        try:
            resp = await self._client.get("/api/tags")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    async def close(self) -> None:
        """Shut down the underlying HTTP connection pool."""
        await self._client.aclose()


# ============================================================
# Command Executor — sandboxed system command runner
# ============================================================

class CommandExecutor:
    """
    Sandboxed subprocess runner for agent-generated system commands.

    Security model:
    - Only commands in the OS-specific whitelist may execute.
    - Arguments are sanitized: shell metacharacters and path traversal blocked.
    - No shell=True — commands are exec'd directly (no metachar expansion).
    - Subprocess inherits a clean environment (no .env secrets leaked).
    - Working directory is a disposable temp dir.
    - Hard timeout prevents hangs; output is capped to prevent OOM.
    - Every execution attempt is logged for auditability.
    """

    # Regex to extract fenced code blocks from LLM output.
    _CODE_BLOCK_RE = re.compile(
        r'```(?:bash|shell|sh|cmd|powershell)?\s*\n(.*?)```',
        re.DOTALL,
    )

    def __init__(self, timeout: int = 30, output_limit: int = COMMAND_OUTPUT_LIMIT) -> None:
        self._timeout = timeout
        self._output_limit = output_limit
        # Select the whitelist for the current OS.
        self._allowed = (
            WINDOWS_COMMANDS if platform.system() == "Windows" else LINUX_COMMANDS
        )
        # Minimal clean environment for subprocesses.
        self._clean_env = self._build_clean_env()
        logger.info(
            "CommandExecutor initialized: OS=%s, %d whitelisted commands, timeout=%ds",
            platform.system(), len(self._allowed), self._timeout,
        )

    @staticmethod
    def _build_clean_env() -> dict[str, str]:
        """Build a minimal environment dict safe for subprocesses."""
        safe_keys = {"PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "HOME", "USER", "LANG"}
        return {k: v for k, v in os.environ.items() if k in safe_keys}

    def extract_commands(self, llm_output: str) -> list[list[str]]:
        """
        Parse fenced code blocks from LLM output and return a list
        of tokenized commands.  Each command is a list of strings
        suitable for asyncio.create_subprocess_exec().

        Lines starting with # are treated as comments and skipped.
        Empty lines are skipped.
        """
        blocks = self._CODE_BLOCK_RE.findall(llm_output)
        commands: list[list[str]] = []

        for block in blocks:
            for line in block.strip().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Split on whitespace — simple tokenization (no shell expansion).
                tokens = line.split()
                if tokens:
                    commands.append(tokens)

        return commands

    def validate_command(self, tokens: list[str]) -> str | None:
        """
        Validate a tokenized command against the whitelist and
        argument sanitization rules.

        Returns None if the command is safe, or an error string
        describing why it was rejected.
        """
        if not tokens:
            return "Empty command"

        cmd = tokens[0].lower()

        # Strip path prefix so "/usr/bin/netstat" matches "netstat".
        cmd_base = Path(cmd).name.lower()
        # On Windows, strip .exe suffix.
        if cmd_base.endswith(".exe"):
            cmd_base = cmd_base[:-4]

        if cmd_base not in self._allowed:
            return f"Command '{cmd_base}' is not in the whitelist"

        # Validate every argument.
        for arg in tokens[1:]:
            if _DANGEROUS_CHARS.search(arg):
                return f"Argument contains dangerous characters: '{arg}'"
            if _PATH_TRAVERSAL.search(arg):
                return f"Argument contains path traversal: '{arg}'"

        return None  # Safe.

    async def execute(self, tokens: list[str]) -> ExecutionResult:
        """
        Execute a single validated command in a sandboxed subprocess.
        Returns an ExecutionResult with structured fields.
        """
        cmd_str = " ".join(tokens)

        # Pre-validate.
        rejection = self.validate_command(tokens)
        if rejection:
            logger.warning("Command BLOCKED: %s — %s", cmd_str, rejection)
            return ExecutionResult(command=cmd_str, error=f"Blocked: {rejection}")

        logger.info("Executing command: %s", cmd_str)

        try:
            # Use a temp dir as the working directory — prevents file writes
            # to the project tree and limits blast radius.
            with tempfile.TemporaryDirectory() as tmp_dir:
                proc = await asyncio.create_subprocess_exec(
                    *tokens,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmp_dir,
                    env=self._clean_env,
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=self._timeout,
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    logger.warning("Command timed out after %ds: %s", self._timeout, cmd_str)
                    return ExecutionResult(
                        command=cmd_str,
                        error=f"Timed out after {self._timeout}s",
                        timeout=True,
                    )

            # Cap output size.
            stdout = stdout_bytes.decode("utf-8", errors="replace")[:self._output_limit]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:self._output_limit]

            if len(stdout_bytes) > self._output_limit:
                stdout += "\n... (output truncated)"
            if len(stderr_bytes) > self._output_limit:
                stderr += "\n... (output truncated)"

            logger.info(
                "Command finished: %s — rc=%d, stdout=%d chars, stderr=%d chars",
                cmd_str, proc.returncode, len(stdout), len(stderr),
            )

            return ExecutionResult(
                command=cmd_str,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
            )

        except FileNotFoundError:
            logger.warning("Command not found on system: %s", tokens[0])
            return ExecutionResult(command=cmd_str, error=f"Command not found: {tokens[0]}")
        except Exception as exc:
            logger.exception("Unexpected error executing: %s", cmd_str)
            return ExecutionResult(command=cmd_str, error=str(exc))

    async def run_from_llm_output(self, llm_output: str) -> str:
        """
        Extract commands from LLM output, validate and execute each one
        sequentially, and return a formatted report of all results.

        Uses structured delimiters so downstream agents can reliably
        parse where system output starts and ends — inspired by
        nanochat's <|output_start|>/<|output_end|> pattern.
        """
        commands = self.extract_commands(llm_output)

        if not commands:
            return "(No executable commands found in agent output)"

        results: list[str] = []

        for tokens in commands:
            result = await self.execute(tokens)

            parts = [f"$ {result.command}"]
            if result.error:
                parts.append(f"ERROR: {result.error}")
            else:
                if result.stdout:
                    parts.append(result.stdout)
                if result.stderr:
                    parts.append(f"STDERR: {result.stderr}")
                parts.append(f"(exit code: {result.returncode})")

            results.append("\n".join(parts))

        return "\n\n".join(results)


# ============================================================
# Pipeline Engine — sequential agent execution
# ============================================================

class PipelineEngine:
    """
    Runs a crew's agent pipeline strictly sequentially.

    Each agent receives either the raw user instruction (first agent)
    or the previous agent's output (all subsequent agents).  The
    LLMClient's internal lock ensures only one inference at a time.

    When an agent has can_execute=True AND code execution is globally
    enabled, the engine extracts system commands from the LLM output,
    runs them in a sandbox, and appends real system data to the agent's
    result before passing it to the next agent in the chain.

    Optional callbacks let the caller (e.g., the Telegram bot) send
    real-time progress updates to the user.
    """

    def __init__(self, llm: LLMClient, executor: CommandExecutor | None = None) -> None:
        self._llm = llm
        self._executor = executor

    async def run(
        self,
        crew: Crew,
        instruction: str,
        on_agent_start: Callable | None = None,
        on_agent_done: Callable | None = None,
    ) -> list[dict]:
        """
        Execute every agent in the crew, in order.

        Returns a list of step results:
            [{"agent": "Agent Name", "output": "response text"}, ...]

        Callbacks (all optional, all async):
            on_agent_start(name, step_number, total_agents)
            on_agent_done(name, output, step_number, total_agents)
        """
        steps: list[dict] = []
        current_input = instruction
        total = len(crew.agents)

        for i, agent in enumerate(crew.agents):
            step = i + 1

            # --- Notify: agent starting ---
            if on_agent_start:
                await on_agent_start(agent.name, step, total)

            # Build the prompt.  The first agent sees the raw instruction;
            # subsequent agents see the previous agent's output with framing.
            if i == 0:
                prompt = current_input
            else:
                prev = crew.agents[i - 1]
                prompt = (
                    f"Previous analysis from {prev.name}:\n"
                    f"---\n{current_input}\n---\n\n"
                    f"Based on the above, perform your analysis."
                )

            # Call the LLM (lock-protected inside LLMClient).
            output = await self._llm.generate(
                prompt=prompt,
                system_prompt=agent.system_prompt,
                temperature=agent.temperature,
                model=agent.model,
                options=agent.options,
            )

            # If this agent can execute commands and execution is enabled,
            # parse the LLM output for fenced code blocks, run them in the
            # sandbox, and append real system data to the output.
            if agent.can_execute and self._executor:
                exec_report = await self._executor.run_from_llm_output(output)
                if exec_report:
                    output = (
                        f"{output}\n\n"
                        f"<|system_output_start|>\n"
                        f"{exec_report}\n"
                        f"<|system_output_end|>"
                    )

            steps.append({"agent": agent.name, "output": output})
            current_input = output  # Chain to the next agent.

            # --- Notify: agent done ---
            if on_agent_done:
                await on_agent_done(agent.name, output, step, total)

        return steps


# ============================================================
# Crew Registry — auto-discovery from YAML files
# ============================================================

def load_crews(crews_dir: str) -> dict[str, Crew]:
    """
    Scan the crews/ directory for YAML files and parse each one
    into a Crew object.  Returns a dict mapping slug keys
    (e.g., "security_operations") to Crew instances.

    Files whose names start with _ are skipped (reserved for
    templates and documentation).
    """
    registry: dict[str, Crew] = {}
    crews_path = Path(crews_dir)

    if not crews_path.exists():
        logger.warning("Crews directory not found: %s", crews_dir)
        return registry

    for yaml_file in sorted(crews_path.glob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            crew = Crew.from_yaml(str(yaml_file))
            # Slug: lowercase, spaces to underscores.
            key = crew.name.lower().replace(" ", "_")
            registry[key] = crew
            logger.info(
                "Loaded crew '%s' (%d agents) from %s",
                crew.name,
                len(crew.agents),
                yaml_file.name,
            )
        except Exception as exc:
            logger.error("Failed to load %s: %s", yaml_file.name, exc)

    return registry


# ============================================================
# Hardware Awareness
# ============================================================

def check_hardware(crew: Crew) -> str | None:
    """
    Estimate whether available RAM is sufficient for the given crew.
    Returns a warning string, or None if things look OK.
    """
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    available_gb = mem.available / (1024 ** 3)

    estimated_need = (
        MODEL_RAM_ESTIMATE_GB
        + SYSTEM_OVERHEAD_GB
        + len(crew.agents) * CONTEXT_PER_AGENT_GB
    )

    warnings: list[str] = []

    if total_gb < crew.recommended_max_ram_gb and len(crew.agents) > 3:
        warnings.append(
            f"This crew has {len(crew.agents)} agents but your system has "
            f"{total_gb:.1f} GB RAM (crew recommends {crew.recommended_max_ram_gb:.0f} GB). "
            f"Consider reducing agents or upgrading hardware."
        )

    if available_gb < estimated_need:
        warnings.append(
            f"Low available RAM: {available_gb:.1f} GB free, "
            f"estimated {estimated_need:.1f} GB needed. "
            f"Close other applications or reduce agents."
        )

    return " | ".join(warnings) if warnings else None


def log_hardware_report(crew_registry: dict[str, Crew]) -> None:
    """Log system hardware info and loaded crew summary at startup."""
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    available_gb = mem.available / (1024 ** 3)

    logger.info(
        "System RAM: %.1f GB total, %.1f GB available (%s%% used)",
        total_gb,
        available_gb,
        mem.percent,
    )

    total_agents = sum(len(c.agents) for c in crew_registry.values())
    logger.info(
        "Loaded %d crew(s) with %d total agent definitions",
        len(crew_registry),
        total_agents,
    )

    if total_gb < 8:
        logger.warning(
            "Less than 8 GB total RAM detected. Performance may be poor. "
            "Consider using a smaller model or fewer agents."
        )


# ============================================================
# Authorization Helper
# ============================================================

def is_authorized(username: str | None) -> bool:
    """
    Check whether a Telegram username is on the whitelist.
    Fail-closed: if no usernames are configured, deny everyone.
    """
    if not ALLOWED_USERNAMES:
        return False
    return username in ALLOWED_USERNAMES


# ============================================================
# Telegram Command Handlers
# ============================================================
# These are wired up in main().  They share the module-level
# llm, engine, and crew_registry objects.

llm: LLMClient
engine: PipelineEngine
executor: CommandExecutor | None
crew_registry: dict[str, Crew]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message and list available crews."""
    if not is_authorized(update.effective_user.username):
        await update.message.reply_text("Access denied.")
        logger.warning("Unauthorized /start from @%s", update.effective_user.username)
        return

    crew_lines = []
    for key, crew in crew_registry.items():
        crew_lines.append(f"  {key} — {crew.name} ({len(crew.agents)} agents)")

    text = (
        "NanoCrew-Local is active.\n\n"
        "Commands:\n"
        "  /scan <instruction>  — Run the default crew\n"
        "  /crew list           — List all crews\n"
        "  /crew info <name>    — Show crew details\n"
        "  /crew run <name> <instruction> — Run a specific crew\n"
        "  /status              — System health check\n"
        "  /help                — This message\n"
    )
    if crew_lines:
        text += "\nAvailable crews:\n" + "\n".join(crew_lines)
    else:
        text += "\nNo crews loaded. Add YAML files to the crews/ directory."

    await update.message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — alias for /start."""
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status — Ollama health, lock state, RAM, loaded crews."""
    if not is_authorized(update.effective_user.username):
        await update.message.reply_text("Access denied.")
        return

    ollama_ok = await llm.health_check()
    lock_status = "busy (inference running)" if llm._lock.locked() else "idle"

    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    available_gb = mem.available / (1024 ** 3)

    lines = [
        "=== NanoCrew-Local Status ===",
        f"Ollama: {'ONLINE' if ollama_ok else 'OFFLINE'}",
        f"Model: {OLLAMA_MODEL}",
        f"LLM Lock: {lock_status}",
        f"Code execution: {'ENABLED' if ENABLE_CODE_EXECUTION else 'DISABLED'}",
        f"RAM: {available_gb:.1f} / {total_gb:.1f} GB available",
        f"RAM usage: {mem.percent}%",
        f"CPU: {psutil.cpu_percent(interval=0.5)}%",
        f"Crews loaded: {len(crew_registry)}",
    ]
    for key, crew in crew_registry.items():
        lines.append(f"  {key}: {crew.name} ({len(crew.agents)} agents)")

    await update.message.reply_text("\n".join(lines))


async def _run_crew_pipeline(
    update: Update, crew: Crew, instruction: str
) -> None:
    """
    Shared execution path for /scan and /crew run.
    Sends per-agent progress updates to the Telegram chat.
    """
    # Hardware pre-check.
    warning = check_hardware(crew)
    if warning:
        await update.message.reply_text(f"Warning: {warning}")

    # Send an initial status message that we'll edit as progress happens.
    status_msg = await update.message.reply_text(
        f"Starting '{crew.name}' pipeline ({len(crew.agents)} agents)..."
    )

    # -- Callbacks for live progress updates --

    async def on_agent_start(name: str, step: int, total: int) -> None:
        try:
            await status_msg.edit_text(f"[{step}/{total}] Running: {name}...")
        except Exception:
            pass  # Edit can fail if message hasn't changed; ignore.

    async def on_agent_done(name: str, output: str, step: int, total: int) -> None:
        label = f"[{step}/{total}] {name}"
        text = f"{label}:\n\n{output}"
        if len(text) > TELEGRAM_MSG_LIMIT:
            text = text[:TELEGRAM_MSG_LIMIT] + "\n\n... (truncated)"
        try:
            await update.message.reply_text(text)
        except Exception as exc:
            logger.warning("Failed to send agent output: %s", exc)

    # -- Run the pipeline --
    try:
        steps = await engine.run(
            crew, instruction,
            on_agent_start=on_agent_start,
            on_agent_done=on_agent_done,
        )
        await status_msg.edit_text(
            f"Pipeline '{crew.name}' complete. "
            f"{len(steps)} agent(s) processed."
        )
    except httpx.HTTPStatusError as exc:
        await status_msg.edit_text(
            f"LLM error: Ollama returned HTTP {exc.response.status_code}. "
            f"Is the model '{OLLAMA_MODEL}' pulled?"
        )
        logger.exception("Ollama HTTP error during pipeline")
    except httpx.RequestError as exc:
        await status_msg.edit_text(
            f"LLM connection error: {exc}. Is Ollama running at {OLLAMA_BASE_URL}?"
        )
        logger.exception("Ollama connection error during pipeline")
    except Exception as exc:
        await status_msg.edit_text(f"Pipeline error: {exc}")
        logger.exception("Unexpected pipeline error")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan — run the default crew on the user's instruction."""
    if not is_authorized(update.effective_user.username):
        await update.message.reply_text("Access denied.")
        return

    instruction = " ".join(context.args) if context.args else ""
    if not instruction:
        await update.message.reply_text(
            "Usage: /scan <instruction>\n"
            "Example: /scan check for unusual network connections"
        )
        return

    # Use the first loaded crew as the default.
    if not crew_registry:
        await update.message.reply_text(
            "No crews loaded. Add YAML files to the crews/ directory."
        )
        return

    default_crew = next(iter(crew_registry.values()))
    logger.info(
        "Scan by @%s using crew '%s': %s",
        update.effective_user.username,
        default_crew.name,
        instruction,
    )
    await _run_crew_pipeline(update, default_crew, instruction)


async def cmd_crew(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /crew — subcommands for managing and running crews.

    Subcommands:
        /crew list              — show all loaded crews
        /crew info <name>       — show crew details and agent roster
        /crew run <name> <text> — run a specific crew pipeline
    """
    if not is_authorized(update.effective_user.username):
        await update.message.reply_text("Access denied.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "  /crew list\n"
            "  /crew info <crew_name>\n"
            "  /crew run <crew_name> <instruction>"
        )
        return

    subcommand = args[0].lower()

    # --- /crew list ---
    if subcommand == "list":
        if not crew_registry:
            await update.message.reply_text("No crews loaded.")
            return
        lines = ["Available crews:\n"]
        for key, crew in crew_registry.items():
            lines.append(
                f"  {key}\n"
                f"    {crew.name} — {crew.description}\n"
                f"    Agents: {len(crew.agents)}"
            )
        await update.message.reply_text("\n".join(lines))
        return

    # --- /crew info <name> ---
    if subcommand == "info":
        if len(args) < 2:
            await update.message.reply_text("Usage: /crew info <crew_name>")
            return
        crew_key = args[1].lower()
        crew = crew_registry.get(crew_key)
        if not crew:
            available = ", ".join(crew_registry.keys()) or "(none)"
            await update.message.reply_text(
                f"Unknown crew: {crew_key}\nAvailable: {available}"
            )
            return
        info_lines = [
            f"Crew: {crew.name}",
            f"Description: {crew.description}",
            f"Recommended RAM: {crew.recommended_max_ram_gb:.0f} GB",
            f"Source: {Path(crew.source_file).name}",
            f"\nAgents ({len(crew.agents)}):",
        ]
        for i, agent in enumerate(crew.agents, 1):
            info_lines.append(f"  {i}. {agent.name}")
            info_lines.append(f"     Role: {agent.role}")
            info_lines.append(f"     Temp: {agent.temperature}")
            if agent.model:
                info_lines.append(f"     Model: {agent.model}")
        await update.message.reply_text("\n".join(info_lines))
        return

    # --- /crew run <name> <instruction> ---
    if subcommand == "run":
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: /crew run <crew_name> <instruction>"
            )
            return
        crew_key = args[1].lower()
        crew = crew_registry.get(crew_key)
        if not crew:
            available = ", ".join(crew_registry.keys()) or "(none)"
            await update.message.reply_text(
                f"Unknown crew: {crew_key}\nAvailable: {available}"
            )
            return
        instruction = " ".join(args[2:])
        logger.info(
            "Crew run by @%s — crew '%s': %s",
            update.effective_user.username,
            crew.name,
            instruction,
        )
        await _run_crew_pipeline(update, crew, instruction)
        return

    # --- Unknown subcommand ---
    await update.message.reply_text(
        f"Unknown subcommand: {subcommand}\n"
        "Use: /crew list | /crew info <name> | /crew run <name> <instruction>"
    )


# ============================================================
# Entry Point
# ============================================================

def main() -> None:
    """
    Initialize all components and start the Telegram bot.

    Startup sequence:
        1. Validate essential config (token, usernames).
        2. Initialize the LLM client (Ollama connection).
        3. Load crew definitions from YAML files.
        4. Log a hardware report.
        5. Build the Telegram Application and start polling.
    """
    global llm, engine, executor, crew_registry

    _print_banner()

    # Log any CLI overrides that were applied.
    for arg in sys.argv[1:]:
        if arg.startswith("--") and "=" in arg:
            logger.info("CLI override: %s", arg)

    # --- Validate config ---
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")
        sys.exit(1)

    if not ALLOWED_USERNAMES:
        logger.error(
            "ALLOWED_USERNAMES is not set. The bot will deny all access. "
            "Add at least one Telegram username to your .env file."
        )
        sys.exit(1)

    logger.info("Authorized users: %s", ", ".join(ALLOWED_USERNAMES))

    # --- Initialize core components ---
    llm = LLMClient(base_url=OLLAMA_BASE_URL, default_model=OLLAMA_MODEL)

    # Code execution is opt-in — only create the executor when enabled.
    if ENABLE_CODE_EXECUTION:
        executor = CommandExecutor(timeout=COMMAND_TIMEOUT)
        logger.info("Code execution ENABLED (timeout=%ds)", COMMAND_TIMEOUT)
    else:
        executor = None
        logger.info("Code execution DISABLED (set ENABLE_CODE_EXECUTION=true to enable)")

    engine = PipelineEngine(llm, executor=executor)

    # --- Load crews ---
    crew_registry = load_crews(CREWS_DIR)
    if not crew_registry:
        logger.warning(
            "No crews loaded from '%s'. The bot will start but /scan "
            "will not work until you add crew YAML files.",
            CREWS_DIR,
        )

    # --- Hardware report ---
    log_hardware_report(crew_registry)

    # --- Build and start the Telegram bot ---
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("crew", cmd_crew))

    logger.info(
        "NanoCrew-Local starting. %d crew(s) loaded. Polling for Telegram updates...",
        len(crew_registry),
    )

    # drop_pending_updates=True: ignore commands that queued while
    # the bot was offline — prevents stale or attacker-queued commands.
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
