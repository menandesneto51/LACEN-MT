# -*- coding: utf-8 -*-
"""Atualiza integração final + inteligência territorial e reporta status DW."""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "saida_pipeline"
PY = BASE / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)


def dw_reachable(host: str = "10.15.1.50", port: int = 1433, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(cmd: list[str]) -> int:
    print(">", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(BASE))


def main() -> int:
    print("=== Status DW ===", flush=True)
    ok = dw_reachable()
    print(f"DW 10.15.1.50:1433 acessivel: {ok}", flush=True)

    if ok:
        print("Tentando inventário DW...", flush=True)
        code = run([str(PY), str(BASE / "_dw_inventario.py")])
        if code != 0:
            print("[AVISO] Inventário DW falhou; seguindo com bases locais.", flush=True)
    else:
        print("[AVISO] DW inacessível (VPN/rede SES). Atualizando com CSVs locais.", flush=True)

    # Integração final (usa saida_pipeline existente)
    final = BASE / "lacen_integracao_final_only.py"
    if final.exists():
        code = run([str(PY), str(final), "--outdir", str(OUT)])
        if code != 0:
            print("[AVISO] Integração final retornou", code, "— gerando territorial via stdlib.", flush=True)
            run([str(PY), str(BASE / "gerar_inteligencia_territorial_stdlib.py")])
    else:
        run([str(PY), str(BASE / "gerar_inteligencia_territorial_stdlib.py")])

    # Garantir CSVs territoriais
    for name in ("municipios_em_risco.csv", "municipios_silenciosos.csv", "taxa_utilizacao_lacen.csv"):
        p = OUT / name
        print(f"{'OK' if p.exists() else 'MISSING'} {name}", flush=True)

    # Sinais preditivos (ML baseline — não depende do DW)
    ml_script = BASE / "ml" / "run_ml_pipeline.py"
    if ml_script.exists():
        code = run([str(PY), "-m", "ml.run_ml_pipeline", "--outdir", str(OUT)])
        if code != 0:
            print("[AVISO] Pipeline ML retornou", code, flush=True)
    for name in (
        "ml_forecast_demanda.csv",
        "ml_anomalias.csv",
        "ml_risco_predito.csv",
        "ml_silencio_predito.csv",
    ):
        p = OUT / name
        print(f"{'OK' if p.exists() else 'MISSING'} {name}", flush=True)

    print("[FINAL] Atualização local concluída.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
