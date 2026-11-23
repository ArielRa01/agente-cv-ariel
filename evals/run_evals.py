"""Corre la suite golden contra un endpoint Open Responses y genera un reporte.

Uso:
  BASE_URL=https://...run.app AGENT_API_KEY=... python evals/run_evals.py --label antes
Salida: evals/results/<label>.md y evals/results/<label>.json
"""
import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def ask(base_url: str, key: str, question: str, retries: int = 2) -> tuple[str, float, dict]:
    body = json.dumps({"model": "ariel-cv-agent", "input": question}).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{base_url}/v1/responses", data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            latency = time.perf_counter() - t
            return data["output"][0]["content"][0]["text"], latency, data.get("usage") or {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            return f"[HTTP {e.code}] {e.read().decode()[:200]}", time.perf_counter() - t, {}


def check(case: dict, answer: str) -> list[str]:
    a = norm(answer)
    fails = []
    if case.get("incluye_alguno") and not any(norm(x) in a for x in case["incluye_alguno"]):
        fails.append(f"falta alguno de {case['incluye_alguno']}")
    for x in case.get("incluye_todos", []):
        if norm(x) not in a:
            fails.append(f"falta '{x}'")
    for x in case.get("excluye", []):
        if norm(x) in a:
            fails.append(f"contiene prohibido '{x}'")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default=datetime.now().strftime("%Y%m%d-%H%M"))
    ap.add_argument("--pause", type=float, default=1.0, help="segundos entre casos")
    args = ap.parse_args()
    base, key = os.environ["BASE_URL"].rstrip("/"), os.environ["AGENT_API_KEY"]
    cases = yaml.safe_load((ROOT / "golden.yaml").read_text(encoding="utf-8"))["casos"]

    results = []
    for c in cases:
        answer, latency, usage = ask(base, key, c["pregunta"])
        fails = check(c, answer)
        results.append({**c, "respuesta": answer, "latencia_s": round(latency, 2),
                        "tokens": usage.get("total_tokens", 0), "ok": not fails, "fallas": fails})
        print(f"{'PASS' if not fails else 'FAIL'}  {c['id']:24} {latency:5.1f}s  {'; '.join(fails)}")
        time.sleep(args.pause)

    passed = sum(r["ok"] for r in results)
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["categoria"], []).append(r["ok"])
    lat = sorted(r["latencia_s"] for r in results)
    p50, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    tokens = sum(r["tokens"] for r in results)

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / f"{args.label}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [f"# Evaluación — {args.label}", "",
          f"**Score: {passed}/{len(results)} ({passed / len(results):.0%})** · "
          f"latencia p50 {p50:.1f}s · p95 {p95:.1f}s · tokens totales {tokens:,}", "",
          "| Categoría | Pasaron |", "|---|---|"]
    md += [f"| {k} | {sum(v)}/{len(v)} |" for k, v in by_cat.items()]
    md += ["", "## Detalle", "", "| Caso | Resultado | Latencia | Fallas |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {'✅' if r['ok'] else '❌'} | {r['latencia_s']}s | {'; '.join(r['fallas'])} |"
           for r in results]
    (out / f"{args.label}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nScore: {passed}/{len(results)} ({passed / len(results):.0%})  ·  p50 {p50:.1f}s  ·  "
          f"reporte: evals/results/{args.label}.md")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
