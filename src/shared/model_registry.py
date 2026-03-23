from __future__ import annotations

import json
import os
import re
from urllib import error, request

from langchain_core.runnables import RunnableLambda

from shared.schemas import ModelSpec


class ModelRegistry:
    def __init__(self, models: dict[str, ModelSpec]) -> None:
        self.models = models

    def build_runnable(self, model_id: str):
        spec = self.models[model_id]
        if spec.provider == "openai" and os.getenv("OPENAI_API_KEY", "").strip():
            return RunnableLambda(lambda payload: self._invoke_openai(spec, payload))

        def invoke(payload):
            text = self._coerce_payload_to_text(payload, prefer_latest_message=True)
            return f"[{spec.model_name}] {text}"

        return RunnableLambda(invoke)

    def _invoke_openai(self, spec: ModelSpec, payload) -> str:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        text = self._coerce_payload_to_text(payload)
        payload = self._post_openai_response(spec, {"model": spec.model_name, "input": text, **spec.defaults})
        return self._extract_output_text(payload)

    def _post_openai_response(self, spec: ModelSpec, body: dict) -> dict:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=spec.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API error ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc

    def _extract_output_text(self, payload: dict) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        parts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(content.get("text", ""))
        return "\n".join(part for part in parts if part).strip()

    def _coerce_payload_to_text(self, payload, *, prefer_latest_message: bool = False) -> str:
        if isinstance(payload, str):
            return self._extract_user_facing_text(payload, prefer_latest_message=prefer_latest_message)
        if isinstance(payload, dict):
            text = payload.get("input") or payload.get("text") or json.dumps(payload)
            return self._extract_user_facing_text(text, prefer_latest_message=prefer_latest_message)
        if prefer_latest_message and hasattr(payload, "to_messages"):
            messages = payload.to_messages()
            if messages:
                return self._extract_user_facing_text(str(messages[-1].content), prefer_latest_message=True)
        if hasattr(payload, "to_string"):
            return self._extract_user_facing_text(payload.to_string(), prefer_latest_message=prefer_latest_message)
        if hasattr(payload, "to_messages"):
            return self._extract_user_facing_text(
                "\n".join(str(message.content) for message in payload.to_messages()),
                prefer_latest_message=prefer_latest_message,
            )
        return self._extract_user_facing_text(str(payload), prefer_latest_message=prefer_latest_message)

    def _extract_user_facing_text(self, text: str, *, prefer_latest_message: bool = False) -> str:
        value = str(text or "")
        if not prefer_latest_message:
            return value
        for pattern in [r"Current Input:\s*(.*)$", r"User/Input:\s*(.*)$"]:
            match = re.search(pattern, value, flags=re.DOTALL)
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    return extracted
        return value
