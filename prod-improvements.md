# Production Improvements

Two production-readiness improvements made to `mcp_service` on branch
`feature/structured-logging`. Both are additive — no existing behaviour
was removed or changed.

---

## 1. Structured JSON Logging

### Problem

The service had no real logging. The only output was a single `print()`
in `controller_client.py`:

```
MCP API: GET http://localhost:9001/ai-api/internal/velocity-context 200
```

In production with multiple concurrent users this creates three problems:

- **No correlation.** Log lines from 50 simultaneous requests are
  interleaved with no way to connect a line to its request.
- **No queryability.** Plain text cannot be filtered, aggregated, or
  alerted on by a log aggregator (Datadog, CloudWatch, Grafana Loki).
- **Silent failures.** When the agent hit `AGENT_MAX_TURNS` the user
  received "I couldn't complete that request" with zero trace of why.

### Solution

A new file `mcp_service/logger.py` provides a structured JSON logger
used by every layer of the service.

**Every log line is one JSON object on stdout:**

```json
{
  "ts": "2026-08-15T14:53:53.733+00:00",
  "level": "info",
  "logger": "agent",
  "request_id": "a6a83326",
  "event": "tool_call_completed",
  "tool": "get_velocity_context",
  "duration_ms": 309,
  "user_id": "demo-user",
  "project_id": "demo-project",
  "sim_id": "demo-sim"
}
```

**How `request_id` works across concurrent requests:**

Each request gets a unique 8-character ID generated in `main.py` at the
start of every `/chat` call. It is stored in a Python `ContextVar` — a
built-in async-safe variable where each concurrent coroutine holds its
own isolated copy. Every log line anywhere in the call stack reads this
variable automatically. No parameter passing required.

This means in a log aggregator you can filter `request_id=a6a83326` and
see the complete timeline of one specific request, pulled out of a stream
of thousands of lines from concurrent users.

**Log events emitted and their levels:**

| Event | Level | Where | What it tells you |
|---|---|---|---|
| `service_started` | info | startup | which LLM provider is active |
| `chat_request_received` | info | per request | user, project, sim, confirm or new message |
| `chat_request_completed` | info | per request | applied, pending_action, total duration |
| `agent_loop_started` | info | agent | number of messages in context |
| `llm_call_completed` | info | agent | which tools the LLM decided to call, duration |
| `tool_call_completed` | info | agent | tool name, duration |
| `tool_call_staged` | info | agent | mutating tool intercepted, shown to user for confirm |
| `confirm_started` | info | agent | which tool the user is confirming |
| `confirm_completed` | info | agent | confirm executed successfully |
| `backend_request` | info | controller | method, url, status, duration |
| `llm_provider_initialised` | info | factory | which provider was chosen at startup |
| `llm_provider_recovered` | info | factory | LLM came back online, switched to real |
| `agent_loop_completed` | info | agent | how many turns were used |
| `agent_max_turns_reached` | **warning** | agent | LLM loop exhausted — was silent before |
| `llm_provider_degraded` | **warning** | factory | LLM went down, switched to fake |
| `tool_call_error` | **error** | agent | tool failed (e.g. backend unreachable) |
| `confirm_tool_error` | **error** | agent | confirmed action failed at execution |
| `backend_error` | **error** | controller | backend returned 4xx/5xx |
| `agent_unhandled_error` | **error** | agent | unexpected exception with traceback |

**Alerting:** configure your log aggregator to alert on `level=error`
events in real time and on elevated rates of `level=warning` events
(e.g. `agent_max_turns_reached` > 10% of requests signals the LLM is
looping or confused).

**New env var:**

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Minimum log level. Set to `DEBUG` for verbose output, `WARNING` in high-traffic prod to reduce volume. |

**Files changed:**
- `mcp_service/logger.py` — new file, the entire logging implementation
- `mcp_service/config.py` — `LOG_LEVEL` env var
- `mcp_service/main.py` — configure logger, `new_request_id()` per request, log request lifecycle
- `mcp_service/agent.py` — log every LLM call, tool call, staging, confirm, max turns, errors
- `mcp_service/controller_client.py` — replace `print()` with structured log

