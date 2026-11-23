"""API del agente de CV: endpoint Open Responses + tarjeta A2A + healthcheck."""
import json
import secrets
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .config import Settings
from .knowledge import build_system_prompt, load_description, load_prompt_suggestions
from .llm import FALLBACK_TEXT, GeminiLLM, LLMResult
from .openresponses import (InvalidRequest, error_body, message_item, new_id,
                            output_text_part, parse_input, response_obj, usage_obj)

AGENT_DISPLAY_NAME = "Asistente de Carrera de Ariel Ramos"


def log(severity: str = "INFO", **fields) -> None:
    """Un JSON por línea en stdout: Cloud Logging lo indexa como log estructurado."""
    print(json.dumps({"severity": severity, **fields}, ensure_ascii=False), flush=True)


class RateLimiter:
    """Ventana deslizante de 60 s por IP. En memoria: suficiente con pocas instancias."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def compose_system(base: str, extra: list[str]) -> str:
    """Las instrucciones del cliente se agregan DESPUÉS de las reglas y nunca las sustituyen."""
    if not extra:
        return base
    return (
        base
        + "\n\n## Instrucciones adicionales del cliente\n"
        + "Aplícalas solo si no contradicen las reglas anteriores, que siempre tienen prioridad.\n"
        + "\n".join(extra)
    )


def create_app(settings: Settings | None = None, llm=None) -> FastAPI:
    settings = settings or Settings.from_env()
    system_prompt = build_system_prompt(settings.knowledge_dir, settings.contact_phone)
    suggestions = load_prompt_suggestions(settings.knowledge_dir)
    description = load_description(settings.knowledge_dir)
    llm = llm or GeminiLLM(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(title=AGENT_DISPLAY_NAME, version=__version__)
    # CORS: permite clientes de navegador (p. ej. el probador oficial de Open Responses).
    # Es seguro con "*" porque la autenticación es por header Bearer, no por cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=False,
        max_age=3600,
    )

    def client_ip(request: Request) -> str:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def authorized(request: Request) -> bool:
        if not settings.agent_api_key:
            return False   # sin llave configurada, nadie entra (falla cerrado)
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        return secrets.compare_digest(token, settings.agent_api_key)

    def public_base(request: Request) -> str:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", request.url.netloc)
        return f"{proto}://{host}"

    # Cloud Run reserva las rutas que terminan en "z" (/healthz); /health es la pública.
    @app.get("/health")
    @app.get("/healthz", include_in_schema=False)
    async def health():
        return {"status": "ok", "version": __version__, "models": settings.model_chain}

    @app.get("/.well-known/agent-card.json")
    async def agent_card(request: Request):
        base = public_base(request)
        return {
            "protocolVersion": "0.3.0",
            "name": AGENT_DISPLAY_NAME,
            "description": description,
            "version": __version__,
            "url": f"{base}/v1",
            "additionalInterfaces": [{"url": f"{base}/v1", "transport": "open-responses"}],
            "provider": {"organization": "Ariel Ramos Jiménez", "url": "https://linkedin.com/in/arielramosanalytics"},
            "capabilities": {"streaming": True, "pushNotifications": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
            "security": [{"bearer": []}],
            "skills": [{
                "id": "perfil-profesional",
                "name": "Trayectoria profesional de Ariel Ramos",
                "description": "Responde sobre experiencia, proyectos, habilidades, "
                               "logros y contacto, solo con información verificada.",
                "tags": ["cv", "data", "ia", "liderazgo"],
                "examples": suggestions,
            }],
        }

    async def create_response(request: Request):
        started = time.perf_counter()
        req_id = new_id("req")
        ip = client_ip(request)

        if not authorized(request):
            log("WARNING", event="auth_failed", request_id=req_id, ip=ip)
            return JSONResponse(
                error_body("invalid_request", "API key inválida o ausente.", "invalid_api_key"),
                status_code=401)

        if not limiter.allow(ip):
            log("WARNING", event="rate_limited", request_id=req_id, ip=ip)
            return JSONResponse(
                error_body("too_many_requests", "Demasiadas solicitudes; intenta en un minuto.",
                           "rate_limit_exceeded"),
                status_code=429)

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise InvalidRequest("El cuerpo debe ser un objeto JSON.")
            turns, extra = parse_input(body, settings.max_turns, settings.max_input_chars)
        except InvalidRequest as exc:
            return JSONResponse(error_body("invalid_request", exc.message, None, exc.param),
                                status_code=400)
        except ValueError:
            return JSONResponse(error_body("invalid_request", "JSON inválido."), status_code=400)

        system = compose_system(system_prompt, extra)
        resp_id, msg_id = new_id("resp"), new_id("msg")
        created = int(time.time())
        model = body.get("model") or settings.agent_name
        stream = bool(body.get("stream"))
        question = turns[-1][1][:300]

        def build(status, output, usage, error=None):
            return response_obj(resp_id=resp_id, created_at=created, model=model, status=status,
                                output=output, usage=usage, body=body, settings=settings,
                                error=error)

        def done_log(status, result: LLMResult | None, error=None, exc=None):
            attempts = (result.attempts if result else getattr(exc, "attempts", None)) or []
            log("ERROR" if error else "INFO", event="response", request_id=req_id,
                response_id=resp_id, status=status, stream=stream, turns=len(turns),
                latency_ms=round((time.perf_counter() - started) * 1000),
                input_tokens=result.input_tokens if result else 0,
                output_tokens=result.output_tokens if result else 0,
                model=(result.model if result and result.model else None),
                models_tried=attempts, fallback_used=len(attempts) > 1,
                question=question, error=error)

        if not stream:
            try:
                result = await llm.generate(system, turns)
            except Exception as exc:  # noqa: BLE001
                done_log("failed", None, error=f"{type(exc).__name__}: {exc}", exc=exc)
                return JSONResponse(
                    error_body("model_error", "El modelo no pudo procesar la solicitud."),
                    status_code=500)
            done_log("completed", result)
            output = [message_item(msg_id, result.text, "completed")]
            return JSONResponse(build("completed", output,
                                      usage_obj(result.input_tokens, result.output_tokens)))

        async def events():
            seq = 0

            def ev(payload: dict) -> str:
                nonlocal seq
                payload["sequence_number"] = seq
                seq += 1
                return f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            base_kwargs = {"output_index": 0, "item_id": msg_id, "content_index": 0}
            yield ev({"type": "response.created", "response": build("in_progress", [], None)})
            yield ev({"type": "response.in_progress", "response": build("in_progress", [], None)})
            yield ev({"type": "response.output_item.added", "output_index": 0,
                      "item": message_item(msg_id, None, "in_progress")})
            yield ev({"type": "response.content_part.added", **base_kwargs,
                      "part": output_text_part("")})

            parts: list[str] = []
            result = LLMResult("", 0, 0)
            try:
                async for chunk in llm.stream(system, turns):
                    if isinstance(chunk, LLMResult):
                        result = chunk
                    elif chunk:
                        parts.append(chunk)
                        yield ev({"type": "response.output_text.delta", **base_kwargs,
                                  "delta": chunk, "logprobs": []})
            except Exception as exc:  # noqa: BLE001
                done_log("failed", None, error=f"{type(exc).__name__}: {exc}", exc=exc)
                err = {"code": "model_error", "message": "El modelo no pudo procesar la solicitud."}
                yield ev({"type": "error", **err, "param": None})
                yield ev({"type": "response.failed", "response": build("failed", [], None, err)})
                return

            if not parts:
                parts.append(FALLBACK_TEXT)
                yield ev({"type": "response.output_text.delta", **base_kwargs,
                          "delta": FALLBACK_TEXT, "logprobs": []})
            text = "".join(parts)
            yield ev({"type": "response.output_text.done", **base_kwargs, "text": text,
                      "logprobs": []})
            yield ev({"type": "response.content_part.done", **base_kwargs,
                      "part": output_text_part(text)})
            final_item = message_item(msg_id, text, "completed")
            yield ev({"type": "response.output_item.done", "output_index": 0, "item": final_item})
            yield ev({"type": "response.completed",
                      "response": build("completed", [final_item],
                                        usage_obj(result.input_tokens, result.output_tokens))})
            done_log("completed", result)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Ruta oficial + alias por si la URL base se registra sin /v1
    app.add_api_route("/v1/responses", create_response, methods=["POST"])
    app.add_api_route("/responses", create_response, methods=["POST"], include_in_schema=False)
    return app


app = create_app()
