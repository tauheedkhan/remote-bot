# Sentinel 🤖

A lean personal AI daemon. Claude Code CLI + Telegram + heartbeat monitoring.

**No API key needed** — uses your Claude Pro/Max subscription.

## How Memory Works

Three layers, each serving a different purpose:

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Claude Code Session (--resume)              │
│ Full conversation history. "What did I ask earlier?" │
│ Resets when context gets too long.                   │
├─────────────────────────────────────────────────────┤
│ Layer 2: CLAUDE.md (auto-read by Claude Code)        │
│ Persistent facts, recent alerts, identity.           │
│ Survives session resets. Auto-updated.               │
├─────────────────────────────────────────────────────┤
│ Layer 3: memory.json (backing store)                 │
│ Session ID, all facts, full alert history.           │
│ Source of truth. Feeds Layer 2.                      │
└─────────────────────────────────────────────────────┘
```

When you chat, Claude Code automatically loads CLAUDE.md (your persistent memory) and resumes your session (conversation history). Even if the session resets due to context limits, CLAUDE.md ensures Claude still knows your facts and recent alerts.

## Architecture

```
     You (Telegram)
          │
          ▼
    ┌───────────┐     ┌─────────────────────────────┐
    │ Sentinel  │────►│ claude -p --resume {sid}     │
    │  Daemon   │     │   --append-system-prompt ... │
    │           │◄────│   --allowedTools Bash,Read.. │
    └─────┬─────┘     │   --output-format json       │
          │           └─────────────────────────────┘
     ┌────┴─────┐           │
     │Heartbeat │      Reads CLAUDE.md automatically
     │  Loop    │      (persistent memory layer)
     └────┬─────┘
          │
   ┌──────┼──────┐
   ▼      ▼      ▼
  URL   Logs   Commands
 Check  Watch   Runner
```

## Quick Start

### 1. Prerequisites

```bash
# Install Claude Code and login with your subscription
# See: https://code.claude.com/docs/en/setup
claude login

# Verify it works
claude -p "hello" --output-format text
```

### 2. Setup

```bash
cd sentinel
pip install -r requirements.txt

cp .env.example .env
# Edit .env: add your Telegram bot token and user ID

export $(cat .env | xargs)
```

### 3. Run

```bash
python sentinel.py
```

Message your bot on Telegram. Claude has full tool access (bash, files, web search) and remembers your conversation across messages.

### 4. Configure monitors (optional)

Edit `config.yaml`:

```yaml
monitors:
  - name: command_runner
    enabled: true
    commands:
      - name: mt5_running
        cmd: "pgrep -c terminal64 || echo 0"
        alert_if: "lt:1"
      - name: disk_usage
        cmd: "df -h / | tail -1 | awk '{print $5}' | sed 's/%//'"
        alert_if: "gt:85"

  - name: url_health
    enabled: true
    urls:
      - "https://your-trading-bot.com/health"
```

## Telegram Commands

| Command | What it does |
|---------|-------------|
| `/start` | Show your user ID + help |
| `/status` | Session + memory info |
| `/alerts` | Alert history |
| `/forget` | Reset session (memory persists) |
| `/remember key=value` | Store a persistent fact |
| *(any text)* | Chat with Claude (full tool access) |

## How It Actually Works

When you send "check disk usage" on Telegram:

1. Sentinel builds: `claude -p --resume {session_id} --output-format json --append-system-prompt "..." --allowedTools "Bash,Read,..." "check disk usage"`
2. Claude Code loads CLAUDE.md (your memory), resumes your session, runs `df -h`, returns the result
3. Sentinel parses the JSON response, extracts session_id for next time, sends result to Telegram

The `--resume` flag is the key — it gives Claude your full conversation history, exactly like working in a Claude Code project interactively.

## Important: Billing

**Do NOT set `ANTHROPIC_API_KEY`**. If it's set, Claude Code ignores your subscription and charges per-token via the API.

```bash
# Check if it's set
echo $ANTHROPIC_API_KEY

# Remove it if set
unset ANTHROPIC_API_KEY
```

Sentinel will warn you on startup if it detects the API key.

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `sentinel.py` | ~80 | Main daemon, lifecycle |
| `agent.py` | ~120 | Claude Code CLI wrapper + session management |
| `bot.py` | ~160 | Telegram bot (in/out) |
| `heartbeat.py` | ~70 | Proactive monitoring loop |
| `monitors.py` | ~100 | URL, log, command monitors |
| `memory.py` | ~100 | JSON store + CLAUDE.md writer |
| **Total** | **~630** | |
