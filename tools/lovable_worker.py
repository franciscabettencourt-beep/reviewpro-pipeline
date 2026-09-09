#!/usr/bin/env python3
# tools/lovable_worker.py
"""
Vigia da ponte Lovable: pergunta à edge function `bridge` da app se há lotes
pendentes, descarrega os ficheiros pelos URLs assinados, corre o motor
(process_batch, o mesmo parser calibrado da app Streamlit) e devolve o resumo
mais os três ficheiros de resultado em base64.

Ambiente (GitHub Actions secrets):
  BRIDGE_URL  https://<projeto>.supabase.co/functions/v1/bridge
  BRIDGE_KEY  a chave partilhada da ponte (cabeçalho x-bridge-key)

Sem ambiente configurado sai em silêncio, para o cron poder existir antes
de a ponte estar pronta.
"""

import base64
import json
import os
import sys
import traceback
import urllib.request

BRIDGE_URL = (os.environ.get("BRIDGE_URL") or "").strip().rstrip("/")
BRIDGE_KEY = (os.environ.get("BRIDGE_KEY") or "").strip()


def call(method="GET", params="", payload=None):
    url = BRIDGE_URL + (("?" + params) if params else "")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-bridge-key": BRIDGE_KEY,
        "content-type": "application/json",
        "user-agent": "reviewpro-worker/1.0",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def pick(d, *names, default=None):
    """O Lovable escolhe os nomes dos campos; aceitamos as variantes óbvias."""
    for n in names:
        if isinstance(d, dict) and d.get(n) is not None:
            return d[n]
    return default


def download(url):
    req = urllib.request.Request(url, headers={"user-agent": "reviewpro-worker/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def main():
    if not BRIDGE_URL or not BRIDGE_KEY:
        print("Ponte por configurar (BRIDGE_URL/BRIDGE_KEY em falta) — nada a fazer.")
        return 0

    resp = call(params="action=pending")
    jobs = pick(resp, "jobs", "lotes", "pending",
                default=resp if isinstance(resp, list) else [])
    if not jobs:
        print("Sem lotes pendentes.")
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from process_batch import process_batch

    for job in jobs:
        job_id = pick(job, "id", "job_id")
        files = pick(job, "files", "ficheiros", default=[])
        print(f"Lote {job_id}: {len(files)} ficheiro(s)")
        try:
            call("POST", payload={"action": "start", "job_id": job_id})
            vtrl, gir = [], []
            for f in files:
                name = str(pick(f, "name", "nome", "original_name", default="ficheiro"))
                tipo = str(pick(f, "type", "tipo", "kind", default="")).lower()
                url = pick(f, "url", "signed_url", "download_url", "signedUrl", "downloadUrl")
                if not url:
                    raise ValueError(f"ficheiro '{name}' sem URL de download na resposta da ponte")
                data = download(url)
                low = name.lower()
                is_gir = ("gir" in tipo) or (
                    not tipo and ("gir" in low or "interac" in low or "interaction" in low)
                )
                (gir if is_gir else vtrl).append((data, name))
            if not vtrl or not gir:
                raise ValueError(
                    f"o lote precisa de VTRL e GIR (recebi {len(vtrl)} VTRL, {len(gir)} GIR)"
                )
            resumo, ficheiros, avisos = process_batch(vtrl, gir)
            call("POST", payload={
                "action": "complete",
                "job_id": job_id,
                "resumo": resumo,
                "avisos": avisos[:40],
                "ficheiros": [
                    {"nome": n, "conteudo_base64": base64.b64encode(b).decode("ascii")}
                    for n, b in ficheiros.items()
                ],
            })
            print(f"  concluído: {resumo}")
        except Exception as e:
            traceback.print_exc()
            try:
                call("POST", payload={"action": "fail", "job_id": job_id, "erro": str(e)[:500]})
            except Exception:
                print("  (não consegui reportar a falha à ponte)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
