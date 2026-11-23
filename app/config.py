"""Configuración del agente. Todo se lee de variables de entorno (12-factor)."""
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KNOWLEDGE_DIR = str(Path(__file__).resolve().parent.parent / "knowledge")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
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
