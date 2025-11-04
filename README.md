# SniffBot A2A Agent 🚀
GitHub repo for HNG Internship Stage 1 A2A Code Review Agent

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.12-green.svg)
![Railway](https://img.shields.io/badge/Deployed-Railway-blueviolet.svg)

## SniffBot A2A Agent

SniffBot is an AI-powered code review agent built with Python and FastAPI, integrating with the Telex.im platform via the Agent-to-Agent (A2A) protocol. It analyzes code snippets, detects issues (e.g., type errors like `x = 1 + "hello"`), and provides severity ratings, fixed code diffs, and conventional commit messages. Deployed on Railway as part of the HNG Internship, SniffBot offers real-time feedback for developers.

The project uses in-memory storage for conversation history, resetting on server restart. For production persistence, consider integrating Redis or a database.
```

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Setup Instructions](#setup-instructions)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
- [Usage](#usage)
  - [Running Locally](#running-locally)
  - [Testing with cURL](#testing-with-curl)
  - [Telex.im Integration](#telexim-integration)
- [Deployment](#deployment)
- [API Endpoints](#api-endpoints)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

- **Code Analysis**: Detects syntax errors and type mismatches using the Groq API.
- **Automated Fixes**: Suggests corrected code with diffs (e.g., `x = str(1) + "hello"`).
- **Artifact Generation**: Returns `review`, `diff`, and `commit` artifacts in A2A responses.
- **Conversation Memory**: Supports follow-ups (e.g., responds to `thanks` with `"You're welcome! Got more code to sniff?"`).
- **Rate Limiting**: Limits requests to 10 per minute per user (configurable).
- **Weekly Smell of the Week**: Posts a code smell every Friday at 10 AM UTC via APScheduler.
- **Telex.im Compatibility**: Integrates with Telex.im’s A2A protocol for real-time reviews.

## Project Structure

The project is organized as follows:

```
sniffbot-a2a/
├── models/
│   └── a2a.py          # Pydantic models for A2A protocol (MessagePart, A2AMessage, TaskResult, etc.)
├── utils/
│   ├── code_extractor.py  # Extracts code blocks from text
│   └── diff.py           # Generates diff between original and fixed code
├── tests/               # Unit tests for agent and server functionality
├── agent.py             # Core agent logic, including Groq API calls and response generation
├── main.py              # FastAPI server handling A2A requests
├── requirements.txt     # Project dependencies
├── .env                 # Environment variables (e.g., GROQ_API_KEY)
├── examples/            # Optional: Example JSON-RPC requests (e.g., example_request.json)
├── .gitignore           # Git ignore file
└── README.md            # This file
```

- **`models/a2a.py`**: Defines the A2A protocol models with Pydantic for validation.
- **`utils/`**: Contains helper utilities for code extraction and diff generation.
- **`tests/`**: Includes unit tests to ensure reliability (e.g., `test_agent.py`, `test_main.py`).
- **`agent.py`**: Implements the SniffBot logic, processing messages and generating artifacts.
- **`main.py`**: Sets up the FastAPI server, handles JSON-RPC requests, and delegates to the agent.
- **`requirements.txt`**: Lists dependencies for installation.
- **`.env`**: Stores sensitive configuration like the Groq API key.

## Setup Instructions

### Prerequisites

- **Python 3.11+**: Ensure Python is installed (`python --version`).
- **Git**: For cloning the repository (`git --version`).
- **Railway Account**: For deployment (sign up at [railway.app](https://railway.app)).
- **Groq API Key**: Obtain from [Groq](https://groq.com) for code analysis.

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/your-username/sniffbot-a2a.git
   cd sniffbot-a2a
   ```

2. Create a virtual environment and activate it:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   The `requirements.txt` file should contain:

   ```
   fastapi[all]>=0.115.12
   pydantic>=2.8.0
   httpx>=0.28.1
   python-dotenv>=1.1.0
   apscheduler>=3.10.4
   ```

### Configuration

1. Create a `.env` file in the project root:

   ```bash
   touch .env
   ```

2. Add the following environment variables:

   ```
   # Server Configuration
   PORT=8080
   RATE_LIMIT_PER_MINUTE=10

   # Groq API
   GROQ_API_KEY=<your-groq-api-key>
   ```

   Replace `<your-groq-api-key>` with your actual Groq API key.

## Usage

### Running Locally

1. Start the FastAPI server:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4 --log-level error
   ```

   The server will be available at `http://localhost:8080`.

2. Test the health endpoint:

   ```bash
   curl http://localhost:8080/health
   ```

   Expected response (as of 01:05 AM WAT, Tuesday, November 04, 2025):

   ```json
   {
     "status": "healthy",
     "agent": "SniffBot",
     "model": "llama-3.1-8b-instant",
     "rate_limit": "10 per minute per user",
     "active_scheduler_jobs": 1,
     "next_smell_of_the_week": "2025-11-07T10:00:00+00:00"
   }
   ```

### Testing with cURL

Test a code review request:

```bash
curl -X POST http://localhost:8080/a2a/sniff \
  -H "Content-Type: application/json" \
  -H "x-telex-user-id: 019a4b99-61ef-7c93-b194-bb6d93aa8d01" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test-001",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "@sniffbot sniff this\n```python\nx = 1 + \"hello\"\n```"
          }
        ],
        "messageId": "msg-001"
      },
      "configuration": {
        "blocking": true
      }
    }
  }'
