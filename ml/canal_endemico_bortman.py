# -*- coding: utf-8 -*-
"""
Canal endêmico Bortman (P25 / P50 / P75) — Radar LACEN / CIEVS.

Método:
  - Baseline: mesma semana epidemiológica nos últimos N anos, excluindo o ano atual.
  - Percentis P25/P50/P75 sobre valores observados (casos não nulos).
  - Anos sem observação NÃO são preenchidos com zero.
  - Menos de 3 anos de baseline com dado → zona ``sem_dado``.
  - Zonas: sucesso (<P25), seguranca [P25,P50), alerta [P50,P75), epidemia (≥P75).

Série preferencial: positivos laboratoriais (GAL) a partir de
``integrated_weekly_surveillance``. Série opcional: notificações.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_XLSX = "canal_endemico.xlsx"
OUT_CSV = "canal_endemico_classificacao.csv"
MIN_ANOS_BASELINE = 3
ZONAS_RISCO = frozenset({"alerta", "epidemia"})


def _log(msg: str) -> None:
    print(msg, flush=True)


def _norm_mun(val: Any) -> str:
    s = str(val or "").strip().upper()
    s = re.sub(r"\s+", " ", s)
    return s


def _parse_se_iso(se_iso: str | None) -> tuple[int, int] | None:
    if not se_iso:
        return None
    m = re.search(r"(20\d{2})\s*[-_]?SE?(\d{1,2})", str(se_iso), re.I)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def resolver_se_referencia(
    outdir: Path,
    *,
    ano_atual: int | None = None,
    se_atual: int | None = None,
    weekly: pd.DataFrame | None = None,
) -> tuple[int, int, str]:
    """
    Resolve (ano, SE) de referência.
    Ordem: flags CLI → validacao_etl_dw_ultimo → última SE presente nos dados.
    """
    if ano_atual is not None and se_atual is not None:
        return int(ano_atual), int(se_atual), "cli"

    for name in ("validacao_etl_dw_ultimo.json", "validacao_etl_dw_ultimo.txt"):
        path = outdir / name
        if not path.exists():
            continue
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                parsed = _parse_se_iso(str(data.get("se_usada") or ""))
                if parsed:
                    return parsed[0], parsed[1], "validacao_etl_dw"
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"se_usada:\s*(20\d{2}-SE\d{1,2})", text, re.I)
                if m:
                    parsed = _parse_se_iso(m.group(1))
                    if parsed:
                        return parsed[0], parsed[1], "validacao_etl_dw"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue

    if weekly is not None and not weekly.empty:
        ycol = "ano" if "ano" in weekly.columns else "epi_year"
        wcol = "semana_epidemiologica" if "semana_epidemiologica" in weekly.columns else "epi_week"
        g = (
            weekly[[ycol, wcol]]
            .dropna()
            .astype({ycol: int, wcol: int})
            .drop_duplicates()
            .sort_values([ycol, wcol])
        )
        if not g.empty:
            row = g.iloc[-1]
            return int(row[ycol]), int(row[wcol]), "ultima_se_dados"

    raise ValueError(
        "Não foi possível determinar ano/SE de referência "
        "(passe --ano-atual/--se-atual ou rode a validação ETL)."
    )


def carregar_weekly(outdir: Path) -> pd.DataFrame:
    parquet = outdir / "integrated_weekly_surveillance.parquet"
    csv = outdir / "integrated_weekly_surveillance.csv"
    if parquet.exists():
        df = pd.read_parquet(parquet)
        _log(f"[Bortman] Fonte: {parquet.name} ({len(df):,} linhas)")
        return df
    if csv.exists():
        df = pd.read_csv(csv, low_memory=False)
        _log(f"[Bortman] Fonte: {csv.name} ({len(df):,} linhas)")
        return df
    raise FileNotFoundError(
        f"Não encontrado integrated_weekly_surveillance em {outdir}"
    )


def montar_serie(
    weekly: pd.DataFrame,
    *,
    serie: str = "positivos",
) -> pd.DataFrame:
    """
    Mapeia weekly → ano, semana_epidemiologica, agravo, municipio, casos.

    Metadados: série ``positivos`` = coluna positives (canal laboratorial).
    Série ``notificacoes`` = coluna notificacoes (quando disponível).
    Casos NA são removidos (não coerce para zero).
    """
    df = weekly.copy()
    ano = df["epi_year"] if "epi_year" in df.columns else df["ano"]
    semana = df["epi_week"] if "epi_week" in df.columns else df["semana_epidemiologica"]
    agravo = df["target"] if "target" in df.columns else df.get("agravo")
    municipio = df["municipio"].map(_norm_mun)

    if serie == "notificacoes":
        if "notificacoes" not in df.columns:
            raise ValueError("Coluna notificacoes ausente no weekly.")
        casos = pd.to_numeric(df["notificacoes"], errors="coerce")
    else:
        if "positives" not in df.columns and "positivos" not in df.columns:
            raise ValueError("Coluna positives/positivos ausente no weekly.")
        col = "positives" if "positives" in df.columns else "positivos"
        casos = pd.to_numeric(df[col], errors="coerce")

    out = pd.DataFrame(
        {
            "ano": pd.to_numeric(ano, errors="coerce"),
            "semana_epidemiologica": pd.to_numeric(semana, errors="coerce"),
            "agravo": agravo.astype(str).str.strip(),
            "municipio": municipio,
            "casos": casos,
            "serie": serie,
        }
    )
    out = out.dropna(subset=["ano", "semana_epidemiologica", "agravo", "municipio", "casos"])
    out["ano"] = out["ano"].astype(int)
    out["semana_epidemiologica"] = out["semana_epidemiologica"].astype(int)
    out = out[out["agravo"].str.len() > 0]
    out = out[out["municipio"].str.len() > 0]
    # Se houver múltiplas linhas no mesmo agrupamento, soma (ex.: tipagens)
    out = (
        out.groupby(
            ["ano", "semana_epidemiologica", "agravo", "municipio", "serie"],
            as_index=False,
        )["casos"]
        .sum()
    )
    return out


def _classificar_zona(casos: float, p25: float, p50: float, p75: float) -> str:
    if casos < p25:
        return "sucesso"
    if casos < p50:
        return "seguranca"
    if casos < p75:
        return "alerta"
    return "epidemia"


def calcular_canal_bortman(
    serie: pd.DataFrame,
    *,
    ano_atual: int,
    se_atual: int,
    anos_baseline: int = 5,
    min_anos: int = MIN_ANOS_BASELINE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Retorna (classificacao SE atual, limites baseline).
    """
    anos_base = list(range(ano_atual - anos_baseline, ano_atual))
    base = serie[
        (serie["ano"].isin(anos_base))
        & (serie["semana_epidemiologica"] == int(se_atual))
    ].copy()

    keys = ["agravo", "municipio", "semana_epidemiologica", "serie"]
    if base.empty:
        limites = pd.DataFrame(
            columns=keys
            + ["n_anos_baseline", "anos_baseline", "p25", "p50", "p75"]
        )
    else:
        rows: list[dict[str, Any]] = []
        for (ag, mun, se, ser), g in base.groupby(keys, sort=False):
            vals = g["casos"].dropna().astype(float).to_numpy()
            anos = sorted({int(a) for a in g["ano"].dropna().astype(int).tolist()})
            if len(vals) == 0:
                continue
            rows.append(
                {
                    "agravo": ag,
                    "municipio": mun,
                    "semana_epidemiologica": int(se),
                    "serie": ser,
                    "n_anos_baseline": int(len(anos)),
                    "anos_baseline": ",".join(str(a) for a in anos),
                    "p25": float(np.percentile(vals, 25)),
                    "p50": float(np.percentile(vals, 50)),
                    "p75": float(np.percentile(vals, 75)),
                }
            )
        limites = pd.DataFrame(rows)

    atual = serie[
        (serie["ano"] == int(ano_atual))
        & (serie["semana_epidemiologica"] == int(se_atual))
    ].copy()

    if atual.empty:
        classif = pd.DataFrame(
            columns=[
                "ano",
                "semana_epidemiologica",
                "agravo",
                "municipio",
                "serie",
                "casos",
                "n_anos_baseline",
                "anos_baseline",
                "p25",
                "p50",
                "p75",
                "zona",
                "razao_vs_p50",
            ]
        )
        return classif, limites

    classif = atual.merge(
        limites,
        on=["agravo", "municipio", "semana_epidemiologica", "serie"],
        how="left",
    )
    classif["n_anos_baseline"] = classif["n_anos_baseline"].fillna(0).astype(int)
    classif["anos_baseline"] = classif["anos_baseline"].fillna("")

    zonas: list[str] = []
    razoes: list[float | None] = []
    for _, row in classif.iterrows():
        n = int(row["n_anos_baseline"] or 0)
        if n < min_anos or pd.isna(row.get("p25")) or pd.isna(row.get("casos")):
            zonas.append("sem_dado")
            razoes.append(None)
            continue
        p25, p50, p75 = float(row["p25"]), float(row["p50"]), float(row["p75"])
        casos = float(row["casos"])
        zonas.append(_classificar_zona(casos, p25, p50, p75))
        if p50 and p50 > 0:
            razoes.append(round(casos / p50, 4))
        else:
            razoes.append(None)
    classif["zona"] = zonas
    classif["razao_vs_p50"] = razoes
    classif["ano"] = int(ano_atual)
    return classif, limites


