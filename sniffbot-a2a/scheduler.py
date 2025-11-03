# scheduler.py
import os
import json
import random
import logging
from uuid import uuid4
from datetime import datetime
from typing import List, Dict, Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Scheduler instance
# ----------------------------------------------------------------------
scheduler = AsyncIOScheduler()

# ----------------------------------------------------------------------
# Load smells once at import time
# ----------------------------------------------------------------------
SMELLS_FILE = "examples/smell_of_the_week.json"

try:
    with open(SMELLS_FILE, "r", encoding="utf-8") as f:
        SMELLS: List[Dict[str, Any]] = json.load(f)
    logger.info(f"Loaded {len(SMELLS)} code smells from {SMELLS_FILE}")
except Exception as e:
    logger.error(f"Failed to load {SMELLS_FILE}: {e}")
    SMELLS = []


# ----------------------------------------------------------------------
# [CHANGED] Emoji mapping per tag
# ----------------------------------------------------------------------
TAG_EMOJI = {
    "security": "lock",
    "performance": "rocket",
    "readability": "bulb",
    "maintainability": "wrench",
    "correctness": "magnifying_glass_tilted_left",
    "style": "paintbrush",
    "portability": "earth_africa",
    "reliability": "shield",
    "modern-js": "recycle",
    "general": "question"
}


# ----------------------------------------------------------------------
# [CHANGED] Build markdown message with emoji + tag
# ----------------------------------------------------------------------
def build_smell_message(smell: Dict[str, Any]) -> str:
    """
    Returns a fully-formatted markdown string with:
      - Title + language
      - Emoji + #tag (if not general)
      - Bad / Good code blocks
      - Explanation
      - Commit message
    """
    title = smell["title"]
    lang = smell["lang"]
    tag = smell.get("tag", "general")
    emoji = TAG_EMOJI.get(tag, "question")
    tag_display = f"{emoji} **#{tag}**" if tag != "general" else ""

    return f"""
**Smell of the Week**  
**{title}** (`{lang}`) {tag_display}

**Bad**
```{lang}
{smell['bad'].rstrip()}
```

**Good**
```{lang}
{smell['good'].rstrip()}
```

> {smell['explanation']}

**Commit Message**  
`{smell['commit_message']}`
""".strip()


# ----------------------------------------------------------------------
# [UNCHANGED] Post smell to Telex (or any A2A webhook)
# ----------------------------------------------------------------------
async def post_smell_of_the_week():
    """
    Selects a random smell and posts it via the configured webhook.
    """
    if not SMELLS:
        logger.warning("No smells loaded – skipping post")
        return

    webhook_url = os.getenv("TELEX_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("TELEX_WEBHOOK_URL not set – cannot post smell")
        return

    smell = random.choice(SMELLS)
    message_text = build_smell_message(smell)
    CONTEXT_ID = "weekly-smell-context"  # ← Persistent
    TASK_ID = f"smell-{uuid4()}"

    payload = {
        "jsonrpc": "2.0",
        "id": f"smell-{datetime.utcnow().isoformat()}",
        "method": "execute",
        "params": {
            "contextId": CONTEXT_ID,
            "taskId": TASK_ID,
            "message": {
                "role": "agent",
                "parts": [
                    {
                        "kind": "text",
                        "text": message_text
                    }
                ]
            },
            "configuration": {
                "blocking": False
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 200:
                logger.info(f"Smell of the Week posted: {smell['title']} {TAG_EMOJI.get(smell.get('tag'), '')}")
            else:
                logger.error(f"Webhook failed {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Failed to post smell: {e}", exc_info=True)


# ----------------------------------------------------------------------
# [UNCHANGED] Schedule the job – every Friday at 10:00 AM UTC
# ----------------------------------------------------------------------
def start_scheduler():
    """
    Call this from main.py lifespan.
    """
    if not scheduler.running:
        scheduler.add_job(
            post_smell_of_the_week,
            trigger="cron",
            day_of_week="fri",
            hour=10,
            minute=0,
            timezone="UTC",
            id="smell_of_the_week",
            replace_existing=True
        )
        scheduler.start()
        logger.info("Scheduler started – Smell of the Week set for Fridays 10:00 UTC")


def stop_scheduler():
    """
    Graceful shutdown.
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
