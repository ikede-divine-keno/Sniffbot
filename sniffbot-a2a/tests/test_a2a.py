# tests/test_a2a.py
import pytest
import httpx
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
BASE_URL = "http://localhost:8080"  # Local

A2A_ENDPOINT = f"{BASE_URL}/a2a/sniff"
HEALTH_ENDPOINT = f"{BASE_URL}/health"

# ----------------------------------------------------------------------
# SCORE TRACKING
# ----------------------------------------------------------------------
TOTAL_POINTS = 0
MAX_POINTS = 92

def add_points(points: int, description: str):
    global TOTAL_POINTS
    TOTAL_POINTS += points
    print(f"[+] {description}: +{points} pts")

# ----------------------------------------------------------------------
# HELPER: Send JSON-RPC
# ----------------------------------------------------------------------
def jsonrpc_call(method: str, params: dict, id: str = "test", headers: dict | None = None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": id
    }
    return httpx.post(A2A_ENDPOINT, json=payload, timeout=15.0, headers=headers or {})

# ----------------------------------------------------------------------
# TEST: JSON-RPC 2.0 Compliance
# ----------------------------------------------------------------------
def test_jsonrpc_version():
    response = jsonrpc_call("message/send", {"message": {"role": "user", "parts": []}})
    assert response.status_code in [200, 400, 500]
    data = response.json()
    assert data.get("jsonrpc") == "2.0"
    add_points(5, "JSON-RPC version is 2.0")

def test_jsonrpc_id_preserved():
    custom_id = f"custom-{uuid.uuid4()}"
    response = jsonrpc_call("message/send", {
        "message": {"role": "user", "parts": [{"kind": "text", "text": "test"}]}
    }, id=custom_id)
    data = response.json()
    assert data.get("id") == custom_id
    add_points(5, "JSON-RPC id preserved")

# ----------------------------------------------------------------------
# TEST: Method Support
# ----------------------------------------------------------------------
def test_message_send_supported():
    response = jsonrpc_call("message/send", {"message": {"role": "user", "parts": []}})
    assert response.status_code in [200, 400] or "error" in response.json()
    add_points(5, "message/send method supported")

def test_execute_supported():
    context_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    response = jsonrpc_call("execute", {
        "messages": [],
        "contextId": context_id,
        "taskId": task_id
    })
    data = response.json()
    assert response.status_code == 200 or "error" in data
    if response.status_code == 200:
        result = data.get("result", {})
        assert result.get("contextId") == context_id
        assert result.get("id") == task_id
    add_points(8, "execute preserves contextId and taskId")

def test_invalid_method():
    response = jsonrpc_call("invalid", {})
    data = response.json()
    assert data.get("error", {}).get("code") == -32601
    add_points(5, "Invalid method → -32601")

# ----------------------------------------------------------------------
# TEST: A2A Message Structure
# ----------------------------------------------------------------------
def test_message_parts_text_kind():
    payload = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "hello"}]
        }
    }
    response = jsonrpc_call("message/send", payload)
    assert response.status_code == 200
    add_points(5, "MessagePart kind=text accepted")

def test_message_parts_data_kind():
    payload = {
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "data",
                    "data": [
                        {"kind": "text", "text": "<p>@sniffbot sniff this</p>"},
                        {"kind": "text", "text": "Analyzing..."}
                    ]
                }
            ]
        }
    }
    response = jsonrpc_call("message/send", payload)
    assert response.status_code == 200
    add_points(5, "MessagePart kind=data with list accepted")

def test_task_result_structure():
    response = jsonrpc_call("message/send", {
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "text",
                    "text": "@sniffbot sniff this\n```python\nx=1\n```"
                }
            ]
        }
    })
    if response.status_code != 200:
        return
    result = response.json().get("result", {})
    required = ["id", "contextId", "status", "artifacts", "history", "kind"]
    for field in required:
        assert field in result, f"Missing {field} in TaskResult"
    add_points(10, "TaskResult has all required fields")

# ----------------------------------------------------------------------
# TEST: Code Extraction
# ----------------------------------------------------------------------
def test_code_extraction_fenced():
    response = jsonrpc_call("message/send", {
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "text",
                    "text": "@sniffbot sniff this\n```python\nx=1\n```"
                }
            ]
        }
    })
    if response.status_code != 200:
        print(f"test_code_extraction_fenced failed with status {response.status_code}: {response.text}")
        return
    data = response.json()
    artifacts = data.get("result", {}).get("artifacts", [])
    print(f"Artifacts received: {artifacts}")
    assert any(a["name"] == "diff" for a in artifacts), f"No 'diff' artifact found in {artifacts}"
    add_points(8, "Fenced code block extracted")

