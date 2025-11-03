# agent.py
import httpx
import json
import asyncio
import random
import logging
from uuid import uuid4
from typing import List, Optional
from datetime import datetime

from models.a2a import (
    A2AMessage, TaskResult, TaskStatus, Artifact,
    MessagePart, MessageConfiguration
)
from utils.code_extractor import extract_code
from utils.diff import create_diff

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Changed from INFO to DEBUG
logger = logging.getLogger(__name__)

# In-memory store: contextId → list of messages
_CONVERSATION_MEMORY: dict[str, list[A2AMessage]] = {}


class SniffBot:
    def __init__(self):
        self.groq_api_key: Optional[str] = None
        self.model = "llama-3.1-8b-instant"  # Updated to a supported model

    async def initialize(self, api_key: str):
        """Called at startup via lifespan"""
        self.groq_api_key = api_key
        logger.info("SniffBot initialized with Groq API")

    async def _analyze_with_groq(self, code: str, lang: str) -> dict:
        """Call Groq API with full error handling"""
        if not self.groq_api_key:
            return self._fallback_result("Bot not configured", code)

        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }

        prompt = f"""
You are a senior code reviewer. Analyze this {lang or 'code'}:

```
{code}
```

Respond **only** in valid JSON:
{{
  "severity": "Low|Medium|High",
  "explanation": "1 short sentence",
  "fixed_code": "corrected code",
  "commit_message": "Conventional Commit style"
}}
"""

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": self.model,
            "temperature": 0.3,
            "max_tokens": 1024
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers=headers
                )
                logger.debug(f"Groq API response: status={resp.status_code}, body={resp.text}")

                if resp.status_code == 429:
                    return self._fallback_result("AI rate limit reached — try again soon", code)
                if resp.status_code != 200:
                    logger.warning(f"Groq error {resp.status_code}: {resp.text}")
                    return self._fallback_result(f"AI service error ({resp.status_code})", code)

                content = resp.json()["choices"][0]["message"]["content"].strip()
                json_str = self._extract_json(content)
                return json.loads(json_str)

        except httpx.TimeoutException:
            return self._fallback_result("AI timed out — try shorter code", code)
        except json.JSONDecodeError:
            return self._fallback_result("AI returned invalid JSON", code)
        except Exception as e:
            logger.error(f"Unexpected AI error: {e}")
            return self._fallback_result("AI analysis failed", code)

    async def _analyze_with_retry(self, code: str, lang: str, max_retries: int = 3) -> dict:
        """
        Retry Groq API with exponential backoff.
        """
        for attempt in range(max_retries):
            analysis = await self._analyze_with_groq(code, lang)
            
            if analysis["severity"] != "Medium" or "rate limit" not in analysis["explanation"].lower():
                return analysis  # Success or non-retryable error
            
            wait_time = (2 ** attempt) + random.uniform(0, 1)  # 1s, 2s, 4s
            logger.warning(f"Retry {attempt + 1}/{max_retries} in {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
        
        return self._fallback_result("Max retries exceeded", code)

    def _extract_json(self, text: str) -> str:
        """Extract JSON from ```json ... ``` or raw"""
        if "```json" in text:
            return text.split("```json", 1)[1].split("```", 1)[0].strip()
        if "```" in text:
            return text.split("```", 1)[1].split("```", 1)[0].strip()
        return text.strip()

    def _fallback_result(self, explanation: str, original_code: str) -> dict:
        diff = create_diff(original_code, original_code)  # No changes in fallback
        logger.debug(f"Fallback diff: '{diff}'")
        return {
            "severity": "Medium",
            "explanation": explanation,
            "fixed_code": original_code,
            "commit_message": "chore: retry analysis",
            "diff": diff  # Add diff field
        }

    async def process_messages(
        self,
        messages: List[A2AMessage],
        context_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> TaskResult:
        """
        Main entry point — matches chess_agent.py structure
        """
        logger.debug(f"Processing messages: {messages}")
        context_id = context_id or str(uuid4())

        # === LOAD MEMORY ===
        if not messages:
            messages = _CONVERSATION_MEMORY.get(context_id, [])
        else:
            _CONVERSATION_MEMORY[context_id] = messages.copy()
        logger.debug(f"Loaded memory for context_id={context_id}, messages={len(messages)}")

        task_id = task_id or str(uuid4())

        if not messages:
            logger.debug("No messages provided")
            return self._build_error_result("No message provided", task_id, context_id, messages)
        
        # Process the latest message
        user_message = messages[-1]
        full_text = " ".join(p.text or "" for p in user_message.parts if p.kind == "text")
        logger.debug(f"Processing message: '{full_text}'")
        lower_text = full_text.lower().strip()

        # Extract code from the message once
        code, lang = extract_code(full_text)
        logger.debug(f"Extracted code: '{code}', language: '{lang}'")

        # === 1. GREETING ===
        if self._is_greeting(lower_text):
            logger.debug("Detected greeting")
            return self._build_greeting_result(task_id, context_id, messages)

        # === 2. HELP COMMAND ===
        if self._is_help_command(lower_text):
            logger.debug("Detected help command")
            return self._build_help_result(task_id, context_id, messages)

        # === 3. CODE REVIEW TRIGGER ===
        trigger = "@sniffbot sniff this" in lower_text
        if trigger and code.strip():
            logger.debug("Code review triggered")
            analysis = await self._analyze_with_retry(code, lang)
            diff = create_diff(code, analysis.get("fixed_code", code))
            logger.debug(f"Generated diff: '{diff}'")
            severity_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(analysis["severity"], "🔵")
            response_text = f"""
**SniffBot Code Review** {severity_emoji} **{analysis['severity']}**

> {analysis['explanation']}

**Fixed Code (Diff)**
```diff
{diff}
```

**Commit Message**  
`{analysis['commit_message']}`
""".strip()

            agent_msg = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=response_text)],
                taskId=task_id,
                contextId=context_id
            )
            artifacts = [
                Artifact(
                    name="review",
                    parts=[MessagePart(kind="text", text=f"Severity: {analysis['severity']}\nExplanation: {analysis['explanation']}")]
                ),
                Artifact(
                    name="diff",
                    parts=[MessagePart(kind="text", text=diff)]
                ),
                Artifact(
                    name="commit",
                    parts=[MessagePart(kind="text", text=analysis['commit_message'])]
                )
            ]
            logger.debug(f"Creating artifacts: {[a.model_dump() for a in artifacts]}")
            _CONVERSATION_MEMORY[context_id] = messages + [agent_msg]
            logger.debug(f"Saved memory for context_id={context_id}, messages={len(_CONVERSATION_MEMORY[context_id])}")
            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(state="completed", message=agent_msg),
                artifacts=artifacts,
                history=messages + [agent_msg],
                kind="task"
            )

        # === 4. FIX LAST CODE TRIGGER ===
        if "@sniffbot fix last" in lower_text:
            logger.debug("Detected fix last command")
            if len(messages) < 2:
                logger.debug("No previous code to fix")
                return self._build_fallback_result(
                    "No previous code to fix! Send some code first.",
                    task_id, context_id, messages
                )
            
            last_user_msg = None
            for msg in reversed(messages[:-1]):
                if msg.role == "user":
                    user_text = " ".join(p.text or "" for p in msg.parts if p.kind == "text")
                    code_check, _ = extract_code(user_text)
                    if code_check.strip():
                        last_user_msg = msg
                        break
            
            if not last_user_msg:
                logger.debug("No previous code message found")
                return self._build_fallback_result(
                    "I couldn't find any previous code to fix.",
                    task_id, context_id, messages
                )
            
            user_text = " ".join(p.text or "" for p in last_user_msg.parts if p.kind == "text")
            code, lang = extract_code(user_text)
            logger.debug(f"Fix last: Extracted code: '{code}', lang='{lang}'")
            if not code.strip():
                logger.debug("No code in last message")
                return self._build_fallback_result(
                    "No code found in the last message.",
                    task_id, context_id, messages
                )

            logger.debug(f"Fix last: Re-analyzing code: '{code}', lang='{lang}'")
            analysis = await self._analyze_with_retry(code, lang)
            diff = create_diff(code, analysis.get("fixed_code", code))
            logger.debug(f"Fix last: Generated diff: '{diff}'")
            severity_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(analysis["severity"], "🔵")
            response_text = f"""
**SniffBot Code Re-Review (Fix Last)** {severity_emoji} **{analysis['severity']}**

> {analysis['explanation']}

**Fixed Code (Diff)**
```diff
{diff}
```

**Commit Message**  
`{analysis['commit_message']}`
""".strip()

            agent_msg = A2AMessage(
                role="agent",
                parts=[MessagePart(kind="text", text=response_text)],
                taskId=task_id,
                contextId=context_id
            )
            artifacts = [
                Artifact(
                    name="review",
                    parts=[MessagePart(kind="text", text=f"Severity: {analysis['severity']}\nExplanation: {analysis['explanation']}")]
                ),
                Artifact(
                    name="diff",
                    parts=[MessagePart(kind="text", text=diff)]
                ),
                Artifact(
                    name="commit",
                    parts=[MessagePart(kind="text", text=analysis['commit_message'])]
                )
            ]
            logger.debug(f"Fix last: Creating artifacts: {[a.model_dump() for a in artifacts]}")
            _CONVERSATION_MEMORY[context_id] = messages + [agent_msg]
            logger.debug(f"Fix last: Saved memory for context_id={context_id}, messages={len(_CONVERSATION_MEMORY[context_id])}")
            return TaskResult(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(state="completed", message=agent_msg),
                artifacts=artifacts,
                history=messages + [agent_msg],
                kind="task"
            )

        # === 5. FOLLOW-UP CHECK ===
        if len(messages) > 1:
            recent_memory = _CONVERSATION_MEMORY.get(context_id, [])[-5:]
            logger.debug(f"Checking memory: {[msg.model_dump() for msg in recent_memory]}")
            for msg in recent_memory:
                if msg.role == "agent":
                    text = " ".join(p.text or "" for p in msg.parts if p.kind == "text")
                    if "SniffBot Code Review" in text or "SniffBot Code Re-Review" in text:
                        logger.debug(f"Follow-up detected in memory, returning: You're welcome! Got more code to sniff?")
                        return self._build_fallback_result(
                            "You're welcome! Got more code to sniff?",
                            task_id, context_id, messages
                        )

        # === 6. FALLBACK FOR NO CODE ===
        if trigger and not code.strip():
            logger.debug("No code detected with sniff this trigger")
            return self._build_fallback_result(
                "**No code detected!**\n\n"
                "You said `sniff this` but no code was found.\n\n"
                "**Example:**\n"
                "```\n"
                "@SniffBot sniff this\n"
                "    x = 1 + \"hello\"\n"
                "```",
                task_id, context_id, messages
            )

        # === 7. DEFAULT FALLBACK ===
        logger.debug("Returning default fallback response")
        return self._build_fallback_result(
            "Say `@SniffBot sniff this` + code to analyze.",
            task_id, context_id, messages
        )
    
    async def execute(
        self,
        messages: List[A2AMessage],
        context_id: str,
        task_id: str
    ) -> TaskResult:
        """
        A2A `execute` method – re-runs analysis on existing context.
        Required for retries, scheduled jobs, or background tasks.
        """
        # Simply reuse process_messages with the provided IDs
        return await self.process_messages(
            messages=messages,
            context_id=context_id,
            task_id=task_id
        )

    # === RESPONSE BUILDERS ===
    def _build_greeting_result(self, task_id, context_id, history):
        text = """
**Hello! I'm SniffBot**  
Your AI-powered code reviewer.

**How to use me:**
1. Paste any code
2. Say `@SniffBot sniff this`
3. I’ll return severity, fix, diff, and commit message

**Example:**
```
@SniffBot sniff this
    print("Hello " + 42)
```

Every Friday → **Smell of the Week**

Try it now!
""".strip()

        msg = A2AMessage(role="agent", parts=[MessagePart(kind="text", text=text)], taskId=task_id, contextId=context_id)
        return TaskResult(
            id=task_id, contextId=context_id,
            status=TaskStatus(state="input-required", message=msg),
            history=history + [msg]
        )

    def _build_help_result(self, task_id, context_id, history):
        text = """
**SniffBot Help**

**Trigger:**
```
@SniffBot sniff this
[your code]
```
@SniffBot fix last
→ Re-analyze the last code you sent

**Code Formats Supported:**
- ```python\n...\n```
- `inline code`
- 4-space indent
- Raw lines with `def`, `function`, etc.

**I return:**
- Severity (Low/Medium/High)
- 1-sentence explanation
- Fixed code diff
- Conventional commit message

**Weekly:** Smell of the Week (Fri 10 AM UTC)
""".strip()

        msg = A2AMessage(role="agent", parts=[MessagePart(kind="text", text=text)], taskId=task_id, contextId=context_id)
        return TaskResult(
            id=task_id, contextId=context_id,
            status=TaskStatus(state="input-required", message=msg),
            history=history + [msg]
        )

    def _build_fallback_result(self, text, task_id, context_id, history):
        msg = A2AMessage(role="agent", parts=[MessagePart(kind="text", text=text)], taskId=task_id)
        return TaskResult(
            id=task_id, contextId=context_id,
            status=TaskStatus(state="input-required", message=msg),
            history=history + [msg]
        )

    def _build_error_result(self, error_msg, task_id, context_id, history):
        text = f"**Error:** {error_msg}\n\nType `help` for usage."
        msg = A2AMessage(role="agent", parts=[MessagePart(kind="text", text=text)], taskId=task_id)
        return TaskResult(
            id=task_id, contextId=context_id,
            status=TaskStatus(state="failed", message=msg),
            history=history + [msg]
        )

    # === INTENT DETECTION ===
    def _is_greeting(self, text: str) -> bool:
        greetings = ["hi", "hello", "hey", "yo", "sup", "morning", "evening"]
        return (
            any(g in text for g in greetings) and
            "@sniffbot" in text and
            "sniff this" not in text and
            "fix last" not in text
        )
    
    def _is_help_command(self, text: str) -> bool:
        return any(cmd in text for cmd in ["help", "?", "how", "what", "usage", "commands"])