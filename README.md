# Agente de CV — Ariel Ramos Jiménez

Agente conversacional que presenta la trayectoria profesional de Ariel Ramos (Senior Data & AI Manager) mediante un endpoint compatible con **[Open Responses](https://www.openresponses.org/)**, desplegado en **Google Cloud Run** y potenciado por **Gemini**.

> README completo (arquitectura, decisiones técnicas, evaluación y operación) en la Fase 4.

## Estructura
```
app/          API FastAPI: endpoint Open Responses, streaming SSE, auth, rate limit, tarjeta A2A
knowledge/    perfil.yaml (base de conocimiento curada) · system_prompt.md (reglas y guardrails)
tests/        30 pruebas automatizadas con el modelo simulado
scripts/      smoke_test.sh para validar un despliegue
```

## Endpoints
| Método | Ruta | Uso |
|---|---|---|
| POST | `/v1/responses` | Open Responses (JSON o `stream: true` con SSE) |
| GET | `/.well-known/agent-card.json` | Tarjeta de agente A2A |
| GET | `/health` | Salud del servicio |

## Pruebas locales
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```
