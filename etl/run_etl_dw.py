# -*- coding: utf-8 -*-
"""
ETL LACEN MT — DW → weekly/territorial → rede/emergência/ML → mirror → validação SE.

Uso:
  python -m etl.run_etl_dw
  python -m etl.run_etl_dw --allow-local-fallback
  python -m etl.run_etl_dw --skip-ml --skip-cievs
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.build_weekly_from_gal import (  # noqa: E402
    choose_se_operacional,
    publish_weekly_inputs,
    weekly_from_dw_agg,
    weekly_from_local_gal,
)
from etl.dw_extract import check_dw_tcp, run_extract, staging_dir  # noqa: E402
from etl.epi_week import format_se, semana_completa_mais_recente  # noqa: E402

PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _run(args: list[str], *, check: bool = False) -> int:
    _log("> " + " ".join(str(a) for a in args))
    code = subprocess.call([str(a) for a in args], cwd=str(ROOT))
    if check and code != 0:
        raise RuntimeError(f"Comando falhou ({code}): {' '.join(str(a) for a in args)}")
    return code


def _counts_for_se(weekly: pd.DataFrame, ano: int, se: int) -> dict[str, Any]:
    if weekly is None or weekly.empty:
        return {"exames": 0, "positivos": 0, "municipios": 0, "linhas": 0}
    w = weekly.copy()
    w["epi_year"] = pd.to_numeric(w.get("epi_year"), errors="coerce")
    w["epi_week"] = pd.to_numeric(w.get("epi_week"), errors="coerce")
    sub = w[(w["epi_year"] == ano) & (w["epi_week"] == se)]
    exames = float(pd.to_numeric(sub.get("tests"), errors="coerce").fillna(0).sum()) if "tests" in sub else 0.0
    pos = float(pd.to_numeric(sub.get("positives"), errors="coerce").fillna(0).sum()) if "positives" in sub else 0.0
    return {
        "exames": int(exames),
        "positivos": int(pos),
        "municipios": int(sub["municipio"].nunique()) if "municipio" in sub else 0,
        "linhas": int(len(sub)),
    }


def write_validacao(
    outdir: Path,
    report: dict[str, Any],
) -> Path:
    path = outdir / "validacao_etl_dw_ultimo.txt"
    lines = [
        "LACEN MT — validação ETL DW + SE real",
        f"gerado_em: {report.get('ts')}",
        f"hoje: {report.get('hoje')}",
        f"se_esperada: {report.get('se_esperada')}",
        f"se_usada: {report.get('se_usada')}",
        f"atraso_se: {report.get('atraso_se')}",
        f"atraso_dias: {report.get('atraso_dias')}",
        f"se_fonte: {report.get('se_fonte')}",
        f"fonte_dados: {report.get('fonte_dados')}",
        f"objetos_dw: {report.get('objetos_dw')}",
        f"sources_extracted: {report.get('sources_extracted')}",
        f"exames_se_usada: {report.get('exames_se_usada')}",
        f"positivos_se_usada: {report.get('positivos_se_usada')}",
        f"municipios_se_usada: {report.get('municipios_se_usada')}",
        f"mirror_dw_ok: {report.get('mirror_dw_ok')}",
        f"mirror_error: {report.get('mirror_error')}",
        f"mirror_rows: {report.get('mirror_rows')}",
        f"aviso: {report.get('aviso') or '(nenhum)'}",
        f"passos: {json.dumps(report.get('passos', []), ensure_ascii=False)}",
        "",
        "DBA (se CREATE TABLE negado): executar saida_pipeline/sql/create_lacen_ml_tables.sql",
        "e reexecutar: python -m ml.mirror_dw",
        "VPN: host DW_HOST (padrão 10.15.1.50:1433) via rede SES; credenciais DW_* no .env",
        "Agenda: ver etl/AGENDADOR.md (Task Scheduler diário/semanal).",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"[OK] {path}")
    return path


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    hoje = datetime.now().date()
    esp = semana_completa_mais_recente(hoje)
    report: dict[str, Any] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "hoje": str(hoje),
        "se_esperada": format_se(*esp),
        "passos": [],
        "fonte_dados": None,
        "objetos_dw": [],
        "sources_extracted": [],
    }

    tcp_ok, host, port = check_dw_tcp(timeout=float(args.tcp_timeout))
    extract_meta: dict[str, Any] = {}
    tests = pos = None

    if tcp_ok:
        _log(f"[ETL] DW TCP OK {host}:{port} — extraindo…")
        try:
            extract_meta = run_extract(
                outdir, weeks_back=args.weeks_back, micro_days=args.micro_days
            )
            report["fonte_dados"] = "DW:" + str(extract_meta.get("gal_view") or "VW_GAL")
            report["objetos_dw"] = [
                f"{r.get('TABLE_SCHEMA')}.{r.get('TABLE_NAME')}"
                for r in (extract_meta.get("objects") or [])[:80]
            ]
            report["sources_extracted"] = extract_meta.get("sources_extracted") or []
            report["passos"].append("extract_dw_ok")
            stage = staging_dir(outdir)
            agg_path = stage / "vw_gal_weekly_agg.parquet"
            if not agg_path.exists():
                agg_path = stage / "vw_gal_weekly_agg.csv"
            agg = pd.read_parquet(agg_path) if agg_path.suffix == ".parquet" else pd.read_csv(agg_path)
            tests, pos = weekly_from_dw_agg(agg)
            # micro → CSV para indicadores de rede
            micro_pq = stage / "vw_gal_micro_recent.parquet"
            if micro_pq.exists():
                micro = pd.read_parquet(micro_pq)
                micro_csv = stage / "vw_gal_micro_recent_for_rede.csv"
                with open(micro_csv, "w", encoding="latin-1", errors="replace", newline="") as fh:
                    micro.to_csv(fh, index=False)
                report["micro_gal_path"] = str(micro_csv)
        except Exception as exc:
            _log(f"[ETL] Extração DW falhou: {exc}")
            report["passos"].append(f"extract_dw_fail:{type(exc).__name__}")
            if not args.allow_local_fallback:
                raise
            tcp_ok = False
    else:
        msg = (
            f"DW inacessível em {host}:{port}. Conecte a VPN SES-MT. "
            "Ou use --allow-local-fallback (SE pode ficar meses atrás)."
        )
        if not args.allow_local_fallback:
            report["aviso"] = msg
            write_validacao(outdir, {**report, "se_usada": None, "atraso_se": None,
                                     "mirror_dw_ok": False, "mirror_error": msg,
                                     "exames_se_usada": 0, "positivos_se_usada": 0,
                                     "municipios_se_usada": 0, "mirror_rows": {}})
            raise ConnectionError(msg)
        _log(f"[ETL] AVISO: {msg}")
        report["passos"].append("dw_tcp_fail_local_fallback")

    if tests is None:
        gal_local = ROOT / "LACEN 2010 a 2026.csv"
        if not gal_local.exists():
            raise FileNotFoundError(
                "Sem DW e sem CSV local 'LACEN 2010 a 2026.csv' para fallback."
            )
        report["fonte_dados"] = f"local:{gal_local.name}"
        _log(f"[ETL] Fallback local → {gal_local.name}")
        tests, pos = weekly_from_local_gal(gal_local, year_min=args.local_year_min)
        report["passos"].append("local_gal_weekly")

    pub = publish_weekly_inputs(tests, pos, outdir)
    report["passos"].append("publish_weekly_inputs")
    _log(f"[ETL] weekly publicados: {pub}")

    # Integração final (reconstrói integrated_weekly)
    code = _run([str(PY), str(ROOT / "lacen_integracao_final_only.py"), "--outdir", str(outdir)])
    report["passos"].append(f"integracao_final:{code}")

    weekly_path = outdir / "integrated_weekly_surveillance.csv"
    weekly = pd.read_csv(weekly_path, low_memory=False) if weekly_path.exists() else pd.DataFrame()
    se_info = choose_se_operacional(weekly if not weekly.empty else tests, hoje=hoje)
    report.update({k: se_info.get(k) for k in (
        "se_usada", "atraso_se", "atraso_dias", "se_fonte", "aviso",
    )})

    # Rede — preferir micro DW se existir
    rede_args = [str(PY), str(ROOT / "gerar_indicadores_rede_lacen.py"), "--outdir", str(outdir)]
    micro_csv = report.get("micro_gal_path")
    if micro_csv and Path(micro_csv).exists():
        rede_args.extend(["--gal", str(micro_csv), "--years", "1"])
    else:
        rede_args.extend(["--years", "2"])
    code = _run(rede_args)
    report["passos"].append(f"indicadores_rede:{code}")

    code = _run([str(PY), str(ROOT / "gerar_indicadores_emergencia.py"), "--outdir", str(outdir)])
    report["passos"].append(f"indicadores_emergencia:{code}")

    if (ROOT / "gerar_confirmacao_emergencia.py").exists():
        code = _run([str(PY), str(ROOT / "gerar_confirmacao_emergencia.py"), "--outdir", str(outdir)])
        report["passos"].append(f"confirmacao_emergencia:{code}")

    if not args.skip_ml:
        code = _run([str(PY), "-m", "ml.run_ml_pipeline", "--outdir", str(outdir)])
        report["passos"].append(f"ml:{code}")

    # Mirror DW
    mirror_status: dict[str, Any] = {"dw_ok": False, "error": "não executado"}
    try:
        from ml.mirror_dw import (
            append_alerta_emergencia_historico,
            append_alerta_historico,
            atualizar_desfechos,
            build_executive_summaries,
            mirror_to_dw,
            seed_alertas_retrospectivos,
        )
        append_alerta_emergencia_historico(outdir)
        risco = pd.read_csv(outdir / "ml_risco_predito.csv") if (outdir / "ml_risco_predito.csv").exists() else None
        sil = pd.read_csv(outdir / "ml_silencio_predito.csv") if (outdir / "ml_silencio_predito.csv").exists() else None
        append_alerta_historico(outdir, risco, sil)
        seed_alertas_retrospectivos(outdir)
        atualizar_desfechos(outdir)
        build_executive_summaries(outdir)
        mirror_status = mirror_to_dw(outdir, do_bulk=not args.no_bulk)
        report["passos"].append("mirror_dw")
    except Exception as exc:
        mirror_status = {"dw_ok": False, "error": str(exc)}
        report["passos"].append(f"mirror_fail:{type(exc).__name__}")

    report["mirror_dw_ok"] = bool(mirror_status.get("dw_ok")) and not mirror_status.get("error")
    if mirror_status.get("rows"):
        report["mirror_dw_ok"] = bool(mirror_status.get("dw_ok")) and bool(mirror_status.get("rows"))
    report["mirror_error"] = mirror_status.get("error") or mirror_status.get("note")
    report["mirror_rows"] = mirror_status.get("rows") or {}
    if mirror_status.get("skipped_create_denied"):
        report["aviso"] = (
            (report.get("aviso") or "")
            + " | CREATE TABLE negado: "
            + ", ".join(mirror_status["skipped_create_denied"])
            + " — DBA deve rodar saida_pipeline/sql/create_lacen_ml_tables.sql"
        ).strip(" |")

    # Contagens SE usada
    usada = se_info.get("se_usada_tuple")
    if usada:
        cnt = _counts_for_se(weekly if not weekly.empty else tests, usada[0], usada[1])
        report["exames_se_usada"] = cnt["exames"]
        report["positivos_se_usada"] = cnt["positivos"]
        report["municipios_se_usada"] = cnt["municipios"]
    else:
        report["exames_se_usada"] = 0
        report["positivos_se_usada"] = 0
        report["municipios_se_usada"] = 0

    if not args.skip_cievs:
        code = _run([
            str(PY), str(ROOT / "scripts" / "enviar_relatorio_cievs.py"), "--dry-run",
        ])
        report["passos"].append(f"cievs_dry_run:{code}")

    write_validacao(outdir, report)
    (outdir / "validacao_etl_dw_ultimo.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ETL LACEN: DW + SE real")
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--weeks-back", type=int, default=60)
    ap.add_argument("--micro-days", type=int, default=120)
    ap.add_argument("--local-year-min", type=int, default=2024)
    ap.add_argument("--tcp-timeout", type=float, default=3.0)
    ap.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="Se DW/VPN cair, usa CSV GAL local (pode gerar SE atrasada com banner).",
    )
    ap.add_argument("--skip-ml", action="store_true")
    ap.add_argument("--skip-cievs", action="store_true")
    ap.add_argument("--no-bulk", action="store_true", help="Mirror sem INSERT (só status/DDL).")
    args = ap.parse_args(argv)

    try:
        report = run_pipeline(args)
    except ConnectionError as exc:
        _log(f"[FALHA] {exc}")
        return 2
    except Exception as exc:
        _log(f"[FALHA] {type(exc).__name__}: {exc}")
        return 1

    _log(
        "[RESUMO] "
        f"hoje={report.get('hoje')} se_esperada={report.get('se_esperada')} "
        f"se_usada={report.get('se_usada')} atraso_se={report.get('atraso_se')} "
        f"fonte={report.get('fonte_dados')} mirror_ok={report.get('mirror_dw_ok')}"
    )
    if report.get("aviso"):
        _log(f"[AVISO] {report['aviso']}")
    # Exit 3 se atraso grave (dados meses atrás)
    atr = report.get("atraso_se")
    if atr is not None and int(atr) >= 8:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
