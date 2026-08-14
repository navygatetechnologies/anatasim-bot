import json

from openai import NOT_GIVEN, AsyncOpenAI

from llm.base import LLMProvider, LLMReply, ToolCall


class OpenAICompatProvider(LLMProvider):
    """Client for any OpenAI-compatible chat-completions server:
    Ollama (/v1), LM Studio, llama.cpp server, or OpenAI itself."""

    def __init__(self, base_url: str, model: str, api_key: str):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or NOT_GIVEN,
        )
        message = response.choices[0].message

        tool_calls = []
        for tc in message.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                # Small local models occasionally emit broken JSON; an empty
                # dict makes the tool fail validation, and that error text
                # goes back to the model so it can retry.
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=arguments)
            )

        return LLMReply(content=message.content, tool_calls=tool_calls)
