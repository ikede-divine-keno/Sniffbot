# main.py
import os
import uuid
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from dotenv import load_dotenv

from models.a2a import (
    JSONRPCRequest, JSONRPCResponse, MessageParams, ExecuteParams,
    MessageConfiguration, TaskResult
)
from agent import SniffBot

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Load .env (Railway supplies env vars directly – load_dotenv is safe)
# ----------------------------------------------------------------------
load_dotenv()

# ----------------------------------------------------------------------
# Rate Limiting: Configurable from .env
# ----------------------------------------------------------------------
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))  # Default: 10
RATE_WINDOW = timedelta(minutes=1)

# In-memory store: identifier (user_id preferred) → list of timestamps
_request_log = defaultdict(list)

def is_rate_limited(identifier: str) -> bool | int:
    """
    Returns False if allowed.
    Returns int (seconds until reset) if rate-limited.
    """
    now = datetime.utcnow()
    timestamps = _request_log[identifier]

    # Remove expired timestamps
    valid = [t for t in timestamps if now - t < RATE_WINDOW]
    _request_log[identifier] = valid

    if len(valid) >= RATE_LIMIT_PER_MINUTE:
        reset_in = int((RATE_WINDOW - (now - valid[0])).total_seconds()) + 1
        return reset_in

    valid.append(now)
    return False

# ----------------------------------------------------------------------
# SniffBot instance
# ----------------------------------------------------------------------
sniffbot = SniffBot()


# ----------------------------------------------------------------------
# Lifespan – initialise the bot once at startup
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required")

    await sniffbot.initialize(api_key)
    
    from scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    logger.info("SniffBot started – scheduler active")
    
    yield
    
    stop_scheduler()
    logger.info("SniffBot shutdown")


app = FastAPI(
    title="SniffBot A2A Agent",
    description="AI-powered code review agent that speaks JSON-RPC 2.0 (Groq + Railway)",
    version="1.0.0",
    lifespan=lifespan,
)


# ----------------------------------------------------------------------
# Helper: build JSON-RPC error response
# ----------------------------------------------------------------------
def jsonrpc_error(req_id: str | None, code: int, message: str, data: dict | None = None):
    payload = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message}
    }
    if data:
        payload["error"]["data"] = data
    # -32768 to -32600 → 400, others → 500
    status_code = 400 if -32768 <= code <= -32600 else 500
    return JSONResponse(status_code=status_code, content=payload)

EXAMPLES = {}
for name in ["example_request", "example_execute"]:
    p = Path(__file__).parent / "examples" / f"{name}.json"
    if p.is_file():
        with p.open("r", encoding="utf-8") as f:
            EXAMPLES[name] = json.load(f)

# ----------------------------------------------------------------------
# /a2a/sniff – the only public A2A endpoint
# ----------------------------------------------------------------------
@app.post("/a2a/sniff",
         summary="A2A JSON-RPC Endpoint",
         description="Accepts JSON-RPC 2.0 requests (message/send, execute)",
         responses={
             200: {
                 "description": "JSON-RPC success response",
                 "content": {
                     "application/json": {
                         "examples": {
                             "message/send": {
                                 "summary": "Code review request",
                                 "value": EXAMPLES.get("example_request")
                             },
                             "execute": {
                                 "summary": "Resume task",
                                 "value": EXAMPLES.get("example_execute")
                             }
                         }
                     }
                 }
             },
             400: {
                 "description": "JSON-RPC error",
                 "content": {
                     "application/json": {
                         "example": {
                             "jsonrpc": "2.0",
                             "id": "1",
                             "error": {"code": -32600, "message": "Invalid Request"}
                         }
                     }
                 }
             }
         }
)
async def a2a_endpoint(request: Request):
    # ---- 1. Parse raw JSON (catch malformed body) --------------------
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning(f"Invalid JSON body: {exc}")
        return jsonrpc_error(None, -32700, "Parse error")

    # ---- 2. Validate JSON-RPC envelope -------------------------------
    if body.get("jsonrpc") != "2.0" or "id" not in body or "method" not in body:
        return jsonrpc_error(body.get("id"), -32600, "Invalid Request")

    req_id = body["id"]
    method = body.get("method")

    # ---- 3. Validate method ------------------------------------------
    if method not in {"message/send", "execute"}:
        return jsonrpc_error(req_id, -32601, "Method not found")

    # ---- 4. Extract Telex identifiers (user > channel > fallback) ----
    user_id = request.headers.get("x-telex-user-id")
    channel_id = request.headers.get("x-telex-channel-id", "unknown")
    ip_fallback = request.headers.get("x-forwarded-for", "unknown")
    identifier = user_id or channel_id or ip_fallback

    logger.info(f"Incoming request | id={req_id} | user={user_id or 'none'} | channel={channel_id} | identifier={identifier}")

    # ---- 5. Rate Limiting Check (per-user preferred) -----------------
    rate_result = is_rate_limited(identifier)
    if rate_result:
        logger.warning(f"Rate limited | identifier={identifier} | retry_after={rate_result}s")
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(rate_result)},
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Rate limited: {RATE_LIMIT_PER_MINUTE} requests per minute per user",
                    "data": {"retry_after_seconds": rate_result}
                }
            }
        )

    # ---- 6. Parse request with Pydantic (strong typing) -------------
    try:
        if method == "message/send":
            params = MessageParams(**body["params"])
            messages = [params.message]
            config = params.configuration
            context_id = getattr(params.message, "contextId", None) or str(uuid.uuid4())
        elif method == "execute":
            params = ExecuteParams(**body["params"])
            messages = params.messages
            context_id = params.contextId or str(uuid.uuid4())
            task_id = params.taskId or str(uuid.uuid4())
        else:
            return jsonrpc_error(req_id, -32601, "Method not found")
    except ValidationError as exc:
        logger.warning(f"JSON-RPC validation failed: {exc}")
        return jsonrpc_error(req_id, -32602, "Invalid params", {"details": str(exc)})
    except Exception as exc:
        logger.warning(f"Unexpected error during params parsing: {exc}")
        return jsonrpc_error(req_id, -32602, "Invalid params", {"details": str(exc)})

    # ---- 7. Delegate to agent (all heavy lifting) -------------------
    try:
        result: TaskResult = await sniffbot.process_messages(
            messages=messages,
            context_id=context_id,
            task_id=task_id,
        )
        logger.info(f"Agent processed successfully | task_id={task_id}")
    except Exception as exc:
        logger.error(f"Agent processing failed: {exc}", exc_info=True)
        return jsonrpc_error(req_id, -32000, "Server error", {"details": str(exc)})

    # ---- 8. Return compliant JSON-RPC response -----------------------
    response = JSONRPCResponse(id=req_id, result=result)
    return JSONResponse(content=response.model_dump(exclude_none=True))


# ----------------------------------------------------------------------
# Health check – useful for Railway / uptime monitors
# ----------------------------------------------------------------------
@app.get("/health")
async def health():
    from scheduler import scheduler

    jobs = scheduler.get_jobs()
    return {
        "status": "healthy",
        "agent": "SniffBot",
        "model": sniffbot.model,
        "rate_limit": f"{RATE_LIMIT_PER_MINUTE} per minute per user",
        "active_scheduler_jobs": len(jobs),
        "next_smell_of_the_week": jobs[0].next_run_time.isoformat() if jobs else None
    }


# ----------------------------------------------------------------------
# Local dev entrypoint (optional – Railway uses start.sh)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")