"""Traducción entre el formato Open Responses y turnos internos (user/model).

Referencia: https://www.openresponses.org/specification
"""
import time
import uuid

TEXT_PART_TYPES = {"input_text", "output_text", "text"}
ROLE_MAP = {"user": "user", "assistant": "model"}
INSTRUCTION_ROLES = {"system", "developer"}


class InvalidRequest(Exception):
    def __init__(self, message: str, param: str | None = None):
        super().__init__(message)
        self.message = message
        self.param = param


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict) and part.get("type", "input_text") in TEXT_PART_TYPES:
                texts.append(part.get("text", ""))
            # input_image / input_file u otros tipos se ignoran: el agente solo usa texto
        return "\n".join(t for t in texts if t)
    return ""


def parse_input(body: dict, max_turns: int, max_input_chars: int):
    """Devuelve (turnos, instrucciones_extra).

    turnos: lista de (rol, texto) con rol en {"user", "model"}.
    La plataforma reproduce la transcripción completa (modo sin estado),
    por lo que no se necesita almacenamiento de conversaciones.
    """
    raw = body.get("input")
    extra: list[str] = []
    if isinstance(body.get("instructions"), str) and body["instructions"].strip():
        extra.append(body["instructions"].strip())

    turns: list[tuple[str, str]] = []
    if isinstance(raw, str):
        if raw.strip():
            turns.append(("user", raw.strip()))
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or item.get("type", "message") != "message":
                continue
            role = item.get("role")
            text = _content_to_text(item.get("content")).strip()
            if not text:
                continue
            if role in INSTRUCTION_ROLES:
                extra.append(text)
            elif role in ROLE_MAP:
                turns.append((ROLE_MAP[role], text))
    else:
        raise InvalidRequest("'input' debe ser texto o una lista de mensajes.", "input")

    if not turns:
        raise InvalidRequest("La conversación no contiene mensajes de texto.", "input")
    if turns[-1][0] != "user":
        raise InvalidRequest("El último mensaje debe ser del usuario.", "input")
    if len(turns[-1][1]) > max_input_chars:
        raise InvalidRequest(
            f"El mensaje excede el máximo de {max_input_chars} caracteres.", "input"
        )

    turns = turns[-max_turns:]
    while turns and turns[0][0] != "user":   # el contexto siempre inicia con el usuario
        turns.pop(0)
    return turns, extra


def output_text_part(text: str) -> dict:
    return {"type": "output_text", "text": text, "annotations": [], "logprobs": []}


def message_item(item_id: str, text: str | None, status: str) -> dict:
    return {
        "id": item_id,
        "type": "message",
        "status": status,
        "role": "assistant",
        "content": [] if text is None else [output_text_part(text)],
    }


def usage_obj(input_tokens: int, output_tokens: int) -> dict:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": input_tokens + output_tokens,
    }


def response_obj(*, resp_id, created_at, model, status, output, usage, body,
                 settings, error=None) -> dict:
    return {
        "id": resp_id,
        "object": "response",
        "created_at": created_at,
        "completed_at": int(time.time()) if status in ("completed", "failed") else None,
        "status": status,
        "incomplete_details": None,
        "model": model,
        "previous_response_id": None,
        "instructions": body.get("instructions"),
        "output": output,
        "error": error,
        "tools": [],
        "tool_choice": "auto",
        "truncation": "auto",
        "parallel_tool_calls": False,
        "text": {"format": {"type": "text"}},
        "top_p": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "top_logprobs": 0,
        "temperature": settings.temperature,
        "reasoning": None,
        "usage": usage,
        "max_output_tokens": settings.max_output_tokens,
        "max_tool_calls": None,
        "store": False,
        "background": False,
        "service_tier": "default",
        "metadata": {},
        "safety_identifier": None,
        "prompt_cache_key": None,
    }


def error_body(err_type: str, message: str, code: str | None = None,
               param: str | None = None) -> dict:
    return {"error": {"type": err_type, "message": message, "code": code, "param": param}}
