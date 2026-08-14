"""A tiny rule-based stand-in for a real tool-calling LLM.

Used automatically (see factory.py) when no OpenAI-compatible endpoint
(Ollama/LM Studio/OpenAI) is reachable, so this demo runs with zero external
setup. It is NOT a language model -- it does just enough keyword/number
matching on the latest user message (and on tool results already in the
conversation) to walk the same get-context -> propose-change -> (confirm
gate) flow a real model would. Point LLM_BASE_URL at a real server for
genuine free-text understanding; see README.md.
"""
import itertools
import json
import math
import re

from llm.base import LLMProvider, LLMReply, ToolCall

# Excludes a digit immediately preceded by a letter, so a target name like
# "C1"/"C2" isn't mistaken for the numeric value in e.g. "set C1 to 1.5"
# (without the lookbehind, .search() would match the "1" inside "c1" first).
_NUMBER = re.compile(r"(?<![a-zA-Z0-9])-?\d+\.?\d*")


def _last_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


def _mentions_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _first_number(text: str):
    match = _NUMBER.search(text)
    return float(match.group()) if match else None


def _match_target(text: str, targets: list[dict]):
    for t in targets:
        if t["name"].lower() in text:
            return t["name"]
    return None


def _direction_for(context: dict, target: str) -> list[float]:
    for t in context.get("targets", []):
        if t["name"] == target:
            value = t.get("value")
            if isinstance(value, list) and len(value) == 3:
                magnitude = math.sqrt(sum(v * v for v in value))
                if magnitude > 1e-9:
                    return [v / magnitude for v in value]
            break
    return [1.0, 0.0, 0.0]


class FakeLLMProvider(LLMProvider):

    def __init__(self):
        self._ids = itertools.count(1)

    def _tool_call(self, name: str, arguments: dict) -> ToolCall:
        return ToolCall(id=f"fake-{next(self._ids)}", name=name, arguments=arguments)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        last = messages[-1]
        text = _last_user_message(messages).lower()

        if last["role"] == "tool":
            return self._reply_from_tool_result(text, last)

        if "turbulence" in text or _mentions_any(text, ("cmu", "c1", "c2")):
            return LLMReply(tool_calls=[self._tool_call("get_setting_context", {"domain": "turbulence"})])

        if _mentions_any(text, ("velocity", "speed", "m/s", "inlet", "outlet", "internalfield", "wall")):
            return LLMReply(tool_calls=[self._tool_call("get_velocity_context", {})])

        return LLMReply(content=(
            "[offline demo brain] I can check or change the velocity field (U) or turbulence "
            "model coefficients for this simulation -- try 'what's the current inlet velocity?' "
            "or 'set the inlet velocity to 5 m/s'."
        ))

    def _reply_from_tool_result(self, user_text: str, tool_message: dict) -> LLMReply:
        try:
            result = json.loads(tool_message["content"])
        except (json.JSONDecodeError, TypeError):
            result = {}

        number = _first_number(user_text)

        if "targets" in result and "U" in result:  # get_velocity_context result
            if number is None:
                return LLMReply(content=self._describe_velocity(result))
            target = _match_target(user_text, result["targets"]) or "inlet"
            direction = _direction_for(result, target)
            value = [round(d * number, 6) for d in direction]
            return LLMReply(tool_calls=[self._tool_call("set_velocity", {"target": target, "value": value})])

        if result.get("domain") == "turbulence":
            targets = result.get("targets", [])
            target = _match_target(user_text, targets)
            if number is None or target is None:
                return LLMReply(content=self._describe_turbulence(result))
            return LLMReply(tool_calls=[
                self._tool_call("apply_setting", {"domain": "turbulence", "target": target, "value": number})
            ])

        return LLMReply(content=f"[offline demo brain] Here's what I found: {json.dumps(result)}")

    @staticmethod
    def _describe_velocity(context: dict) -> str:
        lines = [f"- {t['name']}: {t.get('type')} {t.get('value')}" for t in context.get("targets", [])]
        return "[offline demo brain] Current velocity (U) configuration:\n" + "\n".join(lines)

    @staticmethod
    def _describe_turbulence(context: dict) -> str:
        model = context.get("model", {})
        lines = [
            f"- {t['name']}: {t['value']}" + (" (default)" if t.get("is_default") else "")
            for t in context.get("targets", [])
        ]
        return (
            f"[offline demo brain] Active turbulence model: {model.get('name')} ({model.get('type')})\n"
            + "\n".join(lines)
        )
