"""Pruebas del fallback entre modelos (cliente de Gemini simulado)."""
import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.llm import GeminiLLM, LLMResult, LLMUnavailable

SATURADO = errors.ServerError(503, {"error": {"code": 503, "message": "high demand",
                                              "status": "UNAVAILABLE"}})
NO_EXISTE = errors.ClientError(404, {"error": {"code": 404, "message": "not found",
                                               "status": "NOT_FOUND"}})
USAGE = SimpleNamespace(prompt_token_count=100, candidates_token_count=10, thoughts_token_count=0)


class FakeModels:
    def __init__(self, failures: dict):
        self.failures = failures      # modelo -> excepción
        self.calls: list[str] = []

    async def generate_content(self, model, contents, config):
        self.calls.append(model)
        if model in self.failures:
            raise self.failures[model]
        return SimpleNamespace(text=f"respuesta de {model}", usage_metadata=USAGE)

    async def generate_content_stream(self, model, contents, config):
        self.calls.append(model)
        if model in self.failures:
            raise self.failures[model]

        async def gen():
            for piece in ["hola ", "desde ", model]:
                yield SimpleNamespace(text=piece, usage_metadata=None)
            yield SimpleNamespace(text="", usage_metadata=USAGE)
        return gen()


def make_llm(failures):
    llm = GeminiLLM(Settings(gemini_model="m1", gemini_fallback_models="m2,m3", retry_delay_s=0))
    fake = FakeModels(failures)
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=fake))
    return llm, fake


def collect(llm):
    async def run():
        return [c async for c in llm.stream("sys", [("user", "hola")])]
    return asyncio.run(run())


def test_cadena_de_modelos_sin_duplicados():
    s = Settings(gemini_model="a", gemini_fallback_models="b, a ,c,")
    assert s.model_chain == ["a", "b", "c"]


def test_generate_usa_respaldo_ante_503():
    llm, fake = make_llm({"m1": SATURADO})
    result = asyncio.run(llm.generate("sys", [("user", "hola")]))
    assert result.model == "m2" and fake.calls == ["m1", "m2"]
    assert result.attempts == ["m1", "m2"]


def test_generate_no_reintenta_errores_no_recuperables():
    llm, fake = make_llm({"m1": NO_EXISTE})
    with pytest.raises(errors.ClientError):
        asyncio.run(llm.generate("sys", [("user", "hola")]))
    assert fake.calls == ["m1"]


def test_generate_hace_dos_vueltas_y_reporta_intentos():
    llm, fake = make_llm({"m1": SATURADO, "m2": SATURADO, "m3": SATURADO})
    with pytest.raises(LLMUnavailable) as info:
        asyncio.run(llm.generate("sys", [("user", "hola")]))
    assert info.value.attempts == ["m1", "m2", "m3", "m1", "m2", "m3"]


def test_stream_usa_respaldo_ante_503():
    llm, fake = make_llm({"m1": SATURADO})
    chunks = collect(llm)
    assert "".join(c for c in chunks if isinstance(c, str)) == "hola desde m2"
    assert isinstance(chunks[-1], LLMResult) and chunks[-1].model == "m2"
    assert chunks[-1].input_tokens == 100 and fake.calls == ["m1", "m2"]
