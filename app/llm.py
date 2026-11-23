"""Cliente de Gemini (SDK oficial google-genai), con salida normal y en streaming."""
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .config import Settings

FALLBACK_TEXT = (
    "No pude generar una respuesta en este momento. "
    "¿Puedes reformular tu pregunta sobre la trayectoria de Ariel?"
)


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int


def _usage(meta) -> tuple[int, int]:
    if meta is None:
        return 0, 0
    out = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
    return meta.prompt_token_count or 0, out


class GeminiLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None   # se crea al primer uso: permite importar la app sin llave (pruebas)

    @property
    def client(self):
        if self._client is None:
            if not self.settings.gemini_api_key:
                raise RuntimeError("Falta la variable GEMINI_API_KEY")
            from google import genai
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def _config(self, system: str):
        from google.genai import types
        kwargs = dict(
            system_instruction=system,
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
        )
        if self.settings.thinking_level:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=self.settings.thinking_level
            )
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _contents(turns):
        from google.genai import types
        return [types.Content(role=r, parts=[types.Part(text=t)]) for r, t in turns]

    async def generate(self, system: str, turns) -> LLMResult:
        resp = await self.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=self._contents(turns),
            config=self._config(system),
        )
        tin, tout = _usage(resp.usage_metadata)
        return LLMResult(text=(resp.text or "").strip() or FALLBACK_TEXT,
                         input_tokens=tin, output_tokens=tout)

    async def stream(self, system: str, turns) -> AsyncIterator[str | LLMResult]:
        """Produce fragmentos de texto (str) y al final un LLMResult con el uso de tokens."""
        meta, parts = None, []
        stream = await self.client.aio.models.generate_content_stream(
            model=self.settings.gemini_model,
            contents=self._contents(turns),
            config=self._config(system),
        )
        async for chunk in stream:
            if chunk.usage_metadata is not None:
                meta = chunk.usage_metadata
            if chunk.text:
                parts.append(chunk.text)
                yield chunk.text
        tin, tout = _usage(meta)
        yield LLMResult(text="".join(parts), input_tokens=tin, output_tokens=tout)