---

## 2. LLM Provider Health Watcher

### Problem

`mcp_service/llm/factory.py` decided which LLM provider to use by
probing the endpoint once at startup and caching the result forever.
This caused four bugs:

**Bug 1 — provider never re-evaluated.**
Once chosen, the provider was never reconsidered regardless of what
happened to the LLM endpoint afterwards.

**Bug 2 — no recovery when LLM goes down after startup.**
If the service started with a real LLM and the LLM went down two hours
later, the service kept trying to use it. Every user request would fail
with a connection error until someone manually restarted the process.

**Bug 3 — no upgrade when LLM recovers after startup.**
If the LLM was down at startup, the service chose `FakeLLMProvider` and
kept it forever — even after the LLM came back online minutes later.
Users silently received keyword-matching responses thinking they were
talking to a real AI. No error, no log, no indication anything was wrong.

**Bug 4 — synchronous TCP probe blocked the async event loop.**
`_real_llm_reachable` used `socket.create_connection` with a 500ms
timeout — a synchronous blocking call. In an async service this freezes
the entire event loop for up to 500ms every time it runs, stalling all
concurrent requests.

All four bugs were confirmed with tests before the fix was written.

### Solution

`factory.py` was rewritten around a `_ProviderManager` class with a
`refresh()` method and a background `start_health_watcher()` async task.

**How it works:**

```
service starts
    │
    ├── get_provider() initialises synchronously (acceptable, server
    │   hasn't started accepting requests yet)
    │
    └── start_health_watcher() runs as an asyncio background task
            │
            every LLM_HEALTH_INTERVAL seconds:
            │
            ├── await _real_llm_reachable()   ← async, non-blocking
            │
            ├── if status unchanged → do nothing
            │
            ├── if real → fake:
            │       switch provider to FakeLLMProvider
            │       log WARNING "llm_provider_degraded"
            │                    ↑ alert fires here
            │
            └── if fake → real:
                    switch provider to OpenAICompatProvider
                    log INFO "llm_provider_recovered"
```

**State transitions logged:**

```json
{"level": "warning", "event": "llm_provider_degraded",
 "from_kind": "real", "to_kind": "fake", "url": "http://localhost:11434/v1"}

{"level": "info", "event": "llm_provider_recovered",
 "from_kind": "fake", "to_kind": "real", "url": "http://localhost:11434/v1"}
```

**Thread safety:** replacing `_provider` on the manager is safe under
asyncio's single-threaded event loop. A request mid-flight holds a
reference to the provider object it started with and completes normally.
The swap only affects the next call to `get_provider()`.

**Clean shutdown:** `main.py` creates the watcher as an `asyncio.Task`
and cancels it in the lifespan teardown, ensuring no orphaned tasks on
process exit.

**New env var:**

| Variable | Default | Purpose |
|---|---|---|
| `LLM_HEALTH_INTERVAL` | `30` | Seconds between LLM endpoint probes. Set to `0` to disable the watcher entirely. |

**Files changed:**
- `mcp_service/llm/factory.py` — full rewrite
- `mcp_service/main.py` — starts and cancels the watcher task in lifespan
- `mcp_service/config.py` — `LLM_HEALTH_INTERVAL` env var

**Tests:**
- `mcp_service/tests/test_llm_factory.py` — 6 tests covering all four
  fixes, the no-op case, and clean watcher cancellation
- `mcp_service/pytest.ini` — pytest asyncio configuration

Run with:
```bash
cd mcp_service
python -m pytest tests/test_llm_factory.py -v
```

---

## 3. Per-User Rate Limiting

### Problem

Before this change, a single user could send unlimited requests to
`/chat`. Every request:

- Calls the LLM — costs money per token with a real model
- Runs an agent loop for up to `AGENT_MAX_TURNS` turns
- Hits the backend on each tool call

A buggy frontend, an automated script, or a single bad actor could
exhaust the LLM budget, slow down every other user, or overload the
backend. There was no protection at any layer.

