# ANANTASIM chat demo (standalone)

A fully self-contained, runnable extract of the ANANTASIM platform's AI chat assistant --
the feature that lets a user change simulation settings in natural language ("set the inlet
velocity to 5 m/s") and have the platform stage that change behind a Confirm/Cancel prompt
instead of applying it silently.

This is **not** the real product. It's a trimmed copy of two of its real services
(`mcp_service`, the MCP server + LLM tool-calling agent; and a tiny fake `backend` standing in
for the real Controller's database-backed settings API), with everything that requires the real
stack removed:

- No Docker, no Postgres, no Redis, no shared EFS mount.
- No auth/JWT layer -- `cli.py` talks straight to `mcp_service`.
- No job diagnostics / log-reading tools (5 of the real assistant's 9 tools) -- those need a
  real job/EFS directory tree. This demo keeps the 4 settings-editing tools: reading and
  changing the velocity field (`U`) and turbulence model coefficients.
- One seeded in-memory demo project instead of a real database. Restarting the demo resets it.

## Architecture

```
 you (terminal)
      |
      v
 ┌─────────┐   POST /chat            ┌──────────────┐   GET/POST /ai-api/internal/*  ┌─────────┐
 │  cli.py │ ───────────────────────▶│ mcp_service  │────────────────────────────────▶│ backend │
 └─────────┘                         │ (port 9005)  │   GET /fields/*, /bc/types/all  │(port9001)│
      ▲                              └──────────────┘                                 └─────────┘
      |                                     |
      |                              in-memory MCP session
      |                              (real `mcp` SDK, FastMCP)
      |                                     |
      |                              LLM tool-calling loop
      |                          (real Ollama/OpenAI-compatible
      |                           endpoint if reachable, else a
      |                           built-in offline scripted brain)
      └── prints replies, prompts 'confirm'/'cancel' on a pending_action
```

`mcp_service` is a real MCP server (streamable HTTP at `/mcp`) as well as an "agent host": its
own `POST /chat` opens an in-memory MCP client session against its own server and runs a
tool-calling loop. `backend` is a stand-in for the real Controller's `/ai-api/internal/*`
routes -- an in-memory dict instead of Postgres.

**Mutating calls are staged, not auto-applied.** When the assistant decides to call
`set_velocity` or `apply_setting`, `mcp_service` does not execute it -- it returns a
`pending_action` describing exactly what it would do, and only actually runs it once you type
`confirm`. This is deliberate and code-enforced (see `mcp_service/agent.py`), not something the
model is just asked nicely to do.

## Quickstart

```bash
pip install -r requirements.txt
python run_demo.py
```

That starts `backend` and `mcp_service` for you (each a real, independently-runnable `uvicorn`
process) and drops you into the chat REPL. Type `/quit` to exit (this also shuts down both
background services).

Sample session:

```
ANANTASIM chat demo. Type your request ('/quit' to exit).
[using the built-in offline demo brain (no LLM reachable)]
> what's the current inlet velocity?
[offline demo brain] Current velocity (U) configuration:
- internalField: uniform [0, 0, 0]
- inlet: fixedValue [1, 0, 0]
- outlet: zeroGradient None
- wall: noSlip None
> set the inlet velocity to 5 m/s
Set velocity at `inlet` to [5.0, 0.0, 0.0] m/s?
[type 'confirm' to apply this change, or 'cancel' to drop it]
> confirm
Done — Set velocity at `inlet` to [5.0, 0.0, 0.0] m/s?
[change applied: {'status': 'success', 'target': 'inlet', 'value': [5.0, 0.0, 0.0], 'regenerated': 'demo-sim/0/U'}]
> set Cmu to 0.1
Set turbulence `Cmu` to 0.1?
[type 'confirm' to apply this change, or 'cancel' to drop it]
> confirm
Done — Set turbulence `Cmu` to 0.1?
[change applied: {'status': 'success', 'domain': 'turbulence', 'target': 'Cmu', 'value': 0.1, 'regenerated': 'demo-sim/constant/turbulenceProperties'}]
```

## Using a real LLM instead of the offline brain

By default `mcp_service` runs a tiny rule-based fallback (`mcp_service/llm/fake.py`) so this
folder works with nothing installed beyond `pip install -r requirements.txt`. It's enough to
demonstrate the flow, but it's keyword matching, not genuine language understanding.

For the real thing, point it at any OpenAI-compatible chat-completions server -- exactly how the
real product is configured. Easiest option, a local model via [Ollama](https://ollama.com):

```bash
ollama serve
ollama pull qwen2.5:7b
python run_demo.py
```

`mcp_service` probes `LLM_BASE_URL` once at startup; if it's reachable it uses the real model
instead of the fallback (the REPL's startup banner says which one is active). See `.env.example`
for `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` -- any OpenAI-compatible endpoint (LM Studio,
llama.cpp server, or OpenAI itself with a real key) works the same way.

## Running the pieces separately

Each service is independently runnable, same as the real architecture:

```bash
# terminal 1
cd backend && uvicorn main:app --port 9001

# terminal 2
cd mcp_service && uvicorn main:app --port 9005

# terminal 3
python cli.py
```

With `mcp_service` running you can also point the official MCP Inspector at its real MCP
endpoint:

```bash
npx @modelcontextprotocol/inspector
# connect to http://localhost:9005/mcp
```

Or hit `backend` directly:

```bash
curl "http://localhost:9001/ai-api/internal/velocity-context?project_id=demo-project&sim_id=demo-sim&user_id=demo-user" \
  -H "X-Worker-Key: demo-worker-key"
```

## Layout

```
backend/            fake Controller: in-memory settings store + the handful of HTTP routes
                     mcp_service's controller_client.py calls
mcp_service/         trimmed copy of the real mcp_service: MCP server (4 tools), agent loop,
                     pending-action confirm gate, LLM provider (real + offline fallback)
cli.py               interactive REPL, talks to mcp_service's /chat
run_demo.py          starts backend + mcp_service, then runs cli.py
```
