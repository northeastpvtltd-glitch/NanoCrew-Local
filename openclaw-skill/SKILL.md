# NanoCrew-Local — OpenClaw Skill

## Description
Run NanoCrew-Local crew pipelines from OpenClaw. NanoCrew-Local is a
multi-agent system (MAS) framework that lets you build AI-powered teams
(crews) defined as YAML files. Each crew is a pipeline of specialized
agents that process tasks sequentially.

## When to Use
- You need a **multi-agent pipeline** (3+ specialized agents processing a task in sequence)
- You want to run a **coding agent** that writes, executes, and self-corrects code
- You need work done by a **specialized team** (security ops, legal review, content studio, dev team, etc.)
- You want to leverage **local LLMs** (Ollama) for privacy-sensitive tasks alongside cloud models

## Configuration
NanoCrew-Local must be running on the same machine (or network-accessible).
Default dashboard URL: `http://127.0.0.1:8585`

## Available Crews
Query available crews with:
```bash
curl http://127.0.0.1:8585/api/crews
```

## How to Run a Crew

### Via REST API (recommended)
```bash
curl -X POST http://127.0.0.1:8585/api/crew/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "dev_team", "instruction": "Write a Python script that finds duplicate files by hash"}'
```

### Available Crew Keys
- `security_operations` — Security analysis pipeline (Sentinel → Cipher → Signal)
- `startup_team` — Tech startup advisory (Nova → Atlas → Echo)
- `customer_support` — Customer support pipeline (Iris → Kai → Aria)
- `content_studio` — Content creation (Maven → Quill → Jade)
- `dev_team` — Coding agent crew (Architect → Coder → Reviewer)
- `finance_team` — Financial analysis (Ledger → Abacus → Folio)
- `legal_review` — Legal review pipeline (Clause → Gavel → Brief)
- `health_&_wellness` — Health & wellness advisory (Pulse → Sage → Willow)

### Response Format
The API returns JSON:
```json
{
  "crew": "dev_team",
  "crew_name": "Dev Team",
  "agents_run": 3,
  "results": [
    {"agent": "Architect", "output": "...implementation plan..."},
    {"agent": "Coder", "output": "...code + execution results..."},
    {"agent": "Reviewer", "output": "...code review..."}
  ]
}
```

## Examples

### Run the dev team to write code
```bash
curl -X POST http://127.0.0.1:8585/api/crew/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "dev_team", "instruction": "Write a Python function that validates email addresses using regex, with unit tests"}'
```

### Run security analysis
```bash
curl -X POST http://127.0.0.1:8585/api/crew/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "security_operations", "instruction": "Analyze the security posture of a web application that uses JWT tokens stored in localStorage"}'
```

### Run content creation
```bash
curl -X POST http://127.0.0.1:8585/api/crew/run \
  -H "Content-Type: application/json" \
  -d '{"crew": "content_studio", "instruction": "Write a blog post about the benefits of local AI for small businesses"}'
```

### Check system status
```bash
curl http://127.0.0.1:8585/api/status
```
