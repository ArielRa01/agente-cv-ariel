"""Cliente de Gemini (SDK oficial google-genai) con salida normal, streaming y
resiliencia ante saturación del proveedor:

1. Recorre una cadena de modelos (principal + respaldos) ante errores 429/5xx.
2. Si toda la cadena falla, espera brevemente y la recorre otra vez.
3. Registra cada modelo intentado para observabilidad.
"""
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from .config import Settings

FALLBACK_TEXT = (
    "No pude generar una respuesta en este momento. "
    "¿Puedes reformular tu pregunta sobre la trayectoria de Ariel?"
)
RETRYABLE_CODES = {429, 500, 502, 503, 504}


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str = ""
    attempts: list[str] = field(default_factory=list)


class LLMUnavailable(RuntimeError):
    """Todos los modelos de la cadena fallaron con errores recuperables."""

    def __init__(self, attempts: list[str], last: Exception):
        super().__init__(f"Modelos no disponibles tras {len(attempts)} intentos: {last}")
        self.attempts = attempts
        self.last = last


def _usage(meta) -> tuple[int, int]:
    if meta is None:
        return 0, 0
    out = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)
    return meta.prompt_token_count or 0, out


def is_retryable(exc: Exception) -> bool:
    """Errores del proveedor que justifican intentar con el siguiente modelo."""
    return getattr(exc, "code", None) in RETRYABLE_CODES


class GeminiLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.models = settings.model_chain
        self._client = None   # se crea al primer uso: permite importar la app sin llave (pruebas)

    @property
    def client(self):
        if self._client is None:
            if not self.settings.gemini_api_key:
                raise RuntimeError("Falta la variable GEMINI_API_KEY")
            from google import genai
            from google.genai import types
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key,
                http_options=types.HttpOptions(api_version=self.settings.gemini_api_version),
            )
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

    def _plan(self):
        """Secuencia de (vuelta, modelo) a intentar."""
        for p in range(max(1, self.settings.retry_passes)):
            for model in self.models:
                yield p, model

    async def generate(self, system: str, turns) -> LLMResult:
        attempts: list[str] = []
        last_exc: Exception | None = None
        current_pass = 0
        for p, model in self._plan():
            if p != current_pass:
                current_pass = p
                await asyncio.sleep(self.settings.retry_delay_s)
            attempts.append(model)
            try:
                resp = await self.client.aio.models.generate_content(
                    model=model, contents=self._contents(turns), config=self._config(system))
            except Exception as exc:  # noqa: BLE001
                if not is_retryable(exc):
                    raise
                last_exc = exc
                continue
            tin, tout = _usage(resp.usage_metadata)
            return LLMResult(text=(resp.text or "").strip() or FALLBACK_TEXT,
                             input_tokens=tin, output_tokens=tout, model=model,
                             attempts=attempts)
        raise LLMUnavailable(attempts, last_exc or RuntimeError("Sin modelos configurados"))

    async def stream(self, system: str, turns) -> AsyncIterator[str | LLMResult]:
        """Produce fragmentos de texto (str) y al final un LLMResult con uso de tokens.

        El cambio de modelo solo ocurre si la falla llega ANTES del primer fragmento;
        una vez que el usuario empezó a ver texto, no se mezclan respuestas.
        """
        attempts: list[str] = []
        last_exc: Exception | None = None
        current_pass = 0
        for p, model in self._plan():
            if p != current_pass:
                current_pass = p
                await asyncio.sleep(self.settings.retry_delay_s)
            attempts.append(model)
            meta, parts, started = None, [], False
            try:
                stream = await self.client.aio.models.generate_content_stream(
                    model=model, contents=self._contents(turns), config=self._config(system))
                async for chunk in stream:
                    if chunk.usage_metadata is not None:
                        meta = chunk.usage_metadata
                    if chunk.text:
                        started = True
                        parts.append(chunk.text)
                        yield chunk.text
            except Exception as exc:  # noqa: BLE001
                if started or not is_retryable(exc):
                    raise
                last_exc = exc
                continue
            tin, tout = _usage(meta)
            yield LLMResult(text="".join(parts), input_tokens=tin, output_tokens=tout,
                            model=model, attempts=attempts)
            return
        raise LLMUnavailable(attempts, last_exc or RuntimeError("Sin modelos configurados"))