def _sheet_metadados(
    *,
    ano_atual: int,
    se_atual: int,
    anos_baseline: int,
    fonte_se: str,
    series_usadas: list[str],
    n_classif: int,
    zona_counts: dict[str, int],
) -> pd.DataFrame:
    rows = [
        ("metodo", "Canal endêmico Bortman (quartis)"),
        ("percentis", "P25 / P50 / P75"),
        ("anos_baseline", str(anos_baseline)),
        ("exclui_ano_atual", "sim"),
        ("min_anos_para_classificar", str(MIN_ANOS_BASELINE)),
        ("missing_como_zero", "nao — anos/semanas sem observação são omitidos"),
        ("serie_preferencial", "positivos (GAL / canal laboratorial)"),
        ("series_calculadas", ",".join(series_usadas)),
        ("ano_atual", str(ano_atual)),
        ("se_atual", str(se_atual)),
        ("fonte_se", fonte_se),
        ("zonas", "sucesso / seguranca / alerta / epidemia / sem_dado"),
        ("regra_sucesso", "casos < P25"),
        ("regra_seguranca", "P25 <= casos < P50"),
        ("regra_alerta", "P50 <= casos < P75"),
        ("regra_epidemia", "casos >= P75"),
        ("n_combinacoes_classificadas", str(n_classif)),
    ]
    for z, n in sorted(zona_counts.items()):
        rows.append((f"zona_count_{z}", str(n)))
    return pd.DataFrame(rows, columns=["chave", "valor"])