```

Expected response:

```json
{
  "jsonrpc": "2.0",
  "id": "test-001",
  "result": {
    "id": "<task_id>",
    "contextId": "<context_id>",
    "status": {
      "state": "completed",
      "message": {
        "role": "agent",
        "parts": [
          {
            "kind": "text",
            "text": "**SniffBot Code Review** 🔴 **High**\n\n> TypeError: unsupported operand type(s) for +: 'int' and 'str'.\n\n**Fixed Code (Diff)**\n```diff\n--- original\n+++ fixed\n@@ -1 +1 @@\n-x = 1 + \"hello\"\n+x = str(1) + \"hello\"\n```\n\n**Commit Message**\n`Fix TypeError by converting integer to string for concatenation`"
          }
        ],
        "taskId": "<task_id>",
        "contextId": "<context_id>"
      }
    },
    "artifacts": [
      {
        "name": "review",
        "parts": [{"kind": "text", "text": "Severity: High\nExplanation: TypeError: unsupported operand type(s) for +: 'int' and 'str'."}]
      },
      {
        "name": "diff",
        "parts": [{"kind": "text", "text": "```diff\n--- original\n+++ fixed\n@@ -1 +1 @@\n-x = 1 + \"hello\"\n+x = str(1) + \"hello\"\n```"}]
      },
      {
        "name": "commit",
        "parts": [{"kind": "text", "text": "Fix TypeError by converting integer to string for concatenation"}]
      }
    ],
    "history": [...]
  }
}
```

Test a follow-up (e.g., after the above request):

```bash
curl -X POST http://localhost:8080/a2a/sniff \
  -H "Content-Type: application/json" \
  -H "x-telex-user-id: 019a4b99-61ef-7c93-b194-bb6d93aa8d01" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test-002",
    "method": "execute",
    "params": {
      "messages": [
        {
          "role": "user",
          "parts": [{"kind": "text", "text": "@sniffbot sniff this\n```python\nx = 1 + \"hello\"\n```"}]
        },
        {
          "role": "agent",
          "parts": [{"kind": "text", "text": "**SniffBot Code Review** 🔴 **High**\n\n> TypeError: unsupported operand type(s) for +: 'int' and 'str'.\n\n**Fixed Code (Diff)**\n```diff\n--- original\n+++ fixed\n@@ -1 +1 @@\n-x = 1 + \"hello\"\n+x = str(1) + \"hello\"\n```\n\n**Commit Message**\n`Fix TypeError by converting integer to string for concatenation`"}]
        },
        {
          "role": "user",
          "parts": [{"kind": "text", "text": "thanks"}]
        }
      ],
      "contextId": "<context_id_from_previous_response>",
      "taskId": "test-002"
    }
  }'
```

Expected response:

```json
{
  "jsonrpc": "2.0",
  "id": "test-002",
  "result": {
    "id": "test-002",
    "contextId": "<context_id>",
    "status": {
      "state": "input-required",
      "message": {
        "role": "agent",
        "parts": [{"kind": "text", "text": "You're welcome! Got more code to sniff?"}],
        "taskId": "test-002"
      }
    },
    "artifacts": [],
    "history": [...]
  }
}
```

### Telex.im Integration

To integrate SniffBot with Telex.im, update your `workflow.json`:

```json
{
  "nodes": [
    {
      "id": "sniffbot",
      "name": "SniffBot Code Reviewer",
      "type": "a2a/generic-a2a-node",
      "url": "https://sniffbot-a2a.railway.app/a2a/sniff"
    }
  ]
}
```

Use Telex.im to send commands like:

```
@sniffbot sniff this
```python
x = 1 + "hello"
```
```

SniffBot will respond with a code review in the chat.

## Deployment

SniffBot is deployed directly on Railway without Docker. Follow these steps:

1. **Initialize a Railway Project**:
   - Install the Railway CLI: `curl -fsSL https://railway.app/install.sh | sh`.
   - Log in: `railway login`.

2. **Link Your Repository**:
   - Run `railway init` in the `sniffbot-a2a` directory and connect it to your GitHub repository (e.g., `your-username/sniffbot-a2a`).
   - Set the root directory to `/` if prompted.

3. **Configure Environment Variables**:
   - Add variables in the Railway dashboard under "Settings > Variables":
     - `GROQ_API_KEY`: Your Groq API key.
     - `PORT`: `8080`.
     - `RATE_LIMIT_PER_MINUTE`: `10` (optional, defaults to 10).

4. **Deploy**:
   - Push changes to your GitHub repository:
     ```bash
     git add .
     git commit -m "Initial deployment"
     git push origin main
     ```
   - Railway will automatically build and deploy the app. Access it at the provided URL (e.g., `https://sniffbot-a2a.railway.app`).

5. **Monitor Logs**:
   - View logs with `railway logs` to debug issues.

## API Endpoints

- **`/a2a/sniff` (POST)**: Handles A2A JSON-RPC requests (`message/send`, `execute`).
  - **Request**: JSON-RPC 2.0 compliant with `params` containing `message` or `messages`.
  - **Response**: `TaskResult` with status, artifacts, and history.
  - **Headers**: `x-telex-user-id` for rate limiting.

- **`/health` (GET)**: Returns the agent’s health status.
  - **Response**: JSON with `status`, `agent`, `model`, `rate_limit`, and scheduler details.

## Contributing

Contributions are welcome! To contribute:

1. Fork the repository.
2. Create a branch: `git checkout -b feature/your-feature`.
3. Commit changes: `git commit -m "Add your feature"`.
4. Push to the branch: `git push origin feature/your-feature`.
5. Open a pull request.

Please adhere to the [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details. *(Create a `LICENSE` file if not present.)*

## Acknowledgments

- **HNG Internship**: For the opportunity to build this agent.
- **Telex.im**: For the A2A protocol and platform support.
- **Groq**: For the powerful AI API.
- **Railway**: For free deployment hosting.

---
