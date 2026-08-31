# Production Improvements

Three production-readiness improvements made to `mcp_service`.

---

## 1. Structured JSON Logging

**Problem:** The service had no real logging. One `print()` statement. Zero
visibility into what was happening in production. Silent failures, no way
to trace errors, no way to know which user was affected.

**What we built:** Every request now produces a complete JSON timeline on
stdout — who sent it, what the AI decided, which tools ran, how long each
step took, whether anything failed. Every line carries a `request_id` so
you can pull the full story of one request out of thousands in seconds.

**Why it matters:** This is the difference between running a service and
operating one. Without it you find out something is broken when a user
complains. With it, an alert fires and you know within a minute.

**Key log events:** `chat_request_received`, `tool_call_completed`,
`tool_call_error`, `agent_max_turns_reached` (was completely silent before),
`backend_error`, `backend_request` with `duration_ms`.

**Env var:** `LOG_LEVEL` (default `INFO`)

---

## 2. LLM Provider Health Watcher

**Problem:** The service decided which AI model to use once at startup and
never reconsidered. If the LLM went down after startup — every user got
errors with no fallback, until someone manually restarted the process. If
the LLM was down at startup — users silently got a dumb keyword brain for
the entire lifetime of the service. No error, no log, no indication.

**What we built:** A background task that re-probes the LLM endpoint every
30 seconds and automatically switches the provider if the status changed.
LLM goes down → falls back to offline mode instantly. LLM comes back →
upgrades to real AI automatically. No restart needed. Also fixed the probe
itself which was a synchronous blocking call — replaced with async so it
never freezes the event loop.

**Why it matters:** Self-healing. The service recovers without human
intervention.

**Key log events:** `llm_provider_degraded` (warning — alert on this),
`llm_provider_recovered` (info).

**Env var:** `LLM_HEALTH_INTERVAL` (default `30` seconds, `0` = disabled)

---

## 3. Per-User Rate Limiting

**Problem:** One user could send unlimited requests. Every request calls
the LLM (costs money per token), runs an agent loop, and hits the backend.
A buggy frontend or a single bad actor could exhaust the LLM budget or
slow down every other user. No protection at any layer.

**What we built:** A sliding window rate limiter keyed by `user_id` with
two independent limits — 20 requests per minute and 200 per day. Sliding
window means the limit is always enforced over the last 60 real seconds,
not a fixed bucket that resets all at once. Confirm requests are exempt —
blocking a confirm would strand users mid-conversation. Every rejection is
logged with the user, project, window, and retry time.

**Why it matters:** Same protection Google Gemini provides at the
infrastructure layer. We do it at the application layer so we control the
logic and every rejection is observable.

**Key log event:** `rate_limit_exceeded` (warning) with `user_id`,
`window`, `retry_after_seconds`.

**Env vars:** `RATE_LIMIT_RPM` (default `20`), `RATE_LIMIT_RPD`
(default `200`). Set either to `0` to disable.

---

## Files Changed

| File | Change |
|---|---|
| `mcp_service/logger.py` | New — JSON formatter, request_id via ContextVar |
| `mcp_service/rate_limiter.py` | New — sliding window limiter |
| `mcp_service/llm/factory.py` | Rewritten — health watcher, async probe |
| `mcp_service/main.py` | Logging setup, rate limit check, watcher task |
| `mcp_service/agent.py` | Full instrumentation on every loop step |
| `mcp_service/controller_client.py` | Replaced print() with structured log |
| `mcp_service/config.py` | Three new env vars |
