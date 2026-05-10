from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass

from symkern.intent_contract import build_translation_instructions


@dataclass(slots=True)
class TranslationEnvelope:
    payload: dict[str, object]
    translator: str


class TranslatorAdapter:
    def translate(self, prompt: str) -> TranslationEnvelope:
        raise NotImplementedError

    def repair(self, prompt: str, invalid_payload: dict[str, object] | None, error_message: str) -> TranslationEnvelope:
        raise NotImplementedError


def _decode_json_response(response_payload: dict[str, object], response_key: str) -> dict[str, object]:
    translated = response_payload.get(response_key, response_payload)
    if isinstance(translated, list):
        translated = translated[0] if translated else {}
    if isinstance(translated, str):
        translated = json.loads(translated)
    if not isinstance(translated, dict):
        raise ValueError("Translator returned a non-object payload")
    return dict(translated)


def _http_post_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass(slots=True)
class OllamaTranslatorAdapter(TranslatorAdapter):
    model: str
    endpoint: str = "http://localhost:11434/api/generate"
    temperature: float = 0.0

    def translate(self, prompt: str) -> TranslationEnvelope:
        request_payload = {
            "model": self.model,
            "prompt": f"{build_translation_instructions()}\n\nUser request: {prompt}\n",
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
        }
        response_payload = _http_post_json(self.endpoint, request_payload)
        return TranslationEnvelope(payload=_decode_json_response(response_payload, "response"), translator=f"ollama:{self.model}")

    def repair(self, prompt: str, invalid_payload: dict[str, object] | None, error_message: str) -> TranslationEnvelope:
        repair_prompt = (
            f"{build_translation_instructions()}\n\n"
            f"The previous translation was invalid for the following reason: {error_message}.\n"
            f"Previous payload: {json.dumps(invalid_payload or {}, sort_keys=True)}\n"
            f"User request: {prompt}\n"
            "Common failure to avoid: values like \"{'goal': '...'}\" or \"{'sink': 'stdout'}\" inside list fields are invalid.\n"
            "Rewrite every list field as an array of plain strings and keep structured data only inside the state object.\n"
            "Return only corrected JSON."
        )
        response_payload = _http_post_json(
            self.endpoint,
            {
                "model": self.model,
                "prompt": repair_prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": self.temperature},
            },
        )
        return TranslationEnvelope(payload=_decode_json_response(response_payload, "response"), translator=f"ollama:{self.model}:repair")


@dataclass(slots=True)
class OpenAICompatibleTranslatorAdapter(TranslatorAdapter):
    model: str
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    api_key: str = ""
    temperature: float = 0.0

    def translate(self, prompt: str) -> TranslationEnvelope:
        response_payload = _http_post_json(
            self.endpoint,
            {
                "model": self.model,
                "temperature": self.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": build_translation_instructions()},
                    {"role": "user", "content": prompt},
                ],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        content = response_payload["choices"][0]["message"]["content"]
        return TranslationEnvelope(payload=_decode_json_response({"response": content}, "response"), translator=f"openai-compatible:{self.model}")

    def repair(self, prompt: str, invalid_payload: dict[str, object] | None, error_message: str) -> TranslationEnvelope:
        response_payload = _http_post_json(
            self.endpoint,
            {
                "model": self.model,
                "temperature": self.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": build_translation_instructions()},
                    {
                        "role": "user",
                        "content": (
                            f"Repair the invalid Symkern intent JSON for this request. Error: {error_message}. "
                            f"Previous payload: {json.dumps(invalid_payload or {}, sort_keys=True)}. "
                            f"User request: {prompt}"
                        ),
                    },
                ],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        content = response_payload["choices"][0]["message"]["content"]
        return TranslationEnvelope(payload=_decode_json_response({"response": content}, "response"), translator=f"openai-compatible:{self.model}:repair")


@dataclass(slots=True)
class AnthropicTranslatorAdapter(TranslatorAdapter):
    model: str
    api_key: str = ""
    endpoint: str = "https://api.anthropic.com/v1/messages"
    temperature: float = 0.0

    def translate(self, prompt: str) -> TranslationEnvelope:
        response_payload = _http_post_json(
            self.endpoint,
            {
                "model": self.model,
                "max_tokens": 800,
                "temperature": self.temperature,
                "system": build_translation_instructions(),
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        content = "".join(block.get("text", "") for block in list(response_payload.get("content", [])))
        return TranslationEnvelope(payload=_decode_json_response({"response": content}, "response"), translator=f"anthropic:{self.model}")

    def repair(self, prompt: str, invalid_payload: dict[str, object] | None, error_message: str) -> TranslationEnvelope:
        response_payload = _http_post_json(
            self.endpoint,
            {
                "model": self.model,
                "max_tokens": 800,
                "temperature": self.temperature,
                "system": build_translation_instructions(),
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Repair the invalid Symkern intent JSON for this request. Error: {error_message}. "
                            f"Previous payload: {json.dumps(invalid_payload or {}, sort_keys=True)}. "
                            f"User request: {prompt}"
                        ),
                    }
                ],
            },
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
        )
        content = "".join(block.get("text", "") for block in list(response_payload.get("content", [])))
        return TranslationEnvelope(payload=_decode_json_response({"response": content}, "response"), translator=f"anthropic:{self.model}:repair")


def resolve_api_key(explicit_api_key: str | None = None, api_key_env: str | None = None) -> str:
    if explicit_api_key:
        return explicit_api_key
    if api_key_env:
        return os.environ.get(api_key_env, "")
    return ""