def gravar_saidas(
    outdir: Path,
    classif: pd.DataFrame,
    limites: pd.DataFrame,
    meta: pd.DataFrame,
) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    xlsx = outdir / OUT_XLSX
    csv = outdir / OUT_CSV

    classif_out = classif.copy()
    classif_out.to_csv(csv, index=False, encoding="utf-8-sig")

    try:
        with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
            classif_out.to_excel(writer, sheet_name="Classificacao", index=False)
            limites.to_excel(writer, sheet_name="Limites", index=False)
            meta.to_excel(writer, sheet_name="Metadados", index=False)
    except ImportError as exc:
        _log(f"[Bortman][AVISO] openpyxl indisponível ({exc}); gerando só CSV.")
        xlsx = outdir / "canal_endemico_limites.csv"
        limites.to_csv(xlsx, index=False, encoding="utf-8-sig")
        meta_path = outdir / "canal_endemico_metadados.csv"
        meta.to_csv(meta_path, index=False, encoding="utf-8-sig")
        return {"classificacao": csv, "limites": xlsx, "metadados": meta_path}

    return {"xlsx": xlsx, "classificacao": csv}


def run_canal_endemico(
    outdir: Path | str = "saida_pipeline",
    *,
    se_atual: int | None = None,
    ano_atual: int | None = None,
    anos_baseline: int = 5,
    series: str = "positivos",
) -> dict[str, Any]:
    """
    Executa o canal Bortman e grava saídas em ``outdir``.

    ``series``: ``positivos`` | ``notificacoes`` | ``ambos``.
    """
    outdir = Path(outdir)
    weekly = carregar_weekly(outdir)
    ano, se, fonte_se = resolver_se_referencia(
        outdir, ano_atual=ano_atual, se_atual=se_atual, weekly=weekly
    )
    _log(f"[Bortman] Referência: {ano}-SE{se:02d} (fonte={fonte_se})")

    wanted: list[str]
    if series == "ambos":
        wanted = ["positivos"]
        if "notificacoes" in weekly.columns:
            wanted.append("notificacoes")
    elif series == "notificacoes":
        wanted = ["notificacoes"]
    else:
        wanted = ["positivos"]

    parts: list[pd.DataFrame] = []
    for s in wanted:
        try:
            parts.append(montar_serie(weekly, serie=s))
            _log(f"[Bortman] Série montada: {s}")
        except ValueError as exc:
            _log(f"[Bortman][AVISO] Série {s} ignorada: {exc}")

    if not parts:
        raise RuntimeError("Nenhuma série válida para canal endêmico.")

    serie_df = pd.concat(parts, ignore_index=True)
    classif, limites = calcular_canal_bortman(
        serie_df,
        ano_atual=ano,
        se_atual=se,
        anos_baseline=anos_baseline,
    )
    zona_counts = (
        classif["zona"].value_counts().to_dict() if not classif.empty else {}
    )
    meta = _sheet_metadados(
        ano_atual=ano,
        se_atual=se,
        anos_baseline=anos_baseline,
        fonte_se=fonte_se,
        series_usadas=wanted,
        n_classif=len(classif),
        zona_counts={str(k): int(v) for k, v in zona_counts.items()},
    )
    paths = gravar_saidas(outdir, classif, limites, meta)
    _log(
        f"[Bortman] Combinações SE atual: {len(classif):,} | "
        f"zonas={zona_counts}"
    )
    for k, p in paths.items():
        _log(f"[Bortman] Saída {k}: {p}")

    return {
        "ano": ano,
        "se": se,
        "fonte_se": fonte_se,
        "n_combinacoes": len(classif),
        "zona_counts": {str(k): int(v) for k, v in zona_counts.items()},
        "paths": {k: str(v) for k, v in paths.items()},
        "classificacao": classif,
        "limites": limites,
    }


