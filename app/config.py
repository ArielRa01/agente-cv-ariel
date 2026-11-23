"""Configuración del agente. Todo se lee de variables de entorno (12-factor)."""
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KNOWLEDGE_DIR = str(Path(__file__).resolve().parent.parent / "knowledge")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"     # versión fija: un alias puede cambiar sin aviso
    gemini_fallback_models: str = "gemini-3.8-flash"   # separados por coma; se usan ante 429/5xx
    gemini_api_version: str = "v1beta"
    retry_passes: int = 2             # vueltas completas a la cadena de modelos
    retry_delay_s: float = 0.8        # espera entre vueltas (saturaciones suelen ser breves)
    agent_api_key: str = ""
    contact_phone: str = ""
    agent_name: str = "ariel-cv-agent"
    temperature: float = 0.3
    max_output_tokens: int = 2048
    thinking_level: str = ""          # opcional: "low" reduce latencia en modelos con razonamiento
    max_turns: int = 20               # solo se envían los últimos N turnos al modelo
    max_input_chars: int = 4000       # tope del último mensaje del usuario
    rate_limit_per_minute: int = 20   # por IP
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        return cls(
            gemini_api_key=e("GEMINI_API_KEY", ""),
            gemini_model=e("GEMINI_MODEL", cls.gemini_model),
            gemini_api_version=e("GEMINI_API_VERSION", cls.gemini_api_version),
            gemini_fallback_models=e("GEMINI_FALLBACK_MODELS", cls.gemini_fallback_models),
            retry_passes=int(e("RETRY_PASSES", cls.retry_passes)),
            retry_delay_s=float(e("RETRY_DELAY_S", cls.retry_delay_s)),
            agent_api_key=e("AGENT_API_KEY", ""),
            contact_phone=e("CONTACT_PHONE", ""),
            agent_name=e("AGENT_NAME", cls.agent_name),
            temperature=float(e("TEMPERATURE", cls.temperature)),
            max_output_tokens=int(e("MAX_OUTPUT_TOKENS", cls.max_output_tokens)),
            thinking_level=e("THINKING_LEVEL", ""),
            max_turns=int(e("MAX_TURNS", cls.max_turns)),
            max_input_chars=int(e("MAX_INPUT_CHARS", cls.max_input_chars)),
            rate_limit_per_minute=int(e("RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute)),
            knowledge_dir=e("KNOWLEDGE_DIR", DEFAULT_KNOWLEDGE_DIR),
        )

    @property
    def model_chain(self) -> list[str]:
        """Modelo principal seguido de los de respaldo, sin duplicados."""
        chain = [self.gemini_model] + [m.strip() for m in self.gemini_fallback_models.split(",")]
        return list(dict.fromkeys(m for m in chain if m))
