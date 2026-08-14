#!/usr/bin/env python3
"""Minimal REPL for the ANANTASIM chat demo.

Talks directly to mcp_service's /chat -- there's no Controller/auth layer in
this demo, so no token is needed. Conversation history is kept here,
client-side (mcp_service is stateless). A mutating change (set_velocity/
apply_setting) never applies on its own turn -- the response carries a
`pending_action` instead, and this REPL prompts you to type 'confirm' or
'cancel', mirroring what the real product's chat widget does with its
Confirm/Cancel buttons.

Usage:
  python cli.py                # mcp_service + backend must already be running
  python run_demo.py           # starts both for you, then runs this
"""
import argparse
import os

import requests


def main():
    parser = argparse.ArgumentParser(description="Chat with the ANANTASIM chat demo assistant")
    parser.add_argument("--mcp-service", default=os.getenv("MCP_SERVICE_URL", "http://localhost:9005"))
    parser.add_argument("--project-id", default=os.getenv("DEMO_PROJECT_ID", "demo-project"))
    parser.add_argument("--sim-id", default=os.getenv("DEMO_SIM_ID", "demo-sim"))
    parser.add_argument("--user-id", default=os.getenv("DEMO_USER_ID", "demo-user"))
    args = parser.parse_args()

    try:
        health = requests.get(f"{args.mcp_service}/health", timeout=5).json()
        llm_mode = {
            "real": "a real LLM",
            "fake": "the built-in offline demo brain (no LLM reachable)",
        }.get(health.get("llm"), "an unknown backend")
    except requests.RequestException as exc:
        print(f"[couldn't reach mcp_service at {args.mcp_service}: {exc}]")
        print("Is it running? See README.md, or just run `python run_demo.py` instead.")
        return

    history = []
    pending_action = None
    print("ANANTASIM chat demo. Type your request ('/quit' to exit).")
    print(f"[using {llm_mode}]")

    while True:
        try:
            message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not message:
            continue
        if message in ("/quit", "/exit"):
            break

        if pending_action is not None:
            if message.lower() == "confirm":
                payload = {
                    "project_id": args.project_id,
                    "sim_id": args.sim_id,
                    "user_id": args.user_id,
                    "message": "",
                    "history": [],
                    "confirm": pending_action,
                }
                pending_action = None
            elif message.lower() == "cancel":
                print("[cancelled -- no changes were made]")
                pending_action = None
                continue
            else:
                print("[a change is pending -- type 'confirm' or 'cancel']")
                continue
        else:
            payload = {
                "project_id": args.project_id,
                "sim_id": args.sim_id,
                "user_id": args.user_id,
                "message": message,
                "history": history,
            }

        try:
            response = requests.post(f"{args.mcp_service}/chat", json=payload, timeout=180)
        except requests.RequestException as exc:
            print(f"[connection error] {exc}")
            continue

        if response.status_code != 200:
            print(f"[error {response.status_code}] {response.text}")
            continue

        reply = response.json()
        print(reply["message"])

        if reply.get("pending_action"):
            pending_action = reply["pending_action"]
            print("[type 'confirm' to apply this change, or 'cancel' to drop it]")
        elif reply.get("applied"):
            print(f"[change applied: {reply.get('detail')}]")

        if "confirm" not in payload:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply["message"]})


if __name__ == "__main__":
    main()
