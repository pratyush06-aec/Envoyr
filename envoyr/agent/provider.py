"""Zero-dependency LLM Provider Client for Envoyr.

Built strictly using Python standard library (urllib.request, json).
Supports:
1. Google Gemini (via GEMINI_API_KEY)
2. OpenAI / OpenRouter / Ollama (via OPENAI_API_KEY and optional OPENAI_BASE_URL)
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


try:
    import neatlogs
    HAS_NEATLOGS = True
except ImportError:
    neatlogs = None  # type: ignore
    HAS_NEATLOGS = False


# Groq model alias mapping (translates friendly names to Groq API identifiers)
GROQ_MODEL_ALIASES: dict[str, str] = {
    "gpt-oss": "openai/gpt-oss-120b",
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "gpt-oss-20b": "openai/gpt-oss-20b",
}


class LLMClient:
    """Lightweight REST client for LLM providers without third-party dependencies."""

    def __init__(
        self,
        gemini_api_key: str | None = None,
        groq_api_key: str | None = None,
        openai_api_key: str | None = None,
        openai_base_url: str | None = None,
        openai_model: str | None = None,
    ):
        self.gemini_api_key = gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY")
        self.groq_api_key = groq_api_key if groq_api_key is not None else os.getenv("GROQ_API_KEY")
        self.openai_api_key = openai_api_key if openai_api_key is not None else os.getenv("OPENAI_API_KEY")

        # Groq endpoint defaults (ultra-fast inference, gpt-oss default)
        self.groq_base_url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self.groq_model = os.getenv("GROQ_MODEL", "gpt-oss")

        # OpenAI / generic OpenAI-compatible endpoint defaults
        self.openai_base_url = openai_base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        self.openai_model = openai_model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @property
    def is_configured(self) -> bool:
        """Check if any LLM API key is present."""
        return bool(self.groq_api_key or self.gemini_api_key or self.openai_api_key)

    @property
    def provider_name(self) -> str:
        if self.groq_api_key:
            return "groq"
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return "none"

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 20.0,
    ) -> str:
        """Send prompt to configured LLM provider and return generated text."""
        if self.groq_api_key:
            return self._call_openai_compatible(
                api_key=self.groq_api_key,
                base_url=self.groq_base_url,
                model=self.groq_model,
                prompt=prompt,
                system_prompt=system_prompt,
                timeout=timeout,
                provider_label="Groq",
            )
        if self.gemini_api_key:
            return self._call_gemini(prompt, system_prompt=system_prompt, timeout=timeout)
        if self.openai_api_key:
            return self._call_openai_compatible(
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                model=self.openai_model,
                prompt=prompt,
                system_prompt=system_prompt,
                timeout=timeout,
                provider_label="OpenAI",
            )
        raise RuntimeError(
            "No LLM API key configured. Please set GROQ_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in .env.local"
        )

    def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 20.0,
    ) -> dict[str, Any] | None:
        """Generate response and extract parsed JSON object."""
        raw_text = self.generate(prompt, system_prompt=system_prompt, timeout=timeout)
        return self._extract_json(raw_text)

    def _call_gemini(
        self, prompt: str, system_prompt: str | None = None, timeout: float = 20.0
    ) -> str:
        """Call Google Gemini generateContent endpoint with Neatlogs LLM span tracing."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
        )
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"Instructions:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow your instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Envoyr/1.0",
            },
            method="POST",
        )

        def _do_call() -> str:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                    return ""
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Gemini API error ({e.code}): {error_body}") from e
            except Exception as e:
                raise RuntimeError(f"Gemini network error: {str(e)}") from e

        if HAS_NEATLOGS and neatlogs is not None:
            try:
                with neatlogs.trace("gemini.generateContent", kind="LLM") as span:
                    span.set_attribute("gen_ai.system", "gemini")
                    span.set_attribute("gen_ai.request.model", "gemini-2.0-flash")
                    span.set_attribute("gen_ai.prompt", prompt[:2000] if prompt else "")
                    res = _do_call()
                    span.set_attribute("gen_ai.completion", res[:2000] if res else "")
                    return res
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    raise
                return _do_call()
        return _do_call()

    def _call_openai(
        self, prompt: str, system_prompt: str | None = None, timeout: float = 20.0
    ) -> str:
        """Backward-compatible OpenAI caller."""
        return self._call_openai_compatible(
            api_key=self.openai_api_key or "",
            base_url=self.openai_base_url,
            model=self.openai_model,
            prompt=prompt,
            system_prompt=system_prompt,
            timeout=timeout,
            provider_label="OpenAI",
        )

    def _call_openai_compatible(
        self,
        api_key: str,
        base_url: str,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 20.0,
        provider_label: str = "OpenAI",
    ) -> str:
        """Call OpenAI-compatible chat completions endpoint (supports OpenAI, Groq, OpenRouter, Ollama)."""
        base = base_url.rstrip("/")
        url = f"{base}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Resolve model aliases if calling Groq (e.g. gpt-oss -> openai/gpt-oss-120b)
        model_id = GROQ_MODEL_ALIASES.get(model, model) if provider_label == "Groq" else model

        body = {
            "model": model_id,
            "messages": messages,
            "temperature": 0.2,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Envoyr/1.0",
            },
            method="POST",
        )

        def _do_call() -> str:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        return choices[0]["message"].get("content", "")
                    return ""
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"{provider_label} API error ({e.code}): {error_body}") from e
            except Exception as e:
                raise RuntimeError(f"{provider_label} network error: {str(e)}") from e

        if HAS_NEATLOGS and neatlogs is not None:
            span_name = f"{provider_label.lower()}.chat.completions"
            try:
                with neatlogs.trace(span_name, kind="LLM") as span:
                    span.set_attribute("gen_ai.system", provider_label.lower())
                    span.set_attribute("gen_ai.request.model", model_id)
                    span.set_attribute("gen_ai.prompt", prompt[:2000] if prompt else "")
                    res = _do_call()
                    span.set_attribute("gen_ai.completion", res[:2000] if res else "")
                    return res
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    raise
                return _do_call()
        return _do_call()

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract JSON from raw text, removing markdown code fences if present."""
        cleaned = text.strip()
        # Strip ```json ... ``` or ``` ... ```
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback: search for first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    return None
            return None
