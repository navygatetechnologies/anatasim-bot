#!/usr/bin/env python3
"""One-command launcher: starts backend/ and mcp_service/ as subprocesses
(each a real, independently-runnable uvicorn service, exactly like the real
architecture), waits for both to report healthy, then runs the interactive
chat REPL (cli.py) in the foreground. Exiting the REPL (or Ctrl-C) cleans up
both subprocesses.

  python run_demo.py

You'll see each service's own request-log lines interleaved with the chat --
that's intentional, so you can see the real HTTP calls happening underneath.
To run the pieces separately instead (e.g. to curl backend directly, or
point an MCP Inspector at mcp_service's /mcp), see README.md.
"""
import os
import signal
import subprocess
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_PORT = os.environ.get("BACKEND_PORT", "9001")
MCP_PORT = os.environ.get("MCP_PORT", "9005")
os.environ.setdefault("BACKEND_HOST", f"http://localhost:{BACKEND_PORT}")
os.environ["MCP_SERVICE_URL"] = f"http://localhost:{MCP_PORT}"


def _spawn(cwd: str, port: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port],
        cwd=cwd,
        env=os.environ.copy(),
    )


def _wait_healthy(name: str, url: str, proc: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{name} exited early (code {proc.returncode}) -- see its output above")
        try:
            if requests.get(url, timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{name} did not become healthy within {timeout}s -- check its output above")


def main():
    procs = []
    try:
        print("Starting backend (fake Controller) on "
              f"http://localhost:{BACKEND_PORT} ...")
        backend = _spawn(os.path.join(ROOT, "backend"), BACKEND_PORT)
        procs.append(backend)
        _wait_healthy("backend", f"http://localhost:{BACKEND_PORT}/health", backend)

        print(f"Starting mcp_service on http://localhost:{MCP_PORT} ...")
        mcp_service = _spawn(os.path.join(ROOT, "mcp_service"), MCP_PORT)
        procs.append(mcp_service)
        _wait_healthy("mcp_service", f"http://localhost:{MCP_PORT}/health", mcp_service)

        print()
        subprocess.run([sys.executable, os.path.join(ROOT, "cli.py")])
    finally:
        for proc in procs:
            proc.send_signal(signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
