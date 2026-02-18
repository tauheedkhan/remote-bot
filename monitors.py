"""
Pluggable monitors for Sentinel's heartbeat loop.
Each returns a list of alert strings (empty = all clear).
"""

import asyncio
import logging
import subprocess

import aiohttp

logger = logging.getLogger("sentinel.monitors")

# State tracking between checks
_state: dict[str, dict] = {}
_file_positions: dict[str, int] = {}


async def check_url_health(config: dict) -> list[str]:
    alerts = []
    s = _state.setdefault("url_health", {})
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for url in config.get("urls", []):
            try:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        alerts.append(f"🔴 {url} returned HTTP {resp.status}")
                    elif s.get(url) == "down":
                        alerts.append(f"🟢 {url} is back up")
                    s[url] = "up"
            except Exception as e:
                if s.get(url) != "down":
                    alerts.append(f"🔴 {url} unreachable: {str(e)[:100]}")
                s[url] = "down"
    return alerts


async def check_commands(config: dict) -> list[str]:
    alerts = []
    for cmd_cfg in config.get("commands", []):
        name = cmd_cfg["name"]
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd_cfg["cmd"],
                shell=True, capture_output=True, text=True, timeout=30,
            )
            output = result.stdout.strip()
            alert_if = cmd_cfg.get("alert_if", "not_empty")
            should_alert = False

            if alert_if == "not_empty" and output:
                should_alert = True
            elif alert_if.startswith("gt:"):
                try:
                    if float(output) > float(alert_if.split(":")[1]):
                        should_alert = True
                except ValueError:
                    pass
            elif alert_if.startswith("lt:"):
                try:
                    if float(output) < float(alert_if.split(":")[1]):
                        should_alert = True
                except ValueError:
                    pass
            elif alert_if.startswith("contains:"):
                if alert_if.split(":", 1)[1] in output:
                    should_alert = True

            if should_alert:
                alerts.append(f"⚡ {name}: {output[:500]}")
        except subprocess.TimeoutExpired:
            alerts.append(f"⏰ {name}: timed out")
        except Exception as e:
            alerts.append(f"❌ {name}: {e}")
    return alerts


async def check_logs(config: dict) -> list[str]:
    alerts = []
    patterns = config.get("patterns", ["ERROR"])

    for log_path in config.get("paths", []):
        try:
            from pathlib import Path
            p = Path(log_path)
            if not p.exists():
                continue

            size = p.stat().st_size
            last_pos = _file_positions.get(log_path, 0)
            if size < last_pos:
                last_pos = 0  # File rotated
            if size <= last_pos:
                continue

            content = p.read_text()
            new_content = content[last_pos:]
            _file_positions[log_path] = size

            matches = [
                line for line in new_content.splitlines()
                if any(pat in line for pat in patterns)
            ]
            if matches:
                sample = [f"  → {m[:200]}" for m in matches[:5]]
                alert = f"📋 {log_path}: {len(matches)} new error(s)\n" + "\n".join(sample)
                if len(matches) > 5:
                    alert += f"\n  ... and {len(matches) - 5} more"
                alerts.append(alert)
        except Exception:
            pass
    return alerts


# Registry
MONITORS = {
    "url_health": check_url_health,
    "command_runner": check_commands,
    "log_watcher": check_logs,
}


async def run_all(configs: list[dict]) -> list[str]:
    """Run all enabled monitors, return collected alerts."""
    all_alerts = []
    for cfg in configs:
        if not cfg.get("enabled", False):
            continue
        fn = MONITORS.get(cfg["name"])
        if not fn:
            continue
        try:
            alerts = await fn(cfg)
            all_alerts.extend(alerts)
        except Exception as e:
            logger.error(f"Monitor {cfg['name']} failed: {e}")
    return all_alerts