def carregar_indice_bortman(
    outdir: Path | str,
    *,
    se_iso: str | None = None,
    serie: str = "positivos",
) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Índice (agravo, municipio_norm) → linha de classificação Bortman.
    Filtra SE se ``se_iso`` informado; usa série ``positivos`` por padrão.
    """
    outdir = Path(outdir)
    path = outdir / OUT_CSV
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path, low_memory=False)
    except OSError:
        return {}
    if df.empty:
        return {}
    if "serie" in df.columns:
        df = df[df["serie"].astype(str) == serie]
    parsed = _parse_se_iso(se_iso) if se_iso else None
    if parsed and "ano" in df.columns and "semana_epidemiologica" in df.columns:
        y, w = parsed
        df = df[
            (pd.to_numeric(df["ano"], errors="coerce") == y)
            & (pd.to_numeric(df["semana_epidemiologica"], errors="coerce") == w)
        ]
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in df.iterrows():
        ag = str(row.get("agravo") or "").strip()
        mun = _norm_mun(row.get("municipio"))
        if not ag or not mun:
            continue
        out[(ag, mun)] = {
            "zona": str(row.get("zona") or "sem_dado"),
            "casos": row.get("casos"),
            "p25": row.get("p25"),
            "p50": row.get("p50"),
            "p75": row.get("p75"),
            "razao_vs_p50": row.get("razao_vs_p50"),
            "n_anos_baseline": row.get("n_anos_baseline"),
            "serie": str(row.get("serie") or serie),
        }
    return out


def listar_zonas_atencao(
    outdir: Path | str,
    *,
    se_iso: str | None = None,
    serie: str = "positivos",
    top: int = 10,
) -> list[dict[str, Any]]:
    """
    Top município×agravo em zona alerta/epidemia para a SE atual.

    Prioriza casos observados > 0; ignora combinações com baseline e casos
    ambos zerados (artefato quando P25=P50=P75=0).
    """
    outdir = Path(outdir)
    path = outdir / OUT_CSV
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path, low_memory=False)
    except OSError:
        return []
    if df.empty or "zona" not in df.columns:
        return []
    if "serie" in df.columns:
        df = df[df["serie"].astype(str) == serie]
    parsed = _parse_se_iso(se_iso) if se_iso else None
    if parsed and "ano" in df.columns and "semana_epidemiologica" in df.columns:
        y, w = parsed
        df = df[
            (pd.to_numeric(df["ano"], errors="coerce") == y)
            & (pd.to_numeric(df["semana_epidemiologica"], errors="coerce") == w)
        ]
    df = df[df["zona"].astype(str).str.casefold().isin(ZONAS_RISCO)].copy()
    if df.empty:
        return []

    for col in ("casos", "p25", "p50", "p75", "razao_vs_p50"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Descarta falso positivo: 0 casos com limite superior histórico também 0
    if "casos" in df.columns and "p75" in df.columns:
        mask_ruido = (df["casos"].fillna(0) <= 0) & (df["p75"].fillna(0) <= 0)
        df = df[~mask_ruido]
    # Para o alerta CIEVS: só combinações com casos observados (>0)
    if "casos" in df.columns:
        df = df[df["casos"].fillna(0) > 0]
    if df.empty:
        return []

    zona_rank = df["zona"].astype(str).str.casefold().map(
        {"epidemia": 0, "alerta": 1}
    ).fillna(9)
    casos_rank = -df["casos"].fillna(0) if "casos" in df.columns else 0
    df = df.assign(_zr=zona_rank, _cr=casos_rank).sort_values(
        ["_zr", "_cr"], kind="mergesort"
    )

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _, row in df.iterrows():
        ag = str(row.get("agravo") or "").strip()
        mun = _norm_mun(row.get("municipio"))
        if not ag or not mun or (ag, mun) in seen:
            continue
        seen.add((ag, mun))
        out.append(
            {
                "agravo": ag,
                "municipio": mun,
                "zona": str(row.get("zona") or "").casefold(),
                "casos": row.get("casos"),
                "p25": row.get("p25"),
                "p50": row.get("p50"),
                "p75": row.get("p75"),
                "razao_vs_p50": row.get("razao_vs_p50"),
                "n_anos_baseline": row.get("n_anos_baseline"),
                "serie": str(row.get("serie") or serie),
                "ano": row.get("ano"),
                "semana_epidemiologica": row.get("semana_epidemiologica"),
            }
        )
        if len(out) >= max(1, int(top)):
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Canal endêmico Bortman (P25/P50/P75) — LACEN / CIEVS"
    )
    ap.add_argument("--outdir", default="saida_pipeline")
    ap.add_argument("--se-atual", type=int, default=None, help="Semana epidemiológica")
    ap.add_argument("--ano-atual", type=int, default=None, help="Ano epidemiológico")
    ap.add_argument("--anos-baseline", type=int, default=5)
    ap.add_argument(
        "--serie",
        choices=("positivos", "notificacoes", "ambos"),
        default="positivos",
        help="Série de casos (padrão: positivos laboratoriais)",
    )
    args = ap.parse_args()
    run_canal_endemico(
        args.outdir,
        se_atual=args.se_atual,
        ano_atual=args.ano_atual,
        anos_baseline=args.anos_baseline,
        series=args.serie,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
