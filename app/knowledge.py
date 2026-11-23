"""Carga la base de conocimiento (perfil.yaml) y arma el prompt del sistema.

Decisión de diseño: sin RAG. El perfil completo cabe holgadamente en el contexto
del modelo, así que se envía entero en cada solicitud. Menos piezas móviles,
cero riesgo de recuperar el fragmento equivocado.
"""
import re
from pathlib import Path

import yaml

PHONE_PLACEHOLDER = "{{CONTACT_PHONE}}"
PERFIL_PLACEHOLDER = "{{PERFIL_YAML}}"
PHONE_FALLBACK = "No publicado; contactar por correo o LinkedIn"


def _read(knowledge_dir: str, name: str) -> str:
    return (Path(knowledge_dir) / name).read_text(encoding="utf-8")


def load_profile(knowledge_dir: str, phone: str) -> dict:
    """Lee perfil.yaml e inyecta el teléfono (que nunca vive en el repo)."""
    raw = _read(knowledge_dir, "perfil.yaml")
    if PHONE_PLACEHOLDER not in raw:
        raise ValueError("perfil.yaml debe contener el marcador {{CONTACT_PHONE}}")
    raw = raw.replace(PHONE_PLACEHOLDER, phone.strip() or PHONE_FALLBACK)
    data = yaml.safe_load(raw)
    for key in ("identidad", "experiencia", "proyectos", "habilidades"):
        if key not in data:
            raise ValueError(f"perfil.yaml no tiene la sección obligatoria '{key}'")
    return data


def _section(md: str, heading: str, next_heading: str | None = None) -> str:
    start = md.index(heading) + len(heading)
    end = md.index(next_heading, start) if next_heading else len(md)
    return md[start:end]


def _code_block(text: str) -> str:
    match = re.search(r"```\s*\n(.*?)```", text, re.S)
    return match.group(1).strip() if match else ""


def build_system_prompt(knowledge_dir: str, phone: str) -> str:
    md = _read(knowledge_dir, "system_prompt.md")
    prompt = _section(md, "## PROMPT\n", "## PROMPT SUGGESTIONS").strip().rstrip("-").strip()
    if PERFIL_PLACEHOLDER not in prompt:
        raise ValueError("system_prompt.md debe contener el marcador {{PERFIL_YAML}}")
    profile = load_profile(knowledge_dir, phone)
    profile_yaml = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False, width=1000)
    return prompt.replace(PERFIL_PLACEHOLDER, profile_yaml.strip())


def load_prompt_suggestions(knowledge_dir: str) -> list[str]:
    md = _read(knowledge_dir, "system_prompt.md")
    block = _code_block(_section(md, "## PROMPT SUGGESTIONS", "## DESCRIPCIÓN"))
    return [line.strip() for line in block.splitlines() if line.strip()][:8]


def load_description(knowledge_dir: str) -> str:
    md = _read(knowledge_dir, "system_prompt.md")
    return _code_block(_section(md, "## DESCRIPCIÓN"))