This is the same problem Google Gemini solves at the infrastructure
layer with their requests-per-minute and tokens-per-day limits. We solve
it at the application layer — which means we control the logic, we can
make it domain-aware (confirm flows are exempt), and every rejection is
logged so you can see exactly who is hitting limits and why.

### Solution

A new file `mcp_service/rate_limiter.py` implements a **sliding window**
rate limiter keyed by `user_id`, enforcing two independent limits:

- **RPM (requests per minute)** — protects against burst abuse and
  runaway frontends. Default: 20.
- **RPD (requests per day)** — protects against LLM cost exhaustion
  over a full working day. Default: 200.

**Why sliding window and not fixed window?**

A fixed window resets all at once — a user could send 20 requests at
23:59, the window resets at 00:00, and they send 20 more immediately.
That's 40 requests in 2 seconds. A sliding window tracks individual
timestamps — the window moves continuously so the limit is always
enforced over the last 60 real seconds, not the last calendar minute.

**How it works:**

Each user has a deque (double-ended queue) of request timestamps for
each window. On every request:
1. Timestamps older than the window size are dropped from the front
2. If the remaining count equals or exceeds the limit → reject with
   `RateLimitExceeded`, including a `retry_after` telling the user
   exactly how long to wait
3. Otherwise → record the timestamp and proceed

**Confirm requests are exempt from both limits:**

When a user confirms a `PendingAction` there is no LLM call and no
agent loop — just a single tool execution. Blocking confirms would
strand users mid-conversation with no way to proceed or cancel. Confirm
requests also do not consume quota, so they cannot be used to game the
limiter.

**What a rejected request looks like:**

The user receives a clean `ChatResponse` (not an HTTP error):
```json
{
  "message": "You're sending requests too quickly. Please wait 42 seconds before trying again.",
  "applied": false
}
```

And the log captures the full context:
```json
{
  "level": "warning",
  "event": "rate_limit_exceeded",
  "user_id": "u_123",
  "project_id": "proj_xyz",
  "window": "minute",
  "limit": 20,
  "retry_after_seconds": 42,
  "rpm": 20,
  "rpd": 87
}
```

This log line is what you alert on. If one user is repeatedly hitting
the limit, the `user_id` and `project_id` fields tell you exactly who
and where.

**New env vars:**

| Variable | Default | Purpose |
|---|---|---|
| `RATE_LIMIT_RPM` | `20` | Max requests per minute per user. Set to `0` to disable. |
| `RATE_LIMIT_RPD` | `200` | Max requests per day per user. Set to `0` to disable. |

**Scale note:** the counter lives in memory in a single process. For a
multi-instance deployment behind a load balancer, each instance tracks
its own counter independently — the effective limit multiplies by the
number of instances. For true global rate limiting at scale, replace the
in-memory deque with a Redis sorted set. The `RateLimiter` interface
does not change — only the storage backend.

**Files changed:**
- `mcp_service/rate_limiter.py` — new file, the full implementation
- `mcp_service/main.py` — creates limiter singleton, checks before
  `run_chat`, logs rejections
- `mcp_service/config.py` — `RATE_LIMIT_RPM` and `RATE_LIMIT_RPD`
  env vars

**Tests:**
- `mcp_service/tests/test_rate_limiter.py` — 16 tests covering RPM
  and RPD blocking, sliding window eviction, confirm exemption, quota
  not consumed by confirms, disabled limits, user isolation,
  `retry_after` bounds, and `current_counts` accuracy

Run with:
```bash
cd mcp_service
python -m pytest tests/test_rate_limiter.py -v
```

---

## Test Suite Summary

All improvements are covered by automated tests. Run the full suite:

```bash
cd mcp_service
python -m pytest tests/ -v
```

Current state: **22 tests, all passing.**

| Test file | Tests | What it covers |
|---|---|---|
| `tests/test_llm_factory.py` | 6 | LLM provider health watcher fixes |
| `tests/test_rate_limiter.py` | 16 | Rate limiter all scenarios |
