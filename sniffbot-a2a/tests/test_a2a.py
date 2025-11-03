# tests/test_a2a.py
import pytest
import httpx
import json
import time
from datetime import datetime, timedelta

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
BASE_URL = "http://localhost:8080"  # Local
# BASE_URL = "https://your-app.up.railway.app"  # Deployed

A2A_ENDPOINT = f"{BASE_URL}/a2a/sniff"
HEALTH_ENDPOINT = f"{BASE_URL}/health"

# ----------------------------------------------------------------------
# SCORE TRACKING
# ----------------------------------------------------------------------
TOTAL_POINTS = 0
MAX_POINTS = 100

def add_points(points: int, description: str):
    global TOTAL_POINTS
    TOTAL_POINTS += points
    print(f"[+] {description}: +{points} pts")

# ----------------------------------------------------------------------
# HELPER: Send JSON-RPC
# ----------------------------------------------------------------------
def jsonrpc_call(method: str, params: dict, id: str = "test"):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": id
    }
    return httpx.post(A2A_ENDPOINT, json=payload, timeout=10.0)

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
    response = jsonrpc_call("message/send", {}, id="custom-123")
    data = response.json()
    assert data.get("id") == "custom-123"
    add_points(5, "JSON-RPC id preserved")

# ----------------------------------------------------------------------
# TEST: Method Support
# ----------------------------------------------------------------------
def test_message_send_supported():
    response = jsonrpc_call("message/send", {"message": {"role": "user", "parts": []}})
    assert response.status_code == 200 or "error" in response.json()
    add_points(5, "message/send method supported")

def test_execute_supported():
    response = jsonrpc_call("execute", {"messages": []})
    assert response.status_code == 200 or "error" in response.json()
    add_points(5, "execute method supported")

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

def test_task_result_structure():
    response = jsonrpc_call("message/send", {
        "message": {"role": "user", "parts": [{"kind": "text", "text": "x=1"}]}
    })
    if response.status_code != 200:
        return
    result = response.json().get("result", {})
    assert "id" in result
    assert "contextId" in result
    assert "status" in result
    assert "artifacts" in result
    assert "history" in result
    add_points(10, "TaskResult has all required fields")

# ----------------------------------------------------------------------
# TEST: Code Extraction
# ----------------------------------------------------------------------
def test_code_extraction_fenced():
    # [FIX] Add trigger so agent processes code
    response = jsonrpc_call("message/send", {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "@sniffbot sniff this\n```python\nx=1\n```"}]
        }
    })
    if response.status_code != 200:
        return
    artifacts = response.json().get("result", {}).get("artifacts", [])
    assert any(a["name"] == "diff" for a in artifacts)
    add_points(8, "Fenced code block extracted")

def test_code_extraction_inline():
    response = jsonrpc_call("message/send", {
        "message": {"role": "user", "parts": [{"kind": "text", "text": "`x = 1 + 2`"}]}
    })
    if response.status_code == 200:
        add_points(5, "Inline code handled (no crash)")

# ----------------------------------------------------------------------
# TEST: Rate Limiting
# ----------------------------------------------------------------------
def test_rate_limiting():
    user_id = f"test-user-{int(time.time())}"
    headers = {"x-telex-user-id": user_id}
    for _ in range(11):
        response = httpx.post(A2A_ENDPOINT, json={
            "jsonrpc": "2.0", "id": "rate", "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "test"}]}}
        }, headers=headers, timeout=10.0)
        if response.status_code == 429:
            assert "retry_after_seconds" in response.json().get("error", {}).get("data", {})
            add_points(10, "Rate limiting active with Retry-After")
            return
    assert False, "Rate limit not triggered after 11 requests"

# ----------------------------------------------------------------------
# TEST: Health Endpoint
# ----------------------------------------------------------------------
def test_health_endpoint():
    response = httpx.get(HEALTH_ENDPOINT)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "next_smell_of_the_week" in data
    add_points(5, "Health endpoint returns 200 + next smell")

# ----------------------------------------------------------------------
# TEST: Scheduler Integration
# ----------------------------------------------------------------------
def test_scheduler_job_exists():
    response = httpx.get(HEALTH_ENDPOINT)
    if response.status_code != 200:
        return
    data = response.json()
    assert data["active_scheduler_jobs"] >= 1
    next_run = data["next_smell_of_the_week"]
    assert next_run is not None
    add_points(8, "Scheduler job is active")

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