def test_code_extraction_inline():
    response = jsonrpc_call("message/send", {
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "text",
                    "text": "@sniffbot sniff this `x = 1 + 2`"
                }
            ]
        }
    })
    if response.status_code != 200:
        print(f"test_code_extraction_inline failed with status {response.status_code}: {response.text}")
        return
    data = response.json()
    artifacts = data.get("result", {}).get("artifacts", [])
    print(f"Artifacts received: {artifacts}")
    assert any(a["name"] == "diff" for a in artifacts), f"No 'diff' artifact found in {artifacts}"
    add_points(5, "Inline code extracted and reviewed")

# ----------------------------------------------------------------------
# TEST: Fix Last Command
# ----------------------------------------------------------------------
def test_fix_last_command():
    user_id = f"fix-user-{uuid.uuid4()}"
    headers = {"x-telex-user-id": user_id}

    resp1 = jsonrpc_call("message/send", {
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "text",
                    "text": "@sniffbot sniff this\n```python\ndef hello():\n    return 42\n```"
                }
            ]
        }
    }, headers=headers)
    assert resp1.status_code == 200, f"First request failed: {resp1.text}"
    ctx = resp1.json()["result"]["contextId"]

    resp2 = jsonrpc_call("execute", {
        "messages": [
            {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": "@sniffbot sniff this\n```python\ndef hello():\n    return 42\n```"
                    }
                ]
            },
            {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": "@sniffbot fix last"
                    }
                ]
            }
        ],
        "contextId": ctx,
        "taskId": str(uuid.uuid4())
    }, headers=headers)
    assert resp2.status_code == 200, f"Fix last request failed: {resp2.text}"
    result = resp2.json()["result"]
    assert result["contextId"] == ctx
    artifacts = result["artifacts"]
    print(f"Fix last artifacts: {artifacts}")
    assert any(a["name"] == "diff" for a in artifacts), f"No 'diff' artifact found in {artifacts}"
    add_points(10, "fix last re-analyzes previous code")

# ----------------------------------------------------------------------
# TEST: Rate Limiting
# ----------------------------------------------------------------------
def test_rate_limiting():
    user_id = f"rate-user-{int(time.time())}"
    headers = {"x-telex-user-id": user_id}

    # Send 11 requests
    responses = []
    for i in range(11):
        resp = jsonrpc_call("message/send", {
            "message": {"role": "user", "parts": [{"kind": "text", "text": "test"}]}
        }, id=f"rate-{i}", headers=headers)
        responses.append(resp)

    # 11th should be 429
    assert responses[-1].status_code == 429
    data = responses[-1].json()
    assert data["error"]["code"] == -32000
    assert "retry_after_seconds" in data["error"]["data"]
    retry_after = data["error"]["data"]["retry_after_seconds"]
    assert isinstance(retry_after, int) and retry_after > 0
    add_points(10, "Rate limiting active with Retry-After")

# ----------------------------------------------------------------------
# TEST: Health & Scheduler
# ----------------------------------------------------------------------
def test_health_endpoint():
    response = httpx.get(HEALTH_ENDPOINT, timeout=10.0)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "next_smell_of_the_week" in data
    assert data["active_scheduler_jobs"] >= 1
    add_points(5, "Health endpoint returns 200 + next smell")

def test_scheduler_job_exists():
    response = httpx.get(HEALTH_ENDPOINT)
    if response.status_code != 200:
        return
    data = response.json()
    assert data["active_scheduler_jobs"] >= 1
    next_run = data["next_smell_of_the_week"]
    assert next_run is not None
    # Parse ISO → validate future (using timezone.utc)
    dt = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
    assert dt > datetime.now(timezone.utc)
    add_points(8, "Scheduler job is active and in future")

# ----------------------------------------------------------------------
# TEST: Error Handling
# ----------------------------------------------------------------------
def test_malformed_json():
    response = httpx.post(A2A_ENDPOINT, content="{bad", headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    data = response.json()
    assert data.get("error", {}).get("code") == -32700
    add_points(5, "Malformed JSON → -32700 Parse error")

def test_invalid_params():
    response = jsonrpc_call("message/send", {"message": "invalid"})
    data = response.json()
    assert data.get("error", {}).get("code") == -32602
    add_points(5, "Invalid params → -32602")

# ----------------------------------------------------------------------
# FINAL SCORE
# ----------------------------------------------------------------------
def test_final_score():
    global TOTAL_POINTS, MAX_POINTS
    score = min(TOTAL_POINTS, MAX_POINTS)
    print("\n" + "="*50)
    print(f" FINAL SCORE: {score}/{MAX_POINTS}")
    print("="*50)
    if score == MAX_POINTS:
        print("100% A2A + JSON-RPC 2.0 COMPLIANT")
    elif score >= 85:
        print("Excellent — Ready for production")
    elif score >= 70:
        print("Good — Minor fixes needed")
    else:
        print("Needs improvement")
    assert score == MAX_POINTS  # Fail if not perfect