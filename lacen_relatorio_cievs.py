#!/usr/bin/env python3
"""
LACEN-MT / CIEVS / Vigidesastres — Radar LACEN (alerta institucional).

Monta payload fixo (blocos A–E + F opcional VE) preferindo leitura no
Datawarehouse (DW) e com fallback para agregados em `saida_pipeline`
(sem PII/microdados). Formata para Telegram (curto, HTML) e e-mail
(completo, HTML institucional).

Uso:
  from lacen_relatorio_cievs import montar_relatorio, to_telegram_markdown, to_email_html
"""
from __future__ import annotations

import csv
import html
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from lacen_briefing_epi import (
    briefing_para_relatorio,
    gerar_briefing_epi,
)

ROOT = Path(__file__).resolve().parent
OUTDIR_DEFAULT = ROOT / "saida_pipeline"

DASHBOARD_URL = (
    "https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/"
)

ORGAOS = ("SES-MT", "LACEN-MT", "CIEVS", "Vigidesastres")

# Nome do produto (Telegram/e-mail/header). Override: LACEN_ALERTA_NOME no .env
NOME_FERRAMENTA = PRODUCT_NAME = "Radar LACEN"


def get_nome_ferramenta() -> str:
    """Nome exibido; prioriza LACEN_ALERTA_NOME no ambiente."""
    override = (os.environ.get("LACEN_ALERTA_NOME") or "").strip()
    return override or NOME_FERRAMENTA

# Logical artifact → (DW table candidates, local CSV candidates)
SOURCE_MAP: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "fila_operacional": (
        ("lacen_fila_operacional",),
        ("fila_operacional.csv",),
    ),
    "ml_risco_predito": (
        ("lacen_ml_risco_predito",),
        ("ml_risco_predito.csv", "municipios_em_risco.csv"),
    ),
    "ml_silencio_predito": (
        ("lacen_ml_silencio_predito",),
        ("ml_silencio_predito.csv",),
    ),
    "ml_pressao_rede_predito": (
        ("lacen_ml_pressao_rede_predito",),
        ("ml_pressao_rede_predito.csv",),
    ),
    "indicadores_emergencia": (
        ("lacen_indicadores_emergencia",),
        ("indicadores_emergencia.csv",),
    ),
    "indicadores_emergencia_resumo": (
        ("lacen_indicadores_emergencia_resumo",),
        ("indicadores_emergencia_resumo.csv",),
    ),
    "indicadores_emergencia_familia": (
        ("lacen_indicadores_emergencia_familia",),
        ("indicadores_emergencia_familia.csv",),
    ),
    "indicadores_rede": (
        ("lacen_indicadores_rede",),
        ("indicadores_rede_laboratorial.csv",),
    ),
    "indicadores_rede_resumo": (
        ("lacen_indicadores_rede_resumo",),
        ("indicadores_rede_resumo.csv",),
    ),
    "indicadores_rede_por_familia": (
        ("lacen_indicadores_rede_por_familia",),
        ("indicadores_rede_por_familia.csv",),
    ),
    "qualidade_dado": (
        ("lacen_qualidade_dado",),
        ("qualidade_dado_municipal.csv",),
    ),
    "alerta_emergencia_historico": (
        ("lacen_alerta_emergencia_historico",),
        ("alerta_emergencia_historico.csv",),
    ),
    "emergencia_confirmacao_resumo": (
        ("lacen_emergencia_confirmacao_resumo",),
        ("emergencia_confirmacao_resumo.csv",),
    ),
    "integrated_weekly": (
        ("lacen_integrated_weekly_surveillance",),
        ("integrated_weekly_surveillance.csv",),
    ),
    "executive_state": (
        ("lacen_executive_state_summary",),
        ("executive_state_summary.csv",),
    ),
    "integrated_target_summary": (
        (),
        ("integrated_target_municipio_summary.csv",),
    ),
    "municipio_vizinhos": (
        (),
        ("municipio_vizinhos.csv",),
    ),
}

FEATURE_LABELS_PT: dict[str, str] = {
    "cnes_estabelecimentos": "estabelecimentos CNES",
    "cnes_leitos_total": "leitos CNES",
    "cnes_equipes_esf": "equipes ESF",
    "positividade": "positividade",
    "positividade_ma8": "positividade MA8",
    "tests": "exames",
    "tests_ma8": "exames MA8",
    "tests_ultima_semana": "exames última SE",
    "backlog_estimado": "backlog estimado",
    "indice_pressao_proxy": "índice de pressão",
    "indice_pressao_proxy_atual": "índice de pressão",
    "indice_pressao_rede": "índice de pressão rede",
    "tat_p90_dias": "TAT p90 (dias)",
    "tat_mediano_dias": "TAT mediano (dias)",
    "pct_liberado_48h": "% liberado ≤48h",
    "pct_rejeitado": "% rejeitado",
    "notificacoes_ultima_semana": "notificações última SE",
    "semanas_sem_exame": "semanas sem exame",
    "risco_composto": "risco composto",
}


def _cell(row: dict, *keys: str, default: str = "—") -> str:
    for k in keys:
        if k in row and str(row.get(k) or "").strip():
            return str(row[k]).strip()
    return default


def _num(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    s = str(val).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none", "—", "-", "true", "false"):
        if s.lower() in ("true", "false"):
            return (1.0 if s.lower() == "true" else 0.0) if default is None else default
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _fmt_pct(x: float | None, digits: int = 0) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    v = x * 100 if abs(x) <= 1.5 else x
    return f"{v:.{digits}f}%".replace(".", ",")


def _fmt_num(x: float | None, digits: int = 1) -> str:
    """Número legível em pt-BR (sem notação científica)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    if abs(x) >= 1000 or abs(x - round(x)) < 1e-9:
        n = int(round(x))
        return f"{n:,}".replace(",", ".")
    return f"{x:.{digits}f}".replace(".", ",")


def _fmt_human_value(val: float) -> str:
    if abs(val) >= 100 or abs(val - round(val)) < 1e-6:
        return _fmt_num(val, 0)
    if abs(val) >= 10:
        return _fmt_num(val, 1)
    return _fmt_num(val, 2)


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in ("1", "true", "sim", "yes", "t", "verdadeiro"):
        return True
    n = _num(val)
    return n is not None and n > 0 and s not in ("0", "false", "nao", "não", "n")


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if limit is not None:
        return rows[:limit]
    return rows


def _df_to_rows(df: Any) -> list[dict[str, str]]:
    if df is None:
        return []
    try:
        if getattr(df, "empty", True):
            return []
        out: list[dict[str, str]] = []
        for rec in df.to_dict(orient="records"):
            out.append({str(k): "" if v is None else str(v) for k, v in rec.items()})
        return out
    except Exception:
        return []


def _humanize_feature(name: str) -> str:
    key = (name or "").strip()
    if key in FEATURE_LABELS_PT:
        return FEATURE_LABELS_PT[key]
    # snake_case → palavras
    return key.replace("_", " ").strip() or "fator"


_DRIVER_RE = re.compile(
    r"(?P<feat>[A-Za-z_][\w]*)\s*=\s*(?P<val>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?:\s*\(imp\s*=\s*[^)]+\))?"
)


def _humanize_driver(text: str, max_parts: int = 2, max_len: int = 110) -> str:
    """Converte `cnes_estabelecimentos=6.3e+03 (imp=…)` → `estabelecimentos CNES: 6.300`."""
    t = (text or "").strip()
    if not t or t == "—":
        return "—"
    parts: list[str] = []
    for chunk in t.split(";"):
        m = _DRIVER_RE.search(chunk)
        if not m:
            cleaned = chunk.strip()
            if cleaned and "=" not in cleaned:
                parts.append(cleaned[:50])
            continue
        feat = _humanize_feature(m.group("feat"))
        try:
            val = float(m.group("val"))
        except ValueError:
            val = None
        if val is None:
            parts.append(f"{feat}: {m.group('val')}")
        else:
            parts.append(f"{feat}: {_fmt_human_value(val)}")
        if len(parts) >= max_parts:
            break
    out = "; ".join(parts) if parts else "fatores de risco (modelo)"
    if len(out) > max_len:
        return out[: max_len - 1] + "…"
    return out


@dataclass
class RelatorioSources:
    """Fontes carregadas (DW e/ou arquivo local)."""

    data: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    fonte_primaria: str = "arquivo local"
    tabelas_dw: list[str] = field(default_factory=list)
    arquivos_local: list[str] = field(default_factory=list)
    banner: str = ""
    dw_ok: bool = False
    dw_enrich: dict[str, Any] = field(default_factory=dict)
    staging_dw_ok: bool = False
    etl_fonte: str = ""
    etl_atraso_se: int | None = None
    etl_meta: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, limit: int | None = None) -> list[dict[str, str]]:
        rows = self.data.get(key) or []
        if limit is not None:
            return rows[:limit]
        return rows


def _read_etl_validacao(outdir: Path) -> dict[str, Any]:
    """Lê validacao_etl_dw_ultimo.json (última ETL) se existir."""
    path = Path(outdir) / "validacao_etl_dw_ultimo.json"
    if not path.is_file():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _staging_dw_present(outdir: Path) -> bool:
    """True se há extrato DW usable em saida_pipeline/staging_dw."""
    stage = Path(outdir) / "staging_dw"
    if not stage.is_dir():
        return False
    markers = (
        "extract_meta.json",
        "vw_gal_weekly_agg.parquet",
        "vw_gal_weekly_agg.csv",
        "vw_gal_micro_recent.parquet",
        "vw_gal_micro_recent.csv",
        "vw_gal_micro_recent_for_rede.csv",
    )
    return any((stage / name).is_file() for name in markers)


def _apply_fonte_from_etl_staging(bundle: RelatorioSources, outdir: Path) -> None:
    """
    Corrige banner falso 'DW indisponível' quando o pipeline usou DW
    (validacao_etl / staging_dw) mesmo sem espelhos lacen_* online.
    """
    etl = _read_etl_validacao(outdir)
    staging_ok = _staging_dw_present(outdir)
    bundle.etl_meta = etl
    bundle.staging_dw_ok = staging_ok
    fonte_etl = str(etl.get("fonte_dados") or "").strip()
    bundle.etl_fonte = fonte_etl
    atraso = etl.get("atraso_se")
    try:
        bundle.etl_atraso_se = int(atraso) if atraso is not None else None
    except (TypeError, ValueError):
        bundle.etl_atraso_se = None

    live_dw = bundle.dw_ok or bool(bundle.tabelas_dw) or bool(bundle.dw_enrich)
    etl_is_dw = fonte_etl.upper().startswith("DW")
    # Já marcado como DW live — não sobrescrever
    if live_dw and "DW" in (bundle.fonte_primaria or "").upper():
        if "indispon" not in (bundle.fonte_primaria or "").casefold():
            return

    if etl_is_dw or staging_ok:
        view = fonte_etl.split(":", 1)[-1].strip() if etl_is_dw else "VW_GAL"
        if not view:
            view = "VW_GAL"
        if live_dw:
            bundle.fonte_primaria = f"DW · {view} (+ arquivo local)"
        else:
            bundle.fonte_primaria = f"DW · staging ({view}) + saida_pipeline"
        bundle.banner = ""
        if view and f"dbo.{view}" not in bundle.tabelas_dw and view not in bundle.tabelas_dw:
            bundle.tabelas_dw = list(
                dict.fromkeys([*(bundle.tabelas_dw or []), f"staging:{view}"])
            )


def _try_connect_dw() -> tuple[Any, Any] | None:
    """Retorna (mode, queryable) ou None. Não imprime segredos."""
    try:
        from ml.mirror_dw import dw_reachable

        if not dw_reachable():
            return None
    except Exception:
        # fallback: tenta conectar mesmo sem probe
        pass
    try:
        from lacen_dw import connect_dw

        return connect_dw()
    except Exception:
        return None


def _dw_table_exists(mode: Any, queryable: Any, table: str, schema: str = "dbo") -> bool:
    try:
        from lacen_dw import read_sql

        df = read_sql(
            mode,
            queryable,
            "SELECT CASE WHEN OBJECT_ID(?, N'U') IS NULL "
            "AND OBJECT_ID(?, N'V') IS NULL THEN 0 ELSE 1 END AS ok",
            params=(f"[{schema}].[{table}]", f"[{schema}].[{table}]"),
        )
        return int(df.iloc[0]["ok"]) == 1
    except Exception:
        try:
            from lacen_dw import read_sql

            df = read_sql(
                mode,
                queryable,
                "SELECT 1 AS ok FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
                params=(schema, table),
            )
            return not df.empty
        except Exception:
            return False


def _dw_select(
    mode: Any, queryable: Any, table: str, schema: str = "dbo", limit: int = 50000
) -> list[dict[str, str]]:
    from lacen_dw import read_sql

    # TOP para não estourar memória em espelhos grandes
    sql = f"SELECT TOP ({int(limit)}) * FROM [{schema}].[{table}]"
    return _df_to_rows(read_sql(mode, queryable, sql))


def _enrich_from_vw_gal(mode: Any, queryable: Any) -> dict[str, Any]:
    """Agregados leves de VW_GAL (volume recente + CRS operacional)."""
    from lacen_dw import read_sql

    out: dict[str, Any] = {"view": "dbo.VW_GAL"}
    try:
        mx = read_sql(
            mode,
            queryable,
            """
            SELECT MAX(Data_Liberacao_dt) AS max_dt
            FROM dbo.VW_GAL
            WHERE Data_Liberacao_dt IS NOT NULL
            """,
        )
        if not mx.empty and mx.iloc[0]["max_dt"] is not None:
            max_dt = mx.iloc[0]["max_dt"]
            if hasattr(max_dt, "to_pydatetime"):
                max_dt = max_dt.to_pydatetime()
            if getattr(max_dt, "tzinfo", None) is not None:
                max_dt = max_dt.replace(tzinfo=None)
            out["dw_max_liberacao"] = max_dt
            out["dw_lag_dias"] = (datetime.now() - max_dt).days
    except Exception as exc:
        out["erro_max_dt"] = type(exc).__name__

    try:
        weeks = read_sql(
            mode,
            queryable,
            """
            SELECT TOP 6
              YEAR(Data_Liberacao_dt) AS y,
              DATEPART(iso_week, Data_Liberacao_dt) AS iso_w,
              COUNT_BIG(*) AS n_exames,
              COUNT(DISTINCT Municipio_Solicitante) AS n_mun
            FROM dbo.VW_GAL
            WHERE Data_Liberacao_dt >= DATEADD(day, -90, CAST(GETDATE() AS date))
              AND Data_Liberacao_dt IS NOT NULL
            GROUP BY YEAR(Data_Liberacao_dt), DATEPART(iso_week, Data_Liberacao_dt)
            ORDER BY y DESC, iso_w DESC
            """,
        )
        if not weeks.empty:
            r0 = weeks.iloc[0]
            out["exames_se_recente"] = int(r0["n_exames"])
            out["municipios_com_exame"] = int(r0["n_mun"])
            out["se_iso"] = f"{int(r0['y'])}-SE{int(r0['iso_w']):02d}"
            if len(weeks) >= 2:
                prev = int(weeks.iloc[1]["n_exames"])
                cur = int(r0["n_exames"])
                if prev > 0:
                    out["delta_exames_pct"] = (cur - prev) / prev
    except Exception as exc:
        out["erro_semanas"] = type(exc).__name__

    try:
        crs = read_sql(
            mode,
            queryable,
            """
            SELECT TOP 3 Laboratorio_Cadastro AS crs, COUNT_BIG(*) AS n
            FROM dbo.VW_GAL
            WHERE Data_Liberacao_dt >= DATEADD(day, -60, CAST(GETDATE() AS date))
              AND Laboratorio_Cadastro IS NOT NULL
              AND LTRIM(RTRIM(Laboratorio_Cadastro)) <> ''
            GROUP BY Laboratorio_Cadastro
            ORDER BY n DESC
            """,
        )
        out["crs_top"] = [
            {"crs": str(r["crs"])[:60], "n": int(r["n"])}
            for _, r in crs.iterrows()
        ]
    except Exception:
        out["crs_top"] = []

    # Sem dimensão CRS oficial estável em VW_GAL — não inventar mapeamento.
    out["mun_crs"] = {}
    return out


def load_relatorio_sources(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    prefer_dw: bool = True,
) -> RelatorioSources:
    """
    Carrega artefatos do relatório.

    Ordem: tabelas lacen_* no DW (se existirem) → CSV local.
    Enriquecimento opcional via dbo.VW_GAL quando o DW responde.
    """
    outdir = Path(outdir)
    bundle = RelatorioSources()
    conn = _try_connect_dw() if prefer_dw else None
    mode = queryable = None
    if conn is not None:
        mode, queryable = conn
        bundle.dw_ok = True

    dw_hits = 0
    local_hits = 0

    for key, (dw_tables, csv_names) in SOURCE_MAP.items():
        rows: list[dict[str, str]] = []
        used_dw = False
        if mode is not None and queryable is not None:
            for table in dw_tables:
                try:
                    if _dw_table_exists(mode, queryable, table):
                        rows = _dw_select(mode, queryable, table)
                        if rows:
                            bundle.tabelas_dw.append(f"dbo.{table}")
                            used_dw = True
                            dw_hits += 1
                            break
                except Exception:
                    continue
        if not rows:
            for name in csv_names:
                path = outdir / name
                rows = _read_csv(path)
                if rows:
                    bundle.arquivos_local.append(name)
                    local_hits += 1
                    break
        bundle.data[key] = rows
        if used_dw:
            pass  # already recorded

    if mode is not None and queryable is not None:
        try:
            enrich = _enrich_from_vw_gal(mode, queryable)
            bundle.dw_enrich = enrich
            if enrich.get("view"):
                bundle.tabelas_dw.append(str(enrich["view"]))
        except Exception:
            bundle.dw_enrich = {}

    # Fechar conexão pyodbc se aplicável
    if mode == "pyodbc" and queryable is not None:
        try:
            queryable.close()
        except Exception:
            pass

    if dw_hits > 0 and local_hits == 0:
        bundle.fonte_primaria = "DW · Datawarehouse"
        bundle.banner = ""
    elif dw_hits > 0:
        bundle.fonte_primaria = "DW · Datawarehouse (+ arquivo local complementar)"
        bundle.banner = ""
    elif bundle.dw_ok and bundle.dw_enrich:
        # Conectou e leu VW_GAL, mas espelhos lacen_* ausentes
        bundle.fonte_primaria = "DW · Datawarehouse (VW_GAL) + arquivo local"
        bundle.banner = (
            "Espelhos lacen_* indisponíveis no DW — indicadores consolidados "
            "via saida_pipeline; volume recente enriquecido por VW_GAL."
        )
    elif bundle.dw_ok:
        bundle.fonte_primaria = "arquivo local (espelhos lacen_* ausentes no DW)"
        bundle.banner = "Fonte: arquivo local (tabelas lacen_* não encontradas no DW)"
    else:
        bundle.fonte_primaria = "arquivo local (DW indisponível)"
        bundle.banner = "Fonte: arquivo local (DW indisponível)"

    # Staging / última ETL DW: evita falso "DW indisponível" no Telegram
    _apply_fonte_from_etl_staging(bundle, outdir)

    # dedupe listas mantendo ordem
    bundle.tabelas_dw = list(dict.fromkeys(bundle.tabelas_dw))
    bundle.arquivos_local = list(dict.fromkeys(bundle.arquivos_local))
    return bundle


@dataclass
class RelatorioCIEVS:
    """Payload institucional do Radar LACEN (alerta CIEVS)."""

    orgaos: Sequence[str] = ORGAOS
    gerado_em: str = ""
    semana_epidemiologica: str = "—"
    leitura_situacional: str = "rede estável"
    dashboard_url: str = DASHBOARD_URL
    # KPIs executivos
    kpi_positivos_se: str = "—"
    kpi_variacao_pct: str = "—"
    kpi_tat_p50: str = "—"
    kpi_tat_p90: str = "—"
    kpi_pct_48h: str = "—"
    kpi_pressao_max: str = "—"
    kpi_silencios: str = "—"
    kpi_confirmacao: str = "—"
    kpi_exames_se: str = "—"
    kpi_municipios_exame: str = "—"
    # Bloco A
    top_positivos: list[dict[str, str]] = field(default_factory=list)
    variacao_se: str = "—"
    n_primeira_deteccao_alerta: int = 0
    top_divergencias: list[dict[str, str]] = field(default_factory=list)
    # Bloco E — Briefing epidemiológico (5 perguntas)
    briefing_mais_solicitados: list[dict[str, str]] = field(default_factory=list)
    briefing_maior_positividade: list[dict[str, str]] = field(default_factory=list)
    briefing_localidades: list[dict[str, str]] = field(default_factory=list)
    briefing_vizinhos: list[dict[str, str]] = field(default_factory=list)
    briefing_risco: list[dict[str, str]] = field(default_factory=list)
    cartoes_risco: list[dict[str, str]] = field(default_factory=list)
    briefing_gal_sinan: list[dict[str, str]] = field(default_factory=list)
    briefing_geo_nivel: str = "municipio"
    briefing_geo_nota: str = ""
    briefing_geo_hotspots: list[dict[str, str]] = field(default_factory=list)
    briefing_cruzamento: list[dict[str, str]] = field(default_factory=list)
    briefing_cruzamento_sih_sia: list[dict[str, str]] = field(default_factory=list)
    briefing_cruzamento_sih_sia_caveat: str = ""
    internacoes_por_agravo: list[dict[str, str]] = field(default_factory=list)
    briefing_sinais_rede: dict[str, Any] = field(default_factory=dict)
    briefing_nota_igg: str = ""
    briefing_fontes: list[str] = field(default_factory=list)
    score_prioridade: list[dict[str, str]] = field(default_factory=list)
    canal_endemico: list[dict[str, str]] = field(default_factory=list)
    marcadores_top: list[dict[str, str]] = field(default_factory=list)
    lacunas_vigilancia: list[dict[str, str]] = field(default_factory=list)
    alertas_especificos: list[str] = field(default_factory=list)
    nota_marcadores: str = ""
    # Bloco F — Parecer VE (IA + Guia MS) opcional
    ve_resumo: str = ""
    ve_casos: list[dict[str, str]] = field(default_factory=list)
    ve_recomendacoes: list[dict[str, str]] = field(default_factory=list)
    ve_arquivos: list[str] = field(default_factory=list)
    ve_usou_llm: bool = False
    # Bloco B
    tat_mediano: str = "—"
    tat_p90: str = "—"
    pct_48h: str = "—"
    top_pressao: list[dict[str, str]] = field(default_factory=list)
    silencio_vizinho_quente: list[dict[str, str]] = field(default_factory=list)
    sla_por_familia: list[dict[str, str]] = field(default_factory=list)
    contagem_faixa_pressao: list[dict[str, str]] = field(default_factory=list)
    # Bloco C
    fila_acoes: list[dict[str, str]] = field(default_factory=list)
    preditos_alta: list[dict[str, str]] = field(default_factory=list)
    pressao_predita_top: list[dict[str, str]] = field(default_factory=list)
    contagem_banda_risco: list[dict[str, str]] = field(default_factory=list)
    # Bloco D
    cobertura_municipios: str = "—"
    confirmacao_alertas: str = "—"
    crs_top: list[dict[str, str]] = field(default_factory=list)
    aviso_atraso: str = ""
    # Fontes
    fonte_primaria: str = "—"
    fontes_presentes: list[str] = field(default_factory=list)
    banner_fonte: str = ""
    nota: str = (
        "Relatório agregado — rótulos Observado / Derivado / Predito. "
        "Sem PII ou microdados nominais."
    )

    def __post_init__(self) -> None:
        if not self.gerado_em:
            self.gerado_em = (
                datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
            )


def _fmt_se(year: int, week: int) -> str:
    return f"{int(year)}-SE{int(week):02d}"


def _parse_se(se: str) -> tuple[int, int] | None:
    if not se or "-SE" not in se:
        return None
    try:
        year_s, week_s = se.split("-SE", 1)
        return int(year_s), int(week_s)
    except ValueError:
        return None


def _week_totals(
    parsed: list[tuple[int, int, str, float, float, str]], year: int, week: int
) -> tuple[float, float, int]:
    pos = tests = 0.0
    muns: set[str] = set()
    for y, w, mun, p, t, _fam in parsed:
        if y != year or w != week:
            continue
        pos += p
        tests += t
        muns.add(mun)
    return pos, tests, len(muns)


def _week_incomplete(
    cur_tests: float,
    cur_pos: float,
    prev_tests: float | None,
    prev_pos: float | None,
) -> bool:
    """SE corrente parece parcial/atrasada vs a SE imediatamente anterior."""
    if prev_tests is None or prev_tests <= 0:
        return False
    prev_p = prev_pos or 0.0
    if cur_tests < 50 and prev_tests >= 50:
        return True
    if cur_tests < 0.25 * prev_tests:
        return True
    if cur_pos < 5 and prev_p >= 5 and cur_tests < 0.5 * prev_tests:
        return True
    return False


def _parse_integrated_weekly(
    src: RelatorioSources,
) -> list[tuple[int, int, str, float, float, str]]:
    """Linhas (ano, SE, mun, positivos, testes, familia) com exames > 0."""
    parsed: list[tuple[int, int, str, float, float, str]] = []
    for r in src.get("integrated_weekly"):
        tests = _num(r.get("tests"), 0) or 0
        if tests <= 0:
            continue
        y = _num(r.get("epi_year"))
        w = _num(r.get("epi_week"))
        if y is None or w is None:
            continue
        mun = _cell(r, "municipio", default="")
        if not mun or mun.startswith("*"):
            continue
        pos = _num(r.get("positives"), 0) or 0
        fam = _cell(r, "familia", "target", default="—")
        parsed.append((int(y), int(w), mun, pos, tests, fam))
    return parsed


def _pick_se_lab(
    parsed: list[tuple[int, int, str, float, float, str]],
) -> dict[str, Any]:
    """
    Escolhe UMA SE de referência lab-epi (série integrated_weekly).

    Prefere a última SE completa; se a mais recente estiver parcial,
    usa a anterior e marca meta para aviso.
    """
    weeks = sorted({(y, w) for y, w, *_ in parsed})
    if not weeks:
        return {
            "se": None,
            "prev": None,
            "latest": None,
            "usou_completa": False,
            "se_parcial": None,
        }
    latest = weeks[-1]
    prev = weeks[-2] if len(weeks) >= 2 else None
    cur_pos, cur_tests, _ = _week_totals(parsed, latest[0], latest[1])
    prev_pos = prev_tests = None
    if prev:
        prev_pos, prev_tests, _ = _week_totals(parsed, prev[0], prev[1])
    incomplete = _week_incomplete(cur_tests, cur_pos, prev_tests, prev_pos)
    if incomplete and prev is not None:
        return {
            "se": prev,
            "prev": weeks[-3] if len(weeks) >= 3 else None,
            "latest": latest,
            "usou_completa": True,
            "se_parcial": latest,
            "parcial_pos": cur_pos,
            "parcial_tests": cur_tests,
        }
    return {
        "se": latest,
        "prev": prev,
        "latest": latest,
        "usou_completa": False,
        "se_parcial": None,
    }


def _semana_ref(src: RelatorioSources, se_lab: str | None = None) -> str:
    """SE única do relatório: lab-epi (integrated_weekly) tem prioridade."""
    if se_lab and se_lab != "—":
        return se_lab
    parsed = _parse_integrated_weekly(src)
    if parsed:
        pick = _pick_se_lab(parsed)
        if pick.get("se"):
            return _fmt_se(*pick["se"])
    for key in (
        "executive_state",
        "indicadores_emergencia",
        "emergencia_confirmacao_resumo",
    ):
        for r in src.get(key, 5):
            y = _cell(r, "epi_year_max", "epi_year_ref", "epi_year", default="")
            w = _cell(
                r,
                "epi_week_max",
                "epi_week_ref",
                "epi_week",
                "semana_epidemiologica",
                default="",
            )
            if y and y != "—" and w and w != "—":
                try:
                    return f"{int(float(y))}-SE{int(float(w)):02d}"
                except ValueError:
                    return f"{y}-SE{w}"
    se_iso = src.dw_enrich.get("se_iso")
    if se_iso:
        return str(se_iso)
    return "—"


def _leitura_situacional(resumo: dict, rede: dict, n_pressao: int, n_silencio: int) -> str:
    pct48 = _num(resumo.get("kpi_pct_liberado_48h") or rede.get("pct_liberado_48h_mediano"))
    pressao = _num(resumo.get("kpi_indice_pressao_rede"))
    n_sla = int(_num(resumo.get("n_municipios_sla_crise"), 0) or 0)
    n_alta = int(_num(resumo.get("n_municipios_pressao_alta_critica"), 0) or 0)
    n_div = int(_num(resumo.get("kpi_n_divergencia_gal_notif"), 0) or 0)

    if n_alta >= 15 or (pressao is not None and pressao >= 55) or (
        pct48 is not None and pct48 < 0.4 and n_sla >= 40
    ):
        return "rede sob pressão"
    if n_div >= 50 or n_silencio >= 5 or (n_pressao >= 3 and n_div >= 20):
        return "dispersão territorial"
    return "rede estável"


def _top_positivos(
    src: RelatorioSources, top_n: int = 5
) -> tuple[list[dict[str, str]], str, dict[str, str], dict[str, Any]]:
    """
    Top municípios + variação SE + KPIs de volume — todos na MESMA SE lab.

    Retorna (top, texto_variacao, kpis, meta) onde meta inclui se_iso e flags
    de SE parcial/completa para o aviso de atraso.
    """
    kpis = {
        "positivos_se": "—",
        "variacao_pct": "—",
        "exames_se": "—",
        "municipios": "—",
    }
    meta: dict[str, Any] = {
        "se_iso": "—",
        "cur_pos": None,
        "cur_tests": None,
        "prev_pos": None,
        "prev_tests": None,
        "usou_completa": False,
        "se_parcial": None,
    }
    parsed = _parse_integrated_weekly(src)
    if not parsed:
        tgt = src.get("integrated_target_summary")
        agg: dict[str, dict[str, float]] = {}
        for r in tgt:
            mun = _cell(r, "municipio", default="")
            if not mun or mun.startswith("*"):
                continue
            pos = _num(r.get("positivos"), 0) or 0
            tests = _num(r.get("testes"), 0) or 0
            a = agg.setdefault(mun, {"positivos": 0.0, "testes": 0.0})
            a["positivos"] += pos
            a["testes"] += tests
        ranked = sorted(agg.items(), key=lambda x: x[1]["positivos"], reverse=True)[:top_n]
        out = []
        for mun, a in ranked:
            posi = (a["positivos"] / a["testes"]) if a["testes"] else None
            out.append(
                {
                    "municipio": mun,
                    "positivos": _fmt_num(a["positivos"], 0),
                    "positividade": _fmt_pct(posi),
                    "familia": "—",
                    "tipo_sinal": "Observado",
                }
            )
        return out, "variação SE: indisponível (sem série semanal)", kpis, meta

    pick = _pick_se_lab(parsed)
    if not pick.get("se"):
        return [], "variação SE: sem exames na série", kpis, meta

    cur_y, cur_w = pick["se"]
    prev = pick.get("prev")
    meta["se_iso"] = _fmt_se(cur_y, cur_w)
    meta["usou_completa"] = bool(pick.get("usou_completa"))
    meta["se_parcial"] = (
        _fmt_se(*pick["se_parcial"]) if pick.get("se_parcial") else None
    )
    meta["parcial_pos"] = pick.get("parcial_pos")
    meta["parcial_tests"] = pick.get("parcial_tests")
    meta["latest_iso"] = (
        _fmt_se(*pick["latest"]) if pick.get("latest") else meta["se_iso"]
    )

    def _agg_mun(year: int, week: int) -> dict[str, dict[str, Any]]:
        """Agrega município na SE; família = aquela com mais positivos."""
        out: dict[str, dict[str, Any]] = {}
        fam_pos: dict[str, dict[str, float]] = {}
        for y, w, mun, pos, tests, fam in parsed:
            if y != year or w != week:
                continue
            a = out.setdefault(mun, {"positivos": 0.0, "testes": 0.0, "familia": fam})
            a["positivos"] += pos
            a["testes"] += tests
            fp = fam_pos.setdefault(mun, {})
            fp[fam] = fp.get(fam, 0.0) + pos
        for mun, a in out.items():
            fp = fam_pos.get(mun) or {}
            if fp:
                a["familia"] = max(fp.items(), key=lambda x: x[1])[0]
        return out

    cur_agg = _agg_mun(cur_y, cur_w)
    cur_pos = sum(float(v["positivos"]) for v in cur_agg.values())
    cur_tests = sum(float(v["testes"]) for v in cur_agg.values())
    meta["cur_pos"] = cur_pos
    meta["cur_tests"] = cur_tests

    # Top = subset da mesma SE (só com positivos > 0; senão top por exames)
    with_pos = {m: a for m, a in cur_agg.items() if a["positivos"] > 0}
    pool = with_pos if with_pos else cur_agg
    ranked = sorted(
        pool.items(),
        key=lambda x: (x[1]["positivos"], x[1]["testes"]),
        reverse=True,
    )[:top_n]
    out_list: list[dict[str, str]] = []
    for mun, a in ranked:
        posi = (a["positivos"] / a["testes"]) if a["testes"] else None
        out_list.append(
            {
                "municipio": mun,
                "positivos": _fmt_num(a["positivos"], 0),
                "positividade": _fmt_pct(posi),
                "familia": str(a.get("familia") or "—"),
                "tipo_sinal": "Observado",
            }
        )

    kpis["positivos_se"] = _fmt_num(cur_pos, 0)
    kpis["exames_se"] = _fmt_num(cur_tests, 0)
    kpis["municipios"] = _fmt_num(len(cur_agg), 0)

    if prev:
        prev_agg = _agg_mun(prev[0], prev[1])
        prev_pos = sum(float(v["positivos"]) for v in prev_agg.values())
        prev_tests = sum(float(v["testes"]) for v in prev_agg.values())
        meta["prev_pos"] = prev_pos
        meta["prev_tests"] = prev_tests
        if prev_pos > 0:
            delta = (cur_pos - prev_pos) / prev_pos
            kpis["variacao_pct"] = f"{delta:+.0%}".replace(".", ",")
            variacao = (
                f"Observado: positivos estaduais SE{cur_w:02d}={_fmt_num(cur_pos, 0)} "
                f"vs SE{prev[1]:02d}={_fmt_num(prev_pos, 0)} ({delta:+.0%})"
            )
        else:
            variacao = (
                f"Observado: positivos SE{cur_w:02d}={_fmt_num(cur_pos, 0)}; "
                f"SE anterior sem base"
            )
    else:
        variacao = (
            f"Observado: positivos SE{cur_w:02d}={_fmt_num(cur_pos, 0)} "
            f"(sem SE anterior)"
        )

    return out_list, variacao, kpis, meta


def _count_primeira_deteccao(src: RelatorioSources, se_ref: str) -> int:
    """
    Municípios com 1ª positividade na SE de referência (série integrated_weekly):
    positives>0 na SE ref e zero positivos em todas as SE anteriores da série,
    entre municípios com exames>0 na SE ref.
    """
    yw = _parse_se(se_ref)
    parsed = _parse_integrated_weekly(src)
    if yw and parsed:
        year, week = yw
        first_pos: dict[str, tuple[int, int]] = {}
        exams_ref: set[str] = set()
        for y, w, mun, pos, _tests, _fam in parsed:
            key = mun.upper()
            if (y, w) == (year, week):
                exams_ref.add(key)
            if pos <= 0:
                continue
            cur = (y, w)
            if key not in first_pos or cur < first_pos[key]:
                first_pos[key] = cur
        return sum(1 for mun in exams_ref if first_pos.get(mun) == (year, week))

    # Fallback: só sinais explicitamente de 1ª detecção na fila
    fila = src.get("fila_operacional")
    if not fila:
        return 0
    return sum(
        1
        for r in fila
        if "primeira" in _cell(r, "sinal").lower()
        or "1ª" in _cell(r, "sinal").lower()
        or "1a " in _cell(r, "sinal").lower()
    )


def _aviso_atraso_bases(
    src: RelatorioSources, meta: dict[str, Any], se_ref: str
) -> str:
    """
    Aviso só quando há motivo explícito:
    (a) SE ref ≠ última SE da série porque a mais recente ainda é parcial
    (b) exames na SE com positivos ~0 enquanto SE anterior tinha muitos
    (c) DW max(Data_Liberacao) atrasado > N dias
    (d) validacao_etl: atraso_se > 0 (SE usada vs esperada)
    """
    reasons: list[str] = []
    if meta.get("usou_completa") and meta.get("se_parcial"):
        reasons.append(
            f"SE {meta['se_parcial']} ainda parcial na série lab "
            f"({_fmt_num(meta.get('parcial_tests'), 0)} exames / "
            f"{_fmt_num(meta.get('parcial_pos'), 0)} pos.) — "
            f"referência = {se_ref} (última completa)"
        )

    cur_pos = meta.get("cur_pos")
    cur_tests = meta.get("cur_tests")
    prev_pos = meta.get("prev_pos")
    if (
        cur_pos is not None
        and cur_tests is not None
        and prev_pos is not None
        and cur_tests >= 20
        and cur_pos < 5
        and prev_pos >= 10
    ):
        reasons.append(
            f"positivos SE ref={_fmt_num(cur_pos, 0)} com "
            f"{_fmt_num(cur_tests, 0)} exames, vs SE anterior "
            f"{_fmt_num(prev_pos, 0)} pos. — possível atraso de liberação"
        )

    lag = src.dw_enrich.get("dw_lag_dias")
    if isinstance(lag, (int, float)) and lag > 14:
        reasons.append(
            f"DW VW_GAL: última Data_Liberacao há {int(lag)} dias "
            f"(limiar 14d)"
        )

    atraso_se = src.etl_atraso_se
    if isinstance(atraso_se, int) and atraso_se > 0:
        se_esp = str((src.etl_meta or {}).get("se_esperada") or "—")
        se_usada = str((src.etl_meta or {}).get("se_usada") or se_ref)
        reasons.append(
            f"SE ref {se_usada} atrasada {atraso_se} SE vs esperada {se_esp}"
        )

    if reasons:
        return "Atenção: " + "; ".join(reasons) + "."
    # Não reutilizar banner de fonte (ex.: falso DW indisponível) como atraso
    banner = (src.banner or "").strip()
    if banner and "indispon" not in banner.casefold() and "Espelhos lacen_*" not in banner:
        return banner
    return ""


def _top_divergencias(src: RelatorioSources, top_n: int = 5) -> list[dict[str, str]]:
    emerg = src.get("indicadores_emergencia")
    rows = [r for r in emerg if _truthy(r.get("divergencia_gal_notif"))]
    qual = {
        _cell(r, "municipio").upper(): r for r in src.get("qualidade_dado")
    }

    def _rank_key(r: dict) -> tuple:
        mun = _cell(r, "municipio").upper()
        q = qual.get(mun, {})
        gap = 1 if _truthy(q.get("gap_sinan_sem_exame")) else 0
        notif = _num(q.get("notif_sinan"), 0) or 0
        exames = _num(q.get("exames") or r.get("exames"), 0) or 0
        return (-gap, -notif, exames)

    rows = sorted(rows, key=_rank_key)[:top_n]
    out = []
    for r in rows:
        mun = _cell(r, "municipio")
        q = qual.get(mun.upper(), {})
        out.append(
            {
                "municipio": mun,
                "tipo": _cell(r, "tipo_divergencia", default="GAL×SINAN"),
                "notif_sinan": _fmt_num(_num(q.get("notif_sinan")), 0),
                "exames": _fmt_num(_num(q.get("exames") or r.get("exames")), 0),
                "tipo_sinal": "Observado",
            }
        )
    return out


def _sla_familia(src: RelatorioSources, top_n: int = 5) -> list[dict[str, str]]:
    rows = src.get("indicadores_emergencia_familia") or src.get(
        "indicadores_rede_por_familia"
    )
    fam = [
        r
        for r in rows
        if _cell(r, "granularidade") in ("familia", "—", "")
        or _cell(r, "municipio") in ("ESTADO_MT", "ESTADO", "—", "")
    ]
    fam = sorted(fam, key=lambda r: _num(r.get("exames"), 0) or 0, reverse=True)[:top_n]
    out = []
    for r in fam:
        out.append(
            {
                "familia": _cell(r, "familia"),
                "exames": _fmt_num(_num(r.get("exames")), 0),
                "pct_48h": _fmt_pct(_num(r.get("pct_liberado_48h"))),
                "tat_p90": _fmt_num(_num(r.get("tat_p90_dias")), 1),
                "sla_crise": "sim" if _truthy(r.get("sla_crise")) else "não",
            }
        )
    return out


def _contagem_campo(
    rows: list[dict], field: str, aliases: Sequence[str] = ()
) -> list[dict[str, str]]:
    keys = (field, *aliases)
    counts: dict[str, int] = {}
    for r in rows:
        val = _cell(r, *keys, default="")
        if not val or val == "—":
            continue
        counts[val] = counts.get(val, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    return [{"banda": k, "n": _fmt_num(v, 0)} for k, v in ranked]


def _bloco_rede(
    src: RelatorioSources,
) -> tuple[str, str, str, list[dict], list[dict], dict, dict, str, str]:
    resumo_rows = src.get("indicadores_emergencia_resumo", 1)
    rede_rows = src.get("indicadores_rede_resumo", 1)
    resumo = resumo_rows[0] if resumo_rows else {}
    rede = rede_rows[0] if rede_rows else {}

    tat_med = _fmt_num(
        _num(rede.get("tat_mediano_estadual") or resumo.get("kpi_tat_mediano")), 1
    )
    tat_p90 = _fmt_num(
        _num(resumo.get("kpi_tat_p90_dias") or rede.get("tat_p90_estadual")), 1
    )
    pct48 = _fmt_pct(
        _num(resumo.get("kpi_pct_liberado_48h") or rede.get("pct_liberado_48h_mediano"))
    )
    pressao_max = _fmt_num(_num(resumo.get("kpi_indice_pressao_rede")), 1)

    emerg = src.get("indicadores_emergencia")
    pressao_rows = sorted(
        [
            r
            for r in emerg
            if any(
                x in _cell(r, "faixa_pressao").lower()
                for x in ("alta", "critic", "crít")
            )
        ],
        key=lambda r: _num(r.get("indice_pressao_rede"), 0) or 0,
        reverse=True,
    )[:5]
    top_pressao = []
    for r in pressao_rows:
        top_pressao.append(
            {
                "municipio": _cell(r, "municipio"),
                "faixa": _cell(r, "faixa_pressao"),
                "indice": _fmt_num(_num(r.get("indice_pressao_rede")), 1),
                "backlog": _fmt_num(_num(r.get("backlog_estimado")), 0),
                "rejeicao": _fmt_pct(_num(r.get("pct_rejeitado"))),
                "tipo_sinal": "Derivado",
            }
        )
    if top_pressao:
        pressao_max = top_pressao[0]["indice"]

    viz_map: dict[str, list[str]] = {}
    for r in src.get("municipio_vizinhos"):
        mun = _cell(r, "municipio", default="").upper()
        viz = _cell(r, "vizinho", "municipio_vizinho", "neighbor", default="")
        if mun and viz:
            viz_map.setdefault(mun, []).append(viz)

    pressao_by_mun = {
        _cell(r, "municipio").upper(): r
        for r in emerg
        if _cell(r, "municipio") != "—"
    }

    silencio_rows = [
        r
        for r in emerg
        if _truthy(r.get("silencio_gal_alerta"))
        or _truthy(r.get("silencio_gal_vs_vizinhos"))
    ]
    silencio_out: list[dict[str, str]] = []
    for r in silencio_rows:
        mun = _cell(r, "municipio")
        hot = []
        for v in viz_map.get(mun.upper(), []):
            pr = pressao_by_mun.get(v.upper())
            if not pr:
                continue
            faixa = _cell(pr, "faixa_pressao").lower()
            if any(x in faixa for x in ("alta", "critic", "crít", "moder")):
                hot.append(f"{v}({_cell(pr, 'faixa_pressao')})")
        flag_viz = _truthy(r.get("silencio_gal_vs_vizinhos"))
        silencio_out.append(
            {
                "municipio": mun,
                "tipo_silencio": _cell(r, "tipo_silencio_gal", default="silêncio GAL"),
                "vizinho_quente": (
                    ", ".join(hot[:3])
                    if hot
                    else ("marcado" if flag_viz else "não identificado")
                ),
                "tipo_sinal": "Observado",
            }
        )
    silencio_out = silencio_out[:5]
    n_sil = _fmt_num(
        _num(resumo.get("kpi_n_silencio_gal"), len(silencio_out)) or len(silencio_out),
        0,
    )

    return tat_med, tat_p90, pct48, top_pressao, silencio_out, resumo, rede, pressao_max, n_sil


def _fila_acoes(
    src: RelatorioSources, top_n: int = 10, mun_crs: dict[str, str] | None = None
) -> list[dict[str, str]]:
    mun_crs = mun_crs or {}
    rows = src.get("fila_operacional", top_n)
    out = []
    for r in rows[:top_n]:
        sinal = _cell(r, "sinal")
        tipo = (
            "Predito"
            if "predit" in sinal.lower()
            else (
                "Derivado"
                if any(x in sinal.lower() for x in ("pressao", "pressão", "sla"))
                else "Observado"
            )
        )
        mun = _cell(r, "municipio")
        acao = _cell(r, "acao_sugerida")
        if len(acao) > 100:
            acao = acao[:99] + "…"
        out.append(
            {
                "municipio": mun,
                "crs": mun_crs.get(mun.upper(), "—"),
                "sinal": sinal,
                "banda": _cell(r, "prioridade"),
                "acao": acao,
                "responsavel": _cell(r, "responsavel"),
                "prazo": _cell(r, "prazo_acao"),
                "tipo_sinal": tipo,
            }
        )
    return out


def _driver_is_infra_only(raw_driver: str, humanized: str = "") -> bool:
    """True se os drivers principais são CNES/infra (pouco útil p/ VE)."""
    human = (humanized or "").casefold().strip()
    raw = (raw_driver or "").casefold().strip()
    blob = f"{raw} {human}".strip()
    if not blob or blob in ("—", "-", "fatores de risco (modelo)"):
        return True
    # Avalia sobretudo o texto humanizado (top features) — evita `tests_ma8`
    # enterrado no raw anular o filtro de CNES.
    focus = human if human and human not in ("—", "-") else blob
    infra = bool(
        re.search(
            r"cnes_|estabelecimentos\s+cnes|leitos\s+cnes|equipes\s+esf|"
            r"\bcnes\b|populacao|popula[cç][aã]o",
            focus,
        )
    )
    disease = bool(
        re.search(
            r"positiv|exames?\b|notif|tat_|backlog|press[aã]o|sil[eê]ncio|"
            r"risco_composto|semana|incidencia|incid[eê]ncia|agravo|dengue|"
            r"tubercul|hepatite|mening|(?<![a-z])tests(?![a-z_])",
            focus,
        )
    )
    if infra and not disease:
        return True
    # Top humanizado só CNES/leitos/ESF → infra mesmo com ruído no raw
    parts = [p.strip() for p in focus.split(";") if p.strip()]
    if parts and all(
        re.search(r"cnes|estabelecimento|leitos|equipes\s+esf|popula", p)
        for p in parts[:2]
    ):
        return True
    return False


def _preditos_alta(src: RelatorioSources, top_n: int = 5) -> list[dict[str, str]]:
    risco = src.get("ml_risco_predito")
    se = _semana_ref(src)
    year = week = None
    if "-SE" in se:
        try:
            ys, ws = se.split("-SE", 1)
            year, week = int(ys), int(ws)
        except ValueError:
            pass

    filtered = []
    for r in risco:
        banda = _cell(r, "banda_risco", "faixa_predita", "nivel_risco", "risco")
        if not any(x in banda.lower() for x in ("alta", "alto", "critic", "crít", "muito")):
            continue
        r = dict(r)
        if year is not None and week is not None:
            y = _num(r.get("epi_year"))
            w = _num(r.get("epi_week"))
            r["_se_match"] = (
                1
                if y is not None and w is not None and (int(y), int(w)) == (year, week)
                else 0
            )
        else:
            r["_se_match"] = 0
        filtered.append(r)

    if any(r.get("_se_match") == 1 for r in filtered):
        filtered = [r for r in filtered if r.get("_se_match") == 1]

    filtered = sorted(
        filtered,
        key=lambda r: _num(
            r.get("prob_alerta_proxima_janela")
            or r.get("prob")
            or r.get("risco_composto")
            or r.get("score"),
            0,
        )
        or 0,
        reverse=True,
    )

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in filtered:
        mun = _cell(r, "municipio")
        fam = _cell(r, "familia", "target", "agravo_alvo")
        key = f"{mun}|{fam}"
        if key in seen:
            continue
        raw_drv = _cell(r, "drivers", "driver", "motivo")
        human = _humanize_driver(raw_drv)
        # Não expor CNES/infra como “drivers”; texto plano no alerta.
        if _driver_is_infra_only(raw_drv, human):
            driver_txt = ""
        else:
            driver_txt = human if human not in {"—", "-"} else ""
        seen.add(key)
        out.append(
            {
                "municipio": mun,
                "banda": _cell(r, "banda_risco", "faixa_predita", "nivel_risco"),
                "familia": fam,
                "driver": driver_txt,
                "prob": _fmt_pct(
                    _num(r.get("prob_alerta_proxima_janela") or r.get("prob")), 0
                ),
                "tipo_sinal": "Predito",
            }
        )
        if len(out) >= top_n:
            break
    return out


def _load_ve_acoes_csv(outdir: Path, max_n: int = 8) -> list[dict[str, str]]:
    """Lê relatorio_ve_acoes.csv e diversifica por destinatário."""
    path = Path(outdir) / "relatorio_ve_acoes.csv"
    rows = _read_csv(path)
    if not rows:
        return []
    sev_rank = {"critica": 0, "crítica": 0, "alta": 1, "media": 2, "média": 2, "baixa": 3}

    def _dest_prio(dest: str) -> int:
        d = (dest or "").casefold()
        if d.startswith("cievs"):
            return 0
        if d.startswith("ses"):
            return 1
        if d.startswith("área") or d.startswith("area"):
            return 2
        if d.startswith("munic"):
            return 3
        return 5

    ranked = sorted(
        rows,
        key=lambda r: (
            sev_rank.get(str(r.get("severidade") or "").casefold(), 9),
            _dest_prio(str(r.get("destinatario") or "")),
            str(r.get("destinatario") or ""),
        ),
    )
    seen_dest: set[str] = set()
    out: list[dict[str, str]] = []
    for r in ranked:
        dest = _cell(r, "destinatario", "area", default="")
        if not dest or dest == "—":
            continue
        dest_key = dest.split("—")[0].split("-")[0].strip().casefold()[:24]
        # no máximo 1 por família de destinatário (SES / CIEVS / Área / Município…)
        if dest_key in seen_dest:
            continue
        seen_dest.add(dest_key)
        acao = _cell(r, "recomendacao", "acao")
        if len(acao) > 160:
            acao = acao[:159] + "…"
        out.append(
            {
                "area": dest,
                "acao": acao,
                "prazo": _cell(r, "prazo", default=""),
                "agravo": _cell(r, "agravo", "target", default=""),
                "severidade": _cell(r, "severidade", default=""),
            }
        )
        if len(out) >= max_n:
            break
    return out


def _juina_hbv_line(ve_casos: list[dict[str, str]], ve_resumo: str = "") -> str:
    """Uma linha clara: Juína HBV — investigar, não surto."""
    for c in ve_casos:
        mun = str(c.get("municipio") or "").upper()
        tgt = str(c.get("target") or "").casefold()
        if "JUINA" in mun and "hepatite" in tgt:
            return (
                f"Juína hepatite B: {c.get('exames')} exames / +{c.get('positivos')} "
                f"({c.get('positividade')}) — sinal a investigar (Guia MS); "
                f"não declarar surto/epidemia automaticamente."
            )
    try:
        from lacen_agente_ve import juina_hbv_one_liner

        line = juina_hbv_one_liner(None)
        if line and "Juína" in line:
            # Encurtar para Telegram
            if len(line) > 200:
                return (
                    "Juína hepatite B: sinal a investigar — estratificar "
                    "marcador agudo×crônico (Guia MS); não declarar surto automático."
                )
            return line
    except Exception:
        pass
    if ve_resumo and "JUINA" in ve_resumo.upper() and "hepatite" in ve_resumo.casefold():
        return (
            "Juína hepatite B: sinal a investigar; "
            "não declarar surto automático (Guia MS)."
        )
    return ""


def _parecer_alerta_line(
    ve_casos: list[dict[str, str]], ve_resumo: str = ""
) -> str:
    """Parecer curto: prioriza Juína HBV; senão 1º caso VE / resumo."""
    juina = _juina_hbv_line(ve_casos, ve_resumo)
    if juina:
        return juina
    if ve_casos:
        c = ve_casos[0]
        mun = str(c.get("municipio") or "—")
        tgt = str(c.get("target") or c.get("titulo") or "agravo")
        ver = str(c.get("veredito") or "").strip()
        if ver and len(ver) > 120:
            ver = ver[:119] + "…"
        base = (
            f"{mun}×{tgt}: {c.get('exames')} ex. / +{c.get('positivos')} "
            f"({c.get('positividade')})"
        )
        if ver:
            return f"{base} — {ver}"
        return f"{base} — sinal a investigar (Guia MS)."
    if ve_resumo:
        return ve_resumo.strip()[:220]
    return ""


def _parse_delta_pct(raw: Any) -> float | None:
    s = str(raw or "").strip().replace("%", "").replace(",", ".")
    if not s or s in {"—", "-", "n/d", "nan"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _nome_agravo_pt(raw: str) -> str:
    """Rótulo legível do agravo (sem códigos técnicos)."""
    t = (raw or "").strip()
    if not t or t in {"—", "-"}:
        return "agravo"
    low = t.casefold().replace("-", "_")
    mapping = (
        (("hepatite_b", "hbv", "hbsag"), "hepatite B"),
        (("hepatite_c", "hcv"), "hepatite C"),
        (("hepatite_a",), "hepatite A"),
        (("hepatite",), "hepatite"),
        (("tubercul", "tb_"), "tuberculose"),
        (("dengue",), "dengue"),
        (("chikung",), "chikungunya"),
        (("zika",), "zika"),
        (("arbovir",), "arbovirose"),
        (("mening",), "meningite"),
        (("sars", "covid", "cov_2", "cov2"), "COVID-19"),
        (("respirat", "srag", "influenza"), "síndrome respiratória"),
        (("malaria", "malária"), "malária"),
    )
    for keys, label in mapping:
        if any(k in low for k in keys):
            return label
    return t.replace("_", " ")


def _suavizar_texto_alerta(texto: str) -> str:
    """Remove jargão residual em recomendações/parecer."""
    t = texto or ""
    repl = (
        ("GAL×SINAN", "exame × notificação"),
        ("GAL x SINAN", "exame × notificação"),
        ("gal_sem_sinan", "exame sem notificação"),
        ("sinan_sem_gal", "notificação sem exame"),
        ("hepatite_b_hbv", "hepatite B"),
        ("hepatite_c_hcv", "hepatite C"),
        ("Observado", "dado observado"),
        ("Predito", "risco previsto"),
        ("SE-1", "semana anterior"),
        ("SE-2", "duas semanas atrás"),
        ("CRS", "regional"),
        ("VE municipal", "vigilância municipal"),
        ("Δ%", "variação"),
        ("TAT", "tempo de liberação"),
        ("backlog", "fila"),
    )
    for a, b in repl:
        t = t.replace(a, b)
    t = re.sub(r"\bSE\s*20\d{2}-SE\d{2}\b", "semana de referência", t, flags=re.I)
    t = re.sub(r"\s*↔\s*", " e ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def _mun_titulo(mun: str) -> str:
    m = (mun or "").strip()
    if not m:
        return "—"
    # Mantém preposições minúsculas em nomes BR
    parts = m.replace("_", " ").title().split()
    small = {"De", "Da", "Do", "Das", "Dos", "E"}
    out = [p.lower() if p in small and i > 0 else p for i, p in enumerate(parts)]
    s = " ".join(out)
    fixes = {
        "Cuiaba": "Cuiabá",
        "Varzea Grande": "Várzea Grande",
        "Rondonopolis": "Rondonópolis",
        "Tangara Da Serra": "Tangará da Serra",
        "Juina": "Juína",
        "Caceres": "Cáceres",
    }
    return fixes.get(s, s)


def _fmt_variacao_pt(delta_pct: Any, tendencia: Any = "") -> str:
    """Converte Δ%/+161.7% → 'subiu 162% vs semana anterior'."""
    d = _parse_delta_pct(delta_pct)
    tend = str(tendencia or "").strip()
    if d is None:
        if tend in {"↑", "^", "alta", "up"}:
            return "em alta vs semana anterior"
        if tend in {"↓", "v", "baixa", "down"}:
            return "em baixa vs semana anterior"
        return "vs semana anterior"
    abs_d = abs(d)
    pct = f"{abs_d:.0f}".replace(".", ",") if abs_d >= 10 else f"{abs_d:.1f}".replace(".", ",")
    if d >= 8:
        return f"subiu {pct}% vs semana anterior"
    if d <= -8:
        return f"caiu {pct}% vs semana anterior"
    return f"quase estável ({'+' if d >= 0 else ''}{pct}% vs semana anterior)"


def _flag_territorio_pt(flag: str) -> str:
    f = (flag or "").casefold()
    if "gal_sem_sinan" in f or "exame" in f and "notif" in f:
        return "exame no laboratório sem notificação"
    if "sinan_sem_gal" in f:
        return "notificação sem exame no laboratório"
    if f and f not in {"—", "-", "gap"}:
        return flag.replace("_", " ")
    return "divergência exame × notificação"


def _faixa_pressao_pt(faixa: str) -> str:
    f = (faixa or "").casefold()
    if "critic" in f or "crít" in f:
        return "crítica"
    if "alta" in f or "alto" in f:
        return "alta"
    if "moder" in f:
        return "moderada"
    return (faixa or "—").replace("_", " ")


def carregar_internacoes_alerta(
    outdir: Path | str = OUTDIR_DEFAULT, *, top_por_familia: int = 5
) -> list[dict[str, str]]:
    """
    Internações por município × agravo (hepatite, tuberculose, dengue).
    Prefere cruzamento SIH top; completa com agregados semanais do staging.
    """
    stage = Path(outdir) / "staging_dw"
    familias_alvo = ("hepatite", "tuberculose", "dengue_arbovirose", "dengue")
    labels = {
        "hepatite": "hepatite",
        "tuberculose": "tuberculose",
        "dengue_arbovirose": "dengue",
        "dengue": "dengue",
    }
    agg: dict[tuple[str, str], float] = {}

    def _acc(mun: str, fam_raw: str, n: float) -> None:
        mun_u = (mun or "").strip().upper()
        if not mun_u or mun_u in {"—", "-"}:
            return
        low = (fam_raw or "").casefold()
        fam_key = ""
        if "hepat" in low:
            fam_key = "hepatite"
        elif "tuber" in low:
            fam_key = "tuberculose"
        elif "dengue" in low or "arbov" in low:
            fam_key = "dengue"
        else:
            return
        key = (fam_key, mun_u)
        agg[key] = agg.get(key, 0.0) + n

    top_csv = stage / "cruzamento_sih_sia_top_mun.csv"
    for r in _read_csv(top_csv):
        n = _num(r.get("n"), 0) or 0
        if n <= 0:
            continue
        _acc(
            _cell(r, "municipio"),
            _cell(r, "cid_familia", "familia"),
            n,
        )

    sih_csv = stage / "sih_mun_cid_familia_agg.csv"
    # Soma janela recente por mun×família (complementa hepatite/TB pouco presentes no top dengue)
    for r in _read_csv(sih_csv):
        fam = _cell(r, "cid_familia", "familia")
        low = fam.casefold()
        if not any(x in low for x in ("hepat", "tuber", "dengue", "arbov")):
            continue
        n = _num(r.get("n_internacoes"), _num(r.get("n"), 0)) or 0
        if n <= 0:
            continue
        _acc(_cell(r, "municipio"), fam, n)

    # Se cruzamento já trouxe dengue agregada e sih somou de novo, valores podem
    # duplicar dengue — preferir o máximo por chave (já é soma do sih; top é total).
    # Re-lê top dengue como autoridade se presente.
    dengue_from_top: dict[str, float] = {}
    for r in _read_csv(top_csv):
        fam = _cell(r, "cid_familia", "familia").casefold()
        if "dengue" in fam or "arbov" in fam:
            mun = _cell(r, "municipio").upper()
            dengue_from_top[mun] = _num(r.get("n"), 0) or 0
    for mun, n in dengue_from_top.items():
        agg[("dengue", mun)] = n

    by_fam: dict[str, list[tuple[str, float]]] = {
        "hepatite": [],
        "tuberculose": [],
        "dengue": [],
    }
    for (fam, mun), n in agg.items():
        if fam in by_fam and n > 0:
            by_fam[fam].append((mun, n))

    out: list[dict[str, str]] = []
    for fam in ("hepatite", "tuberculose", "dengue"):
        ranked = sorted(by_fam[fam], key=lambda x: -x[1])[:top_por_familia]
        for mun, n in ranked:
            out.append(
                {
                    "familia": fam,
                    "familia_pt": labels.get(fam, fam),
                    "municipio": _mun_titulo(mun),
                    "municipio_key": mun,
                    "n": _fmt_num(n, 0),
                    "n_raw": str(int(n)),
                    "fonte": "internações (SIH)",
                }
            )
    return out


def _agravos_em_sinal(rel: RelatorioCIEVS) -> set[str]:
    """Famílias/agravos com sinal epidemiológico (não pressão lab genérica)."""
    out: set[str] = set()
    for c in rel.ve_casos or []:
        out.add(_nome_agravo_pt(str(c.get("target") or "")).casefold())
    for x in rel.briefing_mais_solicitados or []:
        d = _parse_delta_pct(x.get("delta_pct"))
        tend = str(x.get("tendencia") or "")
        if (d is not None and d >= 25) or tend in {"↑", "^", "alta", "up"}:
            out.add(_nome_agravo_pt(str(x.get("target") or "")).casefold())
    for x in rel.briefing_maior_positividade or []:
        out.add(_nome_agravo_pt(str(x.get("target") or "")).casefold())
    for v in rel.briefing_vizinhos or []:
        out.add(_nome_agravo_pt(str(v.get("target") or "")).casefold())
    # Expande aliases (dengue → arbovirose) para casar com SLA por família
    expanded = set(out)
    for a in list(out):
        if any(k in a for k in ("dengue", "chikung", "zika", "oropouche")):
            expanded.add("arbovirose")
            expanded.add("dengue")
        if "hepat" in a or "hbv" in a or "hcv" in a:
            expanded.add("hepatite")
        if "tubercul" in a:
            expanded.add("tuberculose")
    return {a for a in expanded if a and a not in {"agravo", "—"}}


def _fam_casa_com_sinal(fam: str, sinais: set[str]) -> bool:
    fam_cf = (fam or "").casefold()
    if not fam_cf or fam_cf in {"outros", "outro", "agravo"}:
        return False
    if any(fam_cf in a or a in fam_cf for a in sinais):
        return True
    if any(k in fam_cf for k in ("arbov", "dengue")) and (
        "arbovirose" in sinais or "dengue" in sinais or "chikungunya" in sinais
    ):
        return True
    if "hepat" in fam_cf and any("hepat" in a for a in sinais):
        return True
    if "tuber" in fam_cf and any("tuber" in a for a in sinais):
        return True
    return False


def _fmt_canal_num(val: Any) -> str:
    """Número curto para canal endêmico (casos / limites)."""
    if val is None or val == "":
        return "—"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if math.isnan(f):
        return "—"
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.1f}".rstrip("0").rstrip(".")


def _zona_canal_pt(zona: str) -> str:
    z = (zona or "").casefold().strip()
    if z == "epidemia":
        return "zona epidêmica (estatística)"
    if z == "alerta":
        return "zona de alerta (estatística)"
    if z == "volume_insuficiente":
        return "volume insuficiente no marcador"
    if z == "sem_dado":
        return "sem dado histórico"
    return z or "—"


def carregar_canal_endemico_alerta(
    outdir: Path | str,
    *,
    se_iso: str | None = None,
    top: int = 10,
) -> list[dict[str, str]]:
    """
    Carrega canal_endemico_classificacao.csv e devolve top alerta/epidemia
    em formato string para Telegram/e-mail.
    """
    try:
        from ml.canal_endemico_bortman import listar_zonas_atencao
    except Exception:  # noqa: BLE001
        return []
    rows = listar_zonas_atencao(outdir, se_iso=se_iso, top=top)
    out: list[dict[str, str]] = []
    for r in rows:
        zona = str(r.get("zona") or "").casefold()
        casos = _fmt_canal_num(r.get("casos"))
        p50 = _fmt_canal_num(r.get("p50"))
        p75 = _fmt_canal_num(r.get("p75"))
        razao = r.get("razao_vs_p50")
        razao_s = ""
        try:
            if razao is not None and str(razao).strip() != "":
                rf = float(razao)
                if not math.isnan(rf) and rf > 0:
                    razao_s = f"{rf:.1f}× a mediana".replace(".0×", "×")
        except (TypeError, ValueError):
            razao_s = ""
        out.append(
            {
                "agravo": str(r.get("agravo") or ""),
                "agravo_pt": _nome_agravo_pt(str(r.get("agravo") or "")),
                "municipio": str(r.get("municipio") or ""),
                "municipio_pt": _mun_titulo(str(r.get("municipio") or "")),
                "zona": zona,
                "zona_pt": _zona_canal_pt(zona),
                "casos": casos,
                "exames_marcador": _fmt_canal_num(r.get("exames_marcador")),
                "marcador_alerta": str(r.get("marcador_alerta") or ""),
                "mediana": p50,
                "limite_superior": p75,
                "razao_vs_mediana": razao_s,
                "n_anos_baseline": _fmt_canal_num(r.get("n_anos_baseline")),
            }
        )
    return out


def _linha_canal_endemico(row: dict[str, str]) -> str:
    """Município × agravo — zona estatística · exames positivos vs mediana/limite."""
    mun = row.get("municipio_pt") or _mun_titulo(str(row.get("municipio") or ""))
    agr = row.get("agravo_pt") or _nome_agravo_pt(str(row.get("agravo") or ""))
    zona_lbl = row.get("zona_pt") or _zona_canal_pt(str(row.get("zona") or ""))
    pos = row.get("casos") or "—"
    med = row.get("mediana") or "—"
    lim = row.get("limite_superior") or "—"
    n_ex = str(row.get("exames_marcador") or "").strip()
    vol = f"; {n_ex} exames no marcador" if n_ex and n_ex not in {"—", ""} else ""
    razao = str(row.get("razao_vs_mediana") or "").strip()
    extra = f"; {razao}" if razao else ""
    return (
        f"{mun} × {agr}: {zona_lbl} — {pos} exames positivos "
        f"(mediana histórica {med}; limite superior {lim}){vol}{extra}"
    )


def coletar_recomendacoes_alerta(
    rel: RelatorioCIEVS, *, max_n: int = 12
) -> list[dict[str, str]]:
    """
    Recomendações CIEVS/VE em português claro (top diversificado).

    Prioriza: casos VE, picos de demanda, positividade, clusters vizinhos,
    lacunas exame×notificação. Pressão lab / fila só se ligada a agravo em sinal.
    """
    buckets: dict[str, list[dict[str, str]]] = {
        "ve": [],
        "canal": [],
        "demanda": [],
        "positividade": [],
        "vizinhos": [],
        "gal_sinan": [],
        "lab_agravo": [],
    }
    seen: set[str] = set()
    sinais = _agravos_em_sinal(rel)

    def _add(tipo: str, dest: str, acao: str, key: str) -> None:
        texto = (acao or "").strip()
        destinatario = (dest or "vigilância").strip() or "vigilância"
        if not texto or tipo not in buckets:
            return
        k = key.casefold()[:96]
        if k in seen:
            return
        seen.add(k)
        if len(texto) > 220:
            texto = texto[:219] + "…"
        buckets[tipo].append({"tipo": tipo, "dest": destinatario, "acao": texto})

    for r in rel.ve_recomendacoes or []:
        area = _suavizar_texto_alerta(str(r.get("area") or "vigilância"))
        acao = _suavizar_texto_alerta(str(r.get("acao") or ""))
        prazo = str(r.get("prazo") or "").strip()
        if prazo and prazo not in {"—", "-"} and prazo not in acao:
            acao = f"{acao} · prazo {prazo}" if acao else f"prazo {prazo}"
        agravo = _nome_agravo_pt(str(r.get("agravo") or ""))
        _add("ve", area, acao, f"ve|{area[:32]}|{agravo}|{acao[:40]}")

    for c in (rel.canal_endemico or [])[:8]:
        zona = str(c.get("zona") or "").casefold()
        if zona not in {"epidemia", "alerta"}:
            continue
        mun = c.get("municipio_pt") or _mun_titulo(str(c.get("municipio") or ""))
        agr = c.get("agravo_pt") or _nome_agravo_pt(str(c.get("agravo") or ""))
        casos = c.get("casos") or "—"
        lim = c.get("limite_superior") or "—"
        if zona == "epidemia":
            _add(
                "canal",
                "CIEVS / VE municipal",
                f"{mun} ({agr}): {casos} exames positivos acima do limite histórico "
                f"({lim}) — zona epidêmica estatística; investigar; "
                f"não declarar epidemia automaticamente.",
                f"canal|{mun}|{agr}|ep",
            )
        else:
            _add(
                "canal",
                "CIEVS / VE municipal",
                f"{mun} ({agr}): zona de alerta estatística no canal endêmico "
                f"({casos} exames positivos; limite {lim}) — reforçar monitoramento "
                f"e cruzar com notificação.",
                f"canal|{mun}|{agr}|al",
            )

    for x in (rel.briefing_mais_solicitados or [])[:8]:
        tgt = str(x.get("target") or "")
        if not tgt:
            continue
        delta = _parse_delta_pct(x.get("delta_pct"))
        tend = str(x.get("tendencia") or "")
        if not (
            (delta is not None and delta >= 25)
            or tend in {"↑", "^", "alta", "up"}
        ):
            continue
        n_se = x.get("n_se", x.get("exames", "—"))
        nome = _nome_agravo_pt(tgt)
        var = _fmt_variacao_pt(x.get("delta_pct"), tend)
        _add(
            "demanda",
            "CIEVS / VE municipal",
            f"Investigar possível aumento de {nome} "
            f"({n_se} exames laboratório; {var}) — "
            f"confrontar com notificações e busca ativa.",
            f"demanda|{tgt}",
        )

    for x in (rel.briefing_maior_positividade or [])[:6]:
        tgt = str(x.get("target") or "")
        if not tgt:
            continue
        flag = ""
        if str(x.get("baixa_amostra") or "") == "sim":
            flag = " (poucos exames — interpretar com cautela)"
        nome = _nome_agravo_pt(tgt)
        _add(
            "positividade",
            "área técnica / VE",
            f"Validar positividade elevada de {nome} "
            f"({x.get('positividade')} em {x.get('exames')} exames){flag}; "
            f"avaliar definição de caso e notificação.",
            f"pos|{tgt}",
        )

    for v in (rel.briefing_vizinhos or [])[:6]:
        tgt = _nome_agravo_pt(str(v.get("target") or ""))
        par = str(v.get("par") or "").replace("↔", "e").replace("<->", "e")
        if not par:
            continue
        _add(
            "vizinhos",
            "CIEVS / VE municipais",
            f"Cluster territorial {par} ({tgt}): reforçar vigilância "
            f"coordenada e comunicação entre municípios vizinhos.",
            f"viz|{tgt}|{par}",
        )

    for g in (rel.briefing_gal_sinan or [])[:6]:
        mun = str(g.get("municipio") or "")
        fam = _nome_agravo_pt(str(g.get("familia") or g.get("target") or ""))
        if not mun:
            continue
        gap = _flag_territorio_pt(str(g.get("flag") or ""))
        _add(
            "gal_sinan",
            "VE municipal",
            f"Em {mun} ({fam}): {gap} — investigar lacuna de vigilância "
            f"(notificação × resultado laboratorial).",
            f"gs|{mun}|{fam}",
        )

    # Apoio lab só se agravo em sinal + SLA/crise da mesma família
    for s in (rel.sla_por_familia or [])[:6]:
        fam_raw = str(s.get("familia") or "")
        fam = _nome_agravo_pt(fam_raw)
        if not _fam_casa_com_sinal(fam, sinais):
            continue
        crise = str(s.get("sla_crise") or "").casefold()
        pct = str(s.get("pct_48h") or "")
        try:
            v = float(str(pct).replace("%", "").replace(",", "."))
        except ValueError:
            v = None
        if crise == "sim" or (v is not None and v < 50):
            _add(
                "lab_agravo",
                "área técnica / LACEN (apoio)",
                f"{fam}: tempo de liberação crítico ({pct} ≤48h) — "
                f"verificar reagentes/capacidade só se houver backlog do agravo.",
                f"lab|{fam}",
            )

    order = (
        "ve",
        "canal",
        "demanda",
        "positividade",
        "vizinhos",
        "gal_sinan",
        "lab_agravo",
    )
    out: list[dict[str, str]] = []
    idxs = {k: 0 for k in order}
    while len(out) < max_n:
        progressed = False
        for tipo in order:
            i = idxs[tipo]
            bucket = buckets[tipo]
            if i < len(bucket):
                out.append(bucket[i])
                idxs[tipo] = i + 1
                progressed = True
                if len(out) >= max_n:
                    break
        if not progressed:
            break
    return out


def coletar_acoes_lacen(rel: RelatorioCIEVS, *, max_n: int = 3) -> list[str]:
    """
    Apoio laboratorial opcional — só quando pertinente ao agravo em sinal
    (reagentes/TAT/confirmação). Não lista pressão genérica da rede.
    """
    acoes: list[str] = []
    seen: set[str] = set()
    sinais = _agravos_em_sinal(rel)

    def _push(txt: str) -> None:
        t = (txt or "").strip()
        if not t:
            return
        k = t.casefold()[:80]
        if k in seen:
            return
        seen.add(k)
        acoes.append(t)

    if not sinais:
        return []

    # SLA / TAT por família do agravo em sinal
    for s in (rel.sla_por_familia or [])[:8]:
        fam_raw = str(s.get("familia") or "")
        fam = _nome_agravo_pt(fam_raw)
        fam_cf = fam.casefold()
        if not _fam_casa_com_sinal(fam, sinais):
            continue
        crise = str(s.get("sla_crise") or "").casefold()
        pct = str(s.get("pct_48h") or "")
        try:
            v = float(str(pct).replace("%", "").replace(",", "."))
        except ValueError:
            v = None
        if crise == "sim" or (v is not None and v < 55):
            if any(k in fam_cf for k in ("dengue", "chikung", "zika", "arbov")):
                _push(
                    f"Arbovirose em sinal: checar capacidade de kits/reagentes "
                    f"e tempo de liberação ({pct} ≤48h) para não atrasar a VE."
                )
            elif any(k in fam_cf for k in ("hepatite", "hbv", "hcv")):
                _push(
                    f"Hepatite em sinal: garantir marcadores confirmatórios "
                    f"e reagentes ({pct} ≤48h) para a investigação."
                )
            elif "tubercul" in fam_cf:
                _push(
                    f"Tuberculose em sinal: priorizar liberação diagnóstica "
                    f"({pct} ≤48h) nos municípios sob investigação."
                )
            else:
                _push(
                    f"{fam}: tempo de liberação elevado ({pct} ≤48h) — "
                    f"alinhar com a investigação do agravo."
                )

    # Juína HBV / casos VE: linha curta de apoio confirmatório
    for c in rel.ve_casos or []:
        tgt = str(c.get("target") or "").casefold()
        mun = _mun_titulo(str(c.get("municipio") or ""))
        if "hepat" in tgt or "hbv" in tgt:
            _push(
                f"{mun} (hepatite B): apoio laboratorial a marcadores "
                f"confirmatórios se a VE municipal solicitar."
            )
            break

    return acoes[:max_n]


def coletar_municipios_prioritarios(
    rel: RelatorioCIEVS,
    internacoes: list[dict[str, str]] | None = None,
    *,
    max_n: int = 5,
) -> list[str]:
    """Linhas legíveis: exames, positivos, internações e vizinhos p/ mun prioritários."""
    internacoes = internacoes if internacoes is not None else list(
        getattr(rel, "internacoes_por_agravo", None) or []
    )
    intern_idx: dict[tuple[str, str], str] = {}
    for row in internacoes:
        fam = str(row.get("familia") or "").casefold()
        mun = str(row.get("municipio_key") or row.get("municipio") or "").upper()
        intern_idx[(fam, mun)] = str(row.get("n") or "0")

    def _intern(mun: str, *fams: str) -> str:
        mun_u = mun.upper()
        for fam in fams:
            n = intern_idx.get((fam, mun_u))
            if n and n not in {"0", "—"}:
                return n
        return "0"

    def _loc_stats(mun_keys: set[str], agravo_substr: tuple[str, ...]) -> dict[str, str]:
        best: dict[str, str] = {"exames": "—", "positivos": "—", "positividade": "—", "target": ""}
        for loc in rel.briefing_localidades or []:
            mun = str(loc.get("municipio") or "").upper()
            tgt = str(loc.get("target") or "").casefold()
            if mun not in mun_keys:
                continue
            if agravo_substr and not any(a in tgt for a in agravo_substr):
                continue
            best = {
                "exames": str(loc.get("exames") or "—"),
                "positivos": str(loc.get("positivos") or "—"),
                "positividade": str(loc.get("positividade") or "—"),
                "target": str(loc.get("target") or ""),
                "municipio": str(loc.get("municipio") or mun),
            }
            break
        for c in rel.ve_casos or []:
            mun = str(c.get("municipio") or "").upper()
            tgt = str(c.get("target") or "").casefold()
            if mun not in mun_keys:
                continue
            if agravo_substr and not any(a in tgt for a in agravo_substr):
                continue
            return {
                "exames": str(c.get("exames") or best["exames"]),
                "positivos": str(c.get("positivos") or best["positivos"]),
                "positividade": str(c.get("positividade") or best["positividade"]),
                "target": str(c.get("target") or best.get("target") or ""),
                "municipio": str(c.get("municipio") or mun),
            }
        for t in rel.top_positivos or []:
            mun = str(t.get("municipio") or "").upper()
            fam = str(t.get("familia") or "").casefold()
            if mun not in mun_keys:
                continue
            if agravo_substr and not any(a in fam for a in agravo_substr):
                continue
            return {
                "exames": str(t.get("exames") or best["exames"]),
                "positivos": str(t.get("positivos") or "—"),
                "positividade": str(t.get("positividade") or "—"),
                "target": str(t.get("familia") or ""),
                "municipio": str(t.get("municipio") or mun),
            }
        return best

    def _vizinhos_para(mun_keys: set[str], agravo_substr: tuple[str, ...]) -> str:
        parts: list[str] = []
        for v in rel.briefing_vizinhos or []:
            par = str(v.get("par") or "")
            tgt = str(v.get("target") or "").casefold()
            if agravo_substr and not any(a in tgt for a in agravo_substr):
                continue
            par_u = par.upper()
            if not any(m in par_u for m in mun_keys):
                continue
            parts.append(
                _suavizar_texto_alerta(
                    f"{par} ({v.get('positivos', '')})"
                ).strip()
            )
            if len(parts) >= 2:
                break
        return "; ".join(parts) if parts else "—"

    lines: list[str] = []

    # Juína × hepatite B
    st = _loc_stats({"JUINA"}, ("hepat", "hbv"))
    if st.get("exames") not in {None, "—", ""} or any(
        "JUINA" in str(c.get("municipio") or "").upper() for c in (rel.ve_casos or [])
    ):
        mun = st.get("municipio") or "JUINA"
        intern = _intern("JUINA", "hepatite")
        viz = _vizinhos_para({"JUINA"}, ("hepat", "hbv"))
        lines.append(
            f"Juína (hepatite B): {st.get('exames', '—')} exames, "
            f"{st.get('positivos', '—')} positivos ({st.get('positividade', '—')}); "
            f"internações: {intern}; vizinhos: {viz}."
        )

    # Cuiabá / Várzea Grande × tuberculose
    st_c = _loc_stats({"CUIABA", "CUIABÁ"}, ("tuber",))
    st_v = _loc_stats({"VARZEA GRANDE", "VÁRZEA GRANDE"}, ("tuber",))
    if st_c.get("positivos") not in {None, "—", "0", ""} or st_v.get("positivos") not in {
        None,
        "—",
        "0",
        "",
    }:
        viz = _vizinhos_para(
            {"CUIABA", "CUIABÁ", "VARZEA GRANDE", "VÁRZEA GRANDE"}, ("tuber",)
        )
        lines.append(
            f"Cuiabá (tuberculose): {st_c.get('exames', '—')} exames, "
            f"{st_c.get('positivos', '—')} positivos; "
            f"internações: {_intern('CUIABA', 'tuberculose')}. "
            f"Várzea Grande (tuberculose): {st_v.get('exames', '—')} exames, "
            f"{st_v.get('positivos', '—')} positivos; "
            f"internações: {_intern('VARZEA GRANDE', 'tuberculose')}. "
            f"Vizinhos: {viz}."
        )

    # Outros municípios com sinal VE / localidade (sem pressão lab genérica)
    seen_mun: set[str] = {ln.split("(")[0].strip().upper() for ln in lines}
    for c in rel.ve_casos or []:
        if len(lines) >= max_n:
            break
        mun = str(c.get("municipio") or "").strip()
        if not mun or mun.upper() in seen_mun:
            continue
        seen_mun.add(mun.upper())
        tgt = _nome_agravo_pt(str(c.get("target") or ""))
        intern = _intern(mun, "hepatite", "tuberculose", "dengue")
        viz = _vizinhos_para({mun.upper()}, ())
        lines.append(
            f"{_mun_titulo(mun)} ({tgt}): {c.get('exames', '—')} exames, "
            f"{c.get('positivos', '—')} positivos ({c.get('positividade', '—')}); "
            f"internações: {intern}; vizinhos: {viz}."
        )

    for loc in rel.briefing_localidades or []:
        if len(lines) >= max_n:
            break
        mun = str(loc.get("municipio") or "").strip()
        if not mun or mun.upper() in seen_mun:
            continue
        tgt_raw = str(loc.get("target") or "").casefold()
        if not any(k in tgt_raw for k in ("hepat", "tuber", "dengue", "arbov", "mening")):
            continue
        seen_mun.add(mun.upper())
        tgt = _nome_agravo_pt(str(loc.get("target") or ""))
        intern = _intern(mun, "hepatite", "tuberculose", "dengue")
        lines.append(
            f"{_mun_titulo(mun)} ({tgt}): {loc.get('exames', '—')} exames, "
            f"{loc.get('positivos', '—')} positivos; internações: {intern}."
        )

    return lines[:max_n]


def _pressao_predita_top(src: RelatorioSources, top_n: int = 3) -> list[dict[str, str]]:
    rows = src.get("ml_pressao_rede_predito")
    if not rows:
        # fallback: flags in indicadores_emergencia
        emerg = [
            r
            for r in src.get("indicadores_emergencia")
            if _truthy(r.get("pressao_predita_acima_limiar"))
        ]
        emerg = sorted(
            emerg,
            key=lambda r: _num(r.get("prob_pressao_alta_proxima_janela"), 0) or 0,
            reverse=True,
        )[:top_n]
        return [
            {
                "municipio": _cell(r, "municipio"),
                "faixa": _cell(r, "faixa_pressao_predita", "faixa_pressao"),
                "prob": _fmt_pct(_num(r.get("prob_pressao_alta_proxima_janela")), 0),
                "driver": _humanize_driver(_cell(r, "drivers_pressao_predita", "drivers")),
                "tipo_sinal": "Predito",
            }
            for r in emerg
        ]

    ranked = sorted(
        rows,
        key=lambda r: _num(r.get("prob_pressao_alta_proxima_janela"), 0) or 0,
        reverse=True,
    )
    out = []
    seen: set[str] = set()
    for r in ranked:
        if not (
            _truthy(r.get("acima_limiar"))
            or any(
                x in _cell(r, "faixa_pressao_predita").lower()
                for x in ("alta", "critic", "crít")
            )
        ):
            continue
        mun = _cell(r, "municipio")
        if mun in seen:
            continue
        seen.add(mun)
        out.append(
            {
                "municipio": mun,
                "faixa": _cell(r, "faixa_pressao_predita", "faixa_pressao"),
                "prob": _fmt_pct(_num(r.get("prob_pressao_alta_proxima_janela")), 0),
                "driver": _humanize_driver(_cell(r, "drivers")),
                "tipo_sinal": "Predito",
            }
        )
        if len(out) >= top_n:
            break
    return out


def _qualidade(src: RelatorioSources) -> tuple[str, str, str]:
    qual = src.get("qualidade_dado")
    rede = src.get("indicadores_rede_resumo", 1)
    n_qual = len([r for r in qual if not _cell(r, "municipio").startswith("*")])
    n_rede = int(_num(rede[0].get("n_municipios"), 0) or 0) if rede else 0
    faixas: dict[str, int] = {}
    for r in qual:
        if _cell(r, "municipio").startswith("*"):
            continue
        f = _cell(r, "faixa_confianca", default="n/d")
        faixas[f] = faixas.get(f, 0) + 1
    faixa_txt = ", ".join(f"{k}={v}" for k, v in sorted(faixas.items(), key=lambda x: -x[1]))
    cobertura = (
        f"Observado: {n_qual} mun. com qualidade "
        f"(rede GAL={n_rede or '—'}); faixas: {faixa_txt or '—'}"
    )

    conf_rows = src.get("emergencia_confirmacao_resumo", 1)
    conf_kpi = "—"
    if conf_rows:
        c = conf_rows[0]
        taxa = _fmt_pct(_num(c.get("taxa_confirmacao_geral")))
        conf_kpi = taxa
        n_ok = _fmt_num(_num(c.get("n_confirmados")), 0)
        n_av = _fmt_num(_num(c.get("n_alertas_avaliados")), 0)
        tipo = _cell(c, "tipo_sinal", default="Observado")
        confirmacao = (
            f"{tipo}: confirmação alertas rodada anterior = {taxa} "
            f"({n_ok}/{n_av}); modo={_cell(c, 'modo_confirmacao')}"
        )
    else:
        confirmacao = "Confirmação: artefato emergencia_confirmacao_* ausente"

    return cobertura, confirmacao, conf_kpi


def montar_relatorio(
    outdir: Path | str = OUTDIR_DEFAULT,
    *,
    top_fila: int = 10,
    top_predito: int = 5,
    prefer_dw: bool = True,
    sources: RelatorioSources | None = None,
    incluir_parecer_ve: bool = True,
) -> RelatorioCIEVS:
    outdir = Path(outdir)
    src = sources or load_relatorio_sources(outdir, prefer_dw=prefer_dw)

    # Lab-epi define a SE única; KPIs A–D e rankings usam a mesma referência.
    top_pos, variacao, vol_kpis, lab_meta = _top_positivos(src, top_n=5)
    se = _semana_ref(src, se_lab=str(lab_meta.get("se_iso") or "—"))
    n_1a = _count_primeira_deteccao(src, se)
    diverg = _top_divergencias(src, top_n=5)
    (
        tat_med,
        tat_p90,
        pct48,
        top_pressao,
        silencio,
        resumo,
        rede,
        pressao_max,
        n_sil,
    ) = _bloco_rede(src)
    leitura = _leitura_situacional(resumo, rede, len(top_pressao), len(silencio))
    mun_crs = src.dw_enrich.get("mun_crs") or {}
    fila = _fila_acoes(src, top_n=top_fila, mun_crs=mun_crs)
    preditos = _preditos_alta(src, top_n=top_predito)
    pressao_pred = _pressao_predita_top(src, top_n=3)
    cobertura, confirmacao, conf_kpi = _qualidade(src)
    sla_fam = _sla_familia(src, top_n=4)
    faixa_press = _contagem_campo(src.get("indicadores_emergencia"), "faixa_pressao")
    banda_risco = _contagem_campo(
        src.get("ml_risco_predito"), "banda_risco", ("faixa_predita",)
    )

    aviso = _aviso_atraso_bases(src, lab_meta, se)

    # Bloco E — mesma SE operacional do lab-epi (Top 10)
    briefing_raw = gerar_briefing_epi(
        outdir, se=se if se != "—" else None, top=10
    )
    briefing = briefing_para_relatorio(briefing_raw)

    # Bloco F — Parecer VE (opcional; falha não quebra o relatório)
    ve_resumo = ""
    ve_casos: list[dict[str, str]] = []
    ve_recs: list[dict[str, str]] = []
    ve_arqs: list[str] = []
    ve_llm = False
    if incluir_parecer_ve:
        try:
            from lacen_agente_ve import gerar_parecer_ve, parecer_para_relatorio

            parecer = gerar_parecer_ve(
                outdir,
                se=se if se != "—" else None,
                top=10,
                tentar_download_ms=False,
                usar_llm=True,
                persistir=True,
                briefing=briefing_raw,
            )
            ve_payload = parecer_para_relatorio(parecer)
            ve_resumo = str(ve_payload.get("resumo") or "")
            ve_casos = [
                {
                    "titulo": str(c.get("titulo") or ""),
                    "municipio": str(c.get("municipio") or ""),
                    "target": str(c.get("target") or ""),
                    "exames": str(c.get("exames") or ""),
                    "positivos": str(c.get("positivos") or ""),
                    "positividade": str(c.get("positividade") or ""),
                    "veredito": str(c.get("veredito") or ""),
                }
                for c in (ve_payload.get("casos") or [])
            ]
            ve_recs = [
                {"area": str(r.get("area") or ""), "acao": str(r.get("acao") or "")}
                for r in (ve_payload.get("recomendacoes_topo") or [])
            ]
            # Preferir linhas por destinatário/agravo quando disponíveis
            if ve_payload.get("recomendacoes_por_agravo") and not ve_recs:
                for block in ve_payload["recomendacoes_por_agravo"][:2]:
                    for dest, texto in list(
                        (block.get("destinatarios") or {}).items()
                    )[:3]:
                        ve_recs.append({"area": str(dest), "acao": str(texto)})
            elif ve_payload.get("recomendacoes_por_agravo"):
                # Injeta SES-MT / CIEVS do 1º agravo no topo do Bloco F
                b0 = ve_payload["recomendacoes_por_agravo"][0]
                dests = b0.get("destinatarios") or {}
                extra = [
                    {"area": str(d), "acao": str(dests[d])}
                    for d in ("SES-MT", "CIEVS")
                    if d in dests
                ]
                ve_recs = extra + ve_recs
            ve_arqs = [str(a) for a in (ve_payload.get("arquivos") or [])]
            ve_llm = bool(ve_payload.get("usou_llm"))
        except Exception as exc:  # noqa: BLE001
            ve_resumo = f"Parecer VE indisponível nesta geração ({exc})."

    # Preferir CSV VE diversificado por destinatário (anti copy-paste silêncio)
    ve_csv = _load_ve_acoes_csv(outdir, max_n=8)
    if ve_csv:
        ve_recs = ve_csv

    fontes: list[str] = []
    if src.tabelas_dw:
        fontes.extend(src.tabelas_dw)
    if src.arquivos_local and not src.tabelas_dw:
        # Só lista arquivos quando não há DW — evita laundry list
        fontes.append(f"saida_pipeline ({len(src.arquivos_local)} artefatos)")
    elif src.arquivos_local and src.tabelas_dw:
        fontes.append(f"+ saida_pipeline complementar ({len(src.arquivos_local)} artefatos)")
    for bf in briefing.get("fontes") or []:
        if bf and bf not in fontes:
            fontes.append(bf)
    if ve_arqs:
        fontes.append("conhecimento_ve + lacen_agente_ve")

    crs_top = [
        {"crs": x.get("crs", "—"), "n": _fmt_num(x.get("n"), 0)}
        for x in (src.dw_enrich.get("crs_top") or [])
    ]

    nota = (
        "Relatório agregado — rótulos Observado / Derivado / Predito. "
        "Sem PII ou microdados nominais. "
        f"KPIs lab-epi, briefing (Top 10) e top municípios alinhados à SE "
        f"de referência {se} "
        "(série integrated_weekly; soma estadual = soma municipal da mesma SE). "
        "Bloco F (parecer VE) não declara surto automaticamente — Guia MS."
    )
    if briefing.get("nota_igg"):
        nota += " " + str(briefing["nota_igg"])
    if briefing.get("nota_marcadores") and briefing.get("nota_marcadores") not in nota:
        nota += " " + str(briefing["nota_marcadores"])
    if briefing.get("nota_populacao"):
        nota += " " + str(briefing["nota_populacao"])

    # Internações: preferir SIH já filtrado aos municípios do sinal
    intern_alerta = list(
        ((briefing.get("cruzamento_sih_sia") or {}).get("top_mun") or [])
    )
    internacoes_fmt: list[dict[str, str]] = []
    if intern_alerta:
        for row in intern_alerta[:15]:
            fam = _nome_agravo_pt(str(row.get("cid_familia") or ""))
            internacoes_fmt.append(
                {
                    "familia": fam,
                    "familia_pt": fam,
                    "municipio": _mun_titulo(str(row.get("municipio") or "—")),
                    "municipio_key": str(row.get("municipio") or "").upper(),
                    "n": str(row.get("n") or "0"),
                    "n_raw": str(row.get("n") or "0"),
                    "fonte": "internações (SIH · municípios do sinal)",
                }
            )
    else:
        internacoes_fmt = carregar_internacoes_alerta(outdir, top_por_familia=5)

    # Canal endêmico Bortman (alerta/epidemia da SE de referência)
    canal_rows = carregar_canal_endemico_alerta(
        outdir, se_iso=se if se != "—" else None, top=10
    )
    if canal_rows and "canal endêmico Bortman" not in " ".join(fontes).casefold():
        fontes.append("canal_endemico_classificacao.csv (Bortman)")

    # Filtra SLA respiratório genérico salvo se houver sinal explícito no briefing
    sinais_txt = " ".join(
        [
            str(x.get("target") or "")
            for x in (briefing.get("mais_solicitados") or [])
            + (briefing.get("maior_positividade") or [])
        ]
        + [str(c.get("target") or "") for c in ve_casos]
    ).casefold()
    tem_sinal_respiratorio = any(
        k in sinais_txt for k in ("respirat", "influenza", "srag", "covid", "sivep")
    )
    sla_filtrada = []
    for s in sla_fam:
        fam_cf = str(s.get("familia") or "").casefold()
        if any(k in fam_cf for k in ("respirat", "influenza", "srag", "covid")):
            if not tem_sinal_respiratorio:
                continue
        sla_filtrada.append(s)

    return RelatorioCIEVS(
        semana_epidemiologica=se,
        leitura_situacional=leitura,
        kpi_positivos_se=vol_kpis.get("positivos_se", "—"),
        kpi_variacao_pct=vol_kpis.get("variacao_pct", "—"),
        kpi_tat_p50=tat_med,
        kpi_tat_p90=tat_p90,
        kpi_pct_48h=pct48,
        kpi_pressao_max=pressao_max,
        kpi_silencios=n_sil,
        kpi_confirmacao=conf_kpi,
        kpi_exames_se=vol_kpis.get("exames_se", "—"),
        kpi_municipios_exame=vol_kpis.get("municipios", "—"),
        top_positivos=top_pos,
        variacao_se=variacao,
        n_primeira_deteccao_alerta=n_1a,
        top_divergencias=diverg,
        briefing_mais_solicitados=briefing.get("mais_solicitados") or [],
        briefing_maior_positividade=briefing.get("maior_positividade") or [],
        briefing_localidades=briefing.get("localidades") or [],
        briefing_vizinhos=briefing.get("vizinhos") or [],
        briefing_risco=briefing.get("risco") or [],
        cartoes_risco=briefing.get("cartoes_risco") or [],
        briefing_gal_sinan=briefing.get("gal_sinan") or [],
        briefing_geo_nivel=str(briefing.get("geo_nivel") or "municipio"),
        briefing_geo_nota=str(briefing.get("geo_nota") or ""),
        briefing_geo_hotspots=briefing.get("geo_hotspots") or [],
        briefing_cruzamento=briefing.get("cruzamento_bases") or [],
        briefing_cruzamento_sih_sia=list(
            ((briefing.get("cruzamento_sih_sia") or {}).get("top_mun") or [])
        ),
        briefing_cruzamento_sih_sia_caveat=str(
            (briefing.get("cruzamento_sih_sia") or {}).get("caveat") or ""
        ),
        internacoes_por_agravo=internacoes_fmt,
        briefing_sinais_rede=dict(briefing.get("sinais_rede") or {}),
        briefing_nota_igg=str(briefing.get("nota_igg") or ""),
        briefing_fontes=list(briefing.get("fontes") or []),
        score_prioridade=list(briefing.get("score_prioridade") or []),
        canal_endemico=canal_rows,
        marcadores_top=list(briefing.get("marcadores_top") or []),
        lacunas_vigilancia=list(briefing.get("lacunas_vigilancia") or []),
        alertas_especificos=list(briefing.get("alertas_especificos") or []),
        nota_marcadores=str(briefing.get("nota_marcadores") or ""),
        ve_resumo=ve_resumo,
        ve_casos=ve_casos,
        ve_recomendacoes=ve_recs,
        ve_arquivos=ve_arqs,
        ve_usou_llm=ve_llm,
        tat_mediano=tat_med,
        tat_p90=tat_p90,
        pct_48h=pct48,
        top_pressao=top_pressao,
        silencio_vizinho_quente=silencio,
        sla_por_familia=sla_filtrada,
        contagem_faixa_pressao=faixa_press[:6],
        fila_acoes=fila,
        preditos_alta=preditos,
        pressao_predita_top=pressao_pred,
        contagem_banda_risco=banda_risco[:6],
        cobertura_municipios=cobertura,
        confirmacao_alertas=confirmacao,
        crs_top=crs_top,
        aviso_atraso=aviso,
        fonte_primaria=src.fonte_primaria,
        fontes_presentes=fontes,
        banner_fonte=src.banner,
        nota=nota,
    )


def _cabecalho(rel: RelatorioCIEVS) -> str:
    nome = get_nome_ferramenta()
    return f"{nome} · CIEVS"


def _kpi_strip_text(rel: RelatorioCIEVS) -> str:
    return (
        f"Positivos SE {rel.kpi_positivos_se} ({rel.kpi_variacao_pct}) · "
        f"Exames {rel.kpi_exames_se} · Mun. {rel.kpi_municipios_exame} · "
        f"TAT p50/p90 {rel.kpi_tat_p50}/{rel.kpi_tat_p90}d · "
        f"%≤48h {rel.kpi_pct_48h} · Pressão máx {rel.kpi_pressao_max} · "
        f"Silêncios {rel.kpi_silencios} · Confirmação {rel.kpi_confirmacao}"
    )


def _tg_clip(text: str, n: int) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[: max(0, n - 1)].rstrip() + "…"


def _tg_se_legivel(se: str) -> str:
    """2026-SE30 → semana epidemiológica 30/2026."""
    parsed = _parse_se(se)
    if not parsed:
        return se or "—"
    year, week = parsed
    return f"semana epidemiológica {week:02d}/{year}"


def _tg_variacao_kpi(var_raw: str) -> str:
    """KPI variação (−1% / +12%) em português."""
    s = (var_raw or "").strip()
    d = _parse_delta_pct(s)
    if d is None:
        return s or "—"
    pct = f"{abs(d):.0f}".replace(".", ",")
    if d > 0.5:
        return f"subiu {pct}% vs semana anterior"
    if d < -0.5:
        return f"caiu {pct}% vs semana anterior"
    return "quase estável vs semana anterior"


def _coletar_sinais_atencao(rel: RelatorioCIEVS, *, max_n: int = 5) -> list[str]:
    """Sinais de possível surto/epidemia/emergência ou sinais novos (CIEVS)."""
    lines: list[str] = []
    seen: set[str] = set()

    def _push(txt: str) -> None:
        t = (txt or "").strip()
        if not t:
            return
        k = t.casefold()[:72]
        if k in seen:
            return
        seen.add(k)
        lines.append(t)

    for c in (rel.ve_casos or [])[:5]:
        mun = _mun_titulo(str(c.get("municipio") or ""))
        tgt = _nome_agravo_pt(str(c.get("target") or c.get("titulo") or ""))
        ver = _suavizar_texto_alerta(str(c.get("veredito") or "")).strip()
        if ver and len(ver) > 140:
            ver = ver[:139] + "…"
        base = (
            f"{mun} × {tgt}: {c.get('exames', '—')} exames / "
            f"+{c.get('positivos', '—')} ({c.get('positividade', '—')})"
        )
        _push(f"{base}" + (f" — {ver}" if ver else " — sinal a investigar"))

    if rel.n_primeira_deteccao_alerta and rel.n_primeira_deteccao_alerta > 0:
        _push(
            f"1ª detecção / sinal novo na SE: "
            f"{rel.n_primeira_deteccao_alerta} município(s) — avaliar emergência "
            f"ou evento ainda não captado pela VE."
        )

    for x in (rel.briefing_mais_solicitados or [])[:6]:
        if len(lines) >= max_n:
            break
        d = _parse_delta_pct(x.get("delta_pct"))
        tend = str(x.get("tendencia") or "")
        if not ((d is not None and d >= 40) or tend in {"↑", "^", "alta", "up"}):
            continue
        if d is not None and d < 25 and tend not in {"↑", "^", "alta", "up"}:
            continue
        nome = _nome_agravo_pt(str(x.get("target") or ""))
        var = _fmt_variacao_pt(x.get("delta_pct"), tend)
        n_se = x.get("n_se", x.get("exames", "—"))
        _push(
            f"Pico de demanda {nome}: {n_se} exames ({var}) — "
            f"possível aumento de casos / pressão sobre a VE."
        )

    for p in (rel.preditos_alta or [])[:3]:
        if len(lines) >= max_n:
            break
        # Sem metodologia explícita no alerta curto — não listar como sinal CIEVS
        continue

    for c in (rel.canal_endemico or [])[:4]:
        if len(lines) >= max_n:
            break
        zona = str(c.get("zona") or "").casefold()
        if zona not in {"epidemia", "alerta"}:
            continue
        mun = c.get("municipio_pt") or _mun_titulo(str(c.get("municipio") or ""))
        agr = c.get("agravo_pt") or _nome_agravo_pt(str(c.get("agravo") or ""))
        if zona == "epidemia":
            _push(
                f"Canal endêmico: {mun} × {agr} em zona epidêmica estatística "
                f"({c.get('casos', '—')} exames positivos) — investigar; "
                f"não declarar epidemia"
            )
        else:
            _push(
                f"Canal endêmico: {mun} × {agr} em zona de alerta estatística "
                f"({c.get('casos', '—')} exames positivos)"
            )

    if not lines and rel.ve_resumo:
        _push(_tg_clip(_suavizar_texto_alerta(rel.ve_resumo), 160))
    if not lines:
        _push(
            f"Leitura: {(rel.leitura_situacional or '—').replace('_', ' ')} — "
            f"sem caso especial destacado; manter monitoramento CIEVS."
        )
    return lines[:max_n]


def _build_telegram_part1(rel: RelatorioCIEVS) -> list[str]:
    """CIEVS: sinais, demanda/positividade, território, internações, lacunas."""
    fonte = rel.fonte_primaria or "—"
    # GAL é uma fonte; deixar claro no rodapé curto
    fonte_pt = fonte
    if "gal" in fonte.casefold() or "lab" in fonte.casefold():
        fonte_pt = f"{fonte} (lab = uma fonte; cruzar com notificação)"
    atraso_short = ""
    av = rel.aviso_atraso or ""
    m_atraso = re.search(
        r"atrasada\s+(\d+)\s+SE\s+vs\s+esperada\s+(\S+)", av, flags=re.I
    )
    if m_atraso:
        se_esp = m_atraso.group(2).rstrip(".,;")
        atraso_short = (
            f" · bases atrasadas {m_atraso.group(1)} semanas "
            f"(esperada {se_esp})"
        )

    leitura = (rel.leitura_situacional or "—").replace("_", " ")
    lines: list[str] = [
        f"<b>📡 {html.escape(_cabecalho(rel))}</b>",
        f"{html.escape(_tg_se_legivel(rel.semana_epidemiologica))} · "
        f"<b>{html.escape(leitura)}</b>",
        html.escape(f"Fontes: {fonte_pt}{atraso_short}"),
        html.escape(rel.gerado_em or ""),
    ]
    if av and "atrasada" not in atraso_short.casefold():
        extra = av
        if "atrasada" in av.casefold() and atraso_short:
            extra = re.sub(
                r"SE ref [^.]*atrasada \d+ SE vs esperada [^.;]+[.;]?\s*",
                "",
                av,
                flags=re.I,
            ).strip()
            extra = re.sub(r"^Atenção:\s*", "Atenção: ", extra).strip()
            if extra in ("Atenção:", "Atenção:."):
                extra = ""
        if extra:
            lines.append(f"<i>{html.escape(_tg_clip(extra, 180))}</i>")

    sinais = _coletar_sinais_atencao(rel, max_n=5)
    if sinais:
        lines.extend(
            [
                "",
                "🚨 <b>Sinais de atenção</b> "
                "<i>(possível surto / epidemia / emergência / sinal novo)</i>",
            ]
        )
        for s in sinais:
            lines.append(html.escape(f"• {_tg_clip(s, 180)}"))

    # Demanda + positividade (lab + notificação quando houver)
    dem_pos: list[str] = []
    for x in (rel.briefing_mais_solicitados or [])[:5]:
        nome = _nome_agravo_pt(str(x.get("target") or ""))
        n_se = x.get("n_se", x.get("exames", "—"))
        var = _fmt_variacao_pt(x.get("delta_pct"), x.get("tendencia"))
        taxa = str(x.get("frase_taxa_positivos") or "").strip()
        taxa_bit = f"; {taxa}" if taxa else ""
        dem_pos.append(
            f"• Demanda {nome}: {n_se} exames, {var}; "
            f"{x.get('positivos', '—')} positivos ({x.get('positividade', '—')})"
            f"{taxa_bit}"
        )
    for x in (rel.briefing_maior_positividade or [])[:5]:
        if len(dem_pos) >= 5:
            break
        nome = _nome_agravo_pt(str(x.get("target") or ""))
        flag = (
            " — poucos exames, cautela"
            if x.get("baixa_amostra") == "sim"
            else ""
        )
        var = _fmt_variacao_pt(x.get("delta_pct"), x.get("tendencia"))
        taxa = str(x.get("frase_taxa_positivos") or "").strip()
        taxa_bit = f"; {taxa}" if taxa else ""
        dem_pos.append(
            f"• Positividade {nome}: {x.get('positividade', '—')} "
            f"({x.get('exames', '—')} exames; {var}){flag}{taxa_bit}"
        )
    if dem_pos:
        lines.extend(
            [
                "",
                "📊 <b>Demanda e positividade</b> "
                "<i>(laboratório + taxas /100 mil)</i>",
            ]
        )
        for t in dem_pos[:5]:
            lines.append(html.escape(_tg_clip(t, 170)))

    # Cartões de risco (top 5 eventos) — eixo CIEVS
    cartoes = list(rel.cartoes_risco or [])[:5]
    if cartoes:
        lines.extend(
            [
                "",
                "🃏 <b>Cartões de risco</b> "
                "<i>(evento · probabilidade × impacto)</i>",
            ]
        )
        for c in cartoes:
            taxa = str(c.get("taxa_positivos") or "").strip()
            taxa_bit = f" · {taxa}" if taxa else ""
            zona = str(c.get("zona_bortman") or "").casefold()
            zona_bit = ""
            if zona == "epidemia":
                zona_bit = " · canal: zona epidêmica (estatística)"
            elif zona == "alerta":
                zona_bit = " · canal: zona de alerta (estatística)"
            lines.append(
                html.escape(
                    _tg_clip(
                        f"• {c.get('evento', '—')}: "
                        f"prob {c.get('probabilidade', '—')} / "
                        f"impacto {c.get('impacto', '—')} → "
                        f"{c.get('veredito', '—')} "
                        f"[{c.get('confianca', 'Observado')}]"
                        f"{taxa_bit}{zona_bit}",
                        190,
                    )
                )
            )

    # Canal endêmico Bortman — top alerta/epidemia
    canal = list(rel.canal_endemico or [])[:8]
    if canal:
        lines.extend(
            [
                "",
                "📈 <b>Canal endêmico</b> "
                "<i>(comparação com a mesma semana nos anos anteriores)</i>",
                html.escape(
                    "Zona epidêmica (estatística) = acima do P75 histórico "
                    "no marcador de alerta — investigar; não declarar epidemia."
                ),
            ]
        )
        for row in canal:
            lines.append(html.escape(_tg_clip(_linha_canal_endemico(row), 240)))

    # Score municipal (proposta homologação) + caveat marcadores
    scores = list(rel.score_prioridade or [])[:5]
    if scores:
        lines.extend(
            [
                "",
                "<b>Prioridade municipal</b> "
                "<i>(proposta para homologação CIEVS)</i>",
            ]
        )
        for s in scores:
            lines.append(
                html.escape(
                    _tg_clip(
                        f"• {_mun_titulo(str(s.get('municipio') or ''))}: "
                        f"score {s.get('score', '—')} "
                        f"(lab {s.get('excesso_lab_0_1', '—')} · "
                        f"pos {s.get('positividade_anomala_0_1', '—')} · "
                        f"lacuna {s.get('lacuna_sinan_0_1', '—')} · "
                        f"internações {s.get('internacoes_graves_0_1', '—')})",
                        180,
                    )
                )
            )
        lines.append(
            html.escape(
                "Fórmula: 3×excesso lab (zona do canal) + 2×positividade do marcador "
                "de alerta + 1×lacuna SINAN + 1×internações; ausente ≠ 0 "
                "(normalizado pelos componentes válidos)."
            )
        )
    if rel.nota_marcadores or rel.briefing_nota_igg:
        cave = (rel.briefing_nota_igg or rel.nota_marcadores or "")[:160]
        lines.append(html.escape(f"Marcadores: {cave}"))

    terr: list[str] = []
    for v in (rel.briefing_vizinhos or [])[:5]:
        nome = _nome_agravo_pt(str(v.get("target") or ""))
        par = _suavizar_texto_alerta(str(v.get("par") or ""))
        terr.append(f"• Cluster vizinhos ({nome}): {par} ({v.get('positivos', '')})")
    mun_prio = coletar_municipios_prioritarios(
        rel, list(rel.internacoes_por_agravo or []), max_n=3
    )
    for ml in mun_prio:
        if len(terr) >= 5:
            break
        terr.append(f"• {_tg_clip(ml, 150)}")
    if terr:
        lines.extend(["", "🗺️ <b>Território / clusters</b>"])
        for t in terr[:5]:
            lines.append(html.escape(_tg_clip(t, 160)))

    intern = list(rel.internacoes_por_agravo or [])
    if not intern and rel.briefing_cruzamento_sih_sia:
        for row in rel.briefing_cruzamento_sih_sia[:12]:
            fam = _nome_agravo_pt(str(row.get("cid_familia") or ""))
            intern.append(
                {
                    "familia": fam,
                    "familia_pt": fam,
                    "municipio": str(row.get("municipio") or "—"),
                    "n": str(row.get("n") or "0"),
                }
            )
    if intern:
        lines.extend(
            ["", "🏥 <b>Internações correlatas</b> <i>(gravidade)</i>"]
        )
        by_fam: dict[str, list[dict[str, str]]] = {}
        for row in intern:
            fam = str(row.get("familia_pt") or row.get("familia") or "agravo")
            by_fam.setdefault(fam, []).append(row)
        n_fam = 0
        for fam in ("hepatite", "tuberculose", "dengue"):
            rows = by_fam.get(fam) or []
            if not rows:
                for k, v in by_fam.items():
                    if fam in k.casefold():
                        rows = v
                        break
            if not rows:
                continue
            bits = [f"{r.get('municipio')} ({r.get('n')})" for r in rows[:5]]
            lines.append(html.escape(f"• {fam.capitalize()}: " + "; ".join(bits)))
            n_fam += 1
            if n_fam >= 3:
                break

    gaps = (rel.briefing_gal_sinan or [])[:5]
    if gaps:
        lines.extend(["", "🔎 <b>Lacunas de vigilância</b>"])
        for g in gaps:
            fam = _nome_agravo_pt(str(g.get("familia") or g.get("target") or ""))
            gap = _flag_territorio_pt(str(g.get("flag") or ""))
            lines.append(
                html.escape(
                    f"• {_mun_titulo(str(g.get('municipio')))} ({fam}): {gap}"
                )
            )

    return lines


def _build_telegram_part2(rel: RelatorioCIEVS, *, part_label: bool = True) -> list[str]:
    """Recomendações CIEVS/VE, apoio lab opcional, parecer."""
    lines: list[str] = []
    if part_label:
        lines.extend(
            [
                f"<b>📡 {html.escape(get_nome_ferramenta())} — Parte 2</b> "
                f"<i>(recomendações CIEVS / VE)</i>",
                html.escape(_tg_se_legivel(rel.semana_epidemiologica)),
                "",
            ]
        )

    recos = coletar_recomendacoes_alerta(rel, max_n=8)
    if recos:
        lines.extend(
            [
                "⚠️ <b>Recomendações</b> "
                "<i>(CIEVS / VE / área técnica / município / vizinhos)</i>"
            ]
        )
        for i, r in enumerate(recos, 1):
            dest = _tg_clip(str(r.get("dest") or "vigilância"), 42)
            acao = _tg_clip(str(r.get("acao") or ""), 140)
            lines.append(
                f"<b>{i}. {html.escape(dest)}</b> — {html.escape(acao)}"
            )

    apoio = coletar_acoes_lacen(rel, max_n=3)
    if apoio:
        lines.extend(
            ["", "🔬 <b>Apoio laboratorial</b> <i>(só se pertinente ao agravo)</i>"]
        )
        for i, a in enumerate(apoio, 1):
            lines.append(html.escape(f"{i}. {_tg_clip(a, 160)}"))

    parecer = _parecer_alerta_line(rel.ve_casos, rel.ve_resumo)
    if parecer:
        parecer_pt = (
            parecer.replace("HBV", "hepatite B")
            .replace("ex.", "exames")
            .replace("sinal lab", "sinal a investigar")
            .replace("sinal no laboratório", "sinal a investigar")
        )
        low = parecer_pt.casefold()
        if "não declarar" not in low and "nao declarar" not in low:
            parecer_pt = (
                parecer_pt.rstrip(". ")
                + " — NÃO declarar surto/epidemia automaticamente (Guia MS)."
            )
        lines.extend(["", "✅ <b>Parecer</b>"])
        lines.append(html.escape(_tg_clip(parecer_pt, 280)))
    else:
        lines.extend(
            [
                "",
                "✅ <b>Parecer</b>",
                html.escape(
                    "Sinais para sala de situação CIEVS — investigar; "
                    "não declarar surto/epidemia automaticamente (Guia MS)."
                ),
            ]
        )

    lines.extend(
        [
            "",
            f'<a href="{html.escape(rel.dashboard_url)}">Painel Radar LACEN</a>',
        ]
    )
    return lines


def to_telegram_messages(
    rel: RelatorioCIEVS, *, max_chars: int = 3900
) -> list[str]:
    """
    1 ou 2 mensagens HTML para Telegram (limite 4096).
    Parte 1 = sinais CIEVS; Parte 2 = recomendações + apoio lab opcional + parecer.
    """
    link = f'\n<a href="{html.escape(rel.dashboard_url)}">Painel Radar LACEN</a>'

    def _clip_msg(text: str) -> str:
        t = text.strip()
        if len(t) <= max_chars:
            return t
        budget = max_chars - len(link) - 14
        return t[:budget].rstrip() + "\n…(truncado)" + link

    part1 = "\n".join(_build_telegram_part1(rel)).strip()
    part2 = "\n".join(_build_telegram_part2(rel, part_label=True)).strip()

    combined_lines = (
        _build_telegram_part1(rel)
        + [""]
        + _build_telegram_part2(rel, part_label=False)
    )
    combined = "\n".join(combined_lines).strip()
    if len(combined) <= max_chars:
        return [_clip_msg(combined)]

    return [_clip_msg(part1), _clip_msg(part2)]


def to_telegram_markdown(rel: RelatorioCIEVS, *, max_chars: int = 3900) -> str:
    """Compat: retorna a 1ª mensagem (ou a única). Use to_telegram_messages."""
    msgs = to_telegram_messages(rel, max_chars=max_chars)
    return msgs[0] if msgs else ""


def to_email_subject(rel: RelatorioCIEVS) -> str:
    nome = get_nome_ferramenta()
    return (
        f"[{nome}] {rel.semana_epidemiologica} — "
        f"{rel.leitura_situacional} — LACEN-MT · {rel.gerado_em}"
    )


def to_email_plain(rel: RelatorioCIEVS) -> str:
    lines: list[str] = [
        _cabecalho(rel),
        f"SE de referência: {rel.semana_epidemiologica} "
        f"(única para KPIs e rankings A–D)",
        f"Gerado em: {rel.gerado_em}",
        f"Leitura situacional: {rel.leitura_situacional}",
        rel.nota,
        "",
        "KPIs: " + _kpi_strip_text(rel),
    ]
    if rel.aviso_atraso:
        lines.append(f"Aviso: {rel.aviso_atraso}")

    if rel.cartoes_risco:
        lines.extend(["", "— Visão executiva · Cartões de risco (CIEVS) —"])
        for i, c in enumerate(rel.cartoes_risco[:5], 1):
            taxa = c.get("taxa_positivos") or ""
            taxa_bit = f" · {taxa}" if taxa else ""
            lines.append(
                f"  {i}. {c.get('evento', '—')}: "
                f"prob={c.get('probabilidade', '—')} "
                f"impacto={c.get('impacto', '—')} → "
                f"{c.get('veredito', '—')} "
                f"[{c.get('confianca', 'Observado')}]{taxa_bit}"
            )
            if c.get("acao_cievs"):
                lines.append(f"     CIEVS: {c['acao_cievs']}")

    if rel.canal_endemico:
        lines.extend(
            [
                "",
                "— Canal endêmico (comparação com a mesma semana nos anos anteriores) —",
                "Zona epidêmica (estatística) = acima do P75 no marcador de alerta — "
                "priorizar investigação; não declarar epidemia automaticamente.",
            ]
        )
        for i, row in enumerate(rel.canal_endemico[:10], 1):
            lines.append(f"  {i}. {_linha_canal_endemico(row)}")

    if rel.score_prioridade:
        lines.extend(
            [
                "",
                "— Prioridade municipal (proposta para homologação CIEVS) —",
                "score = (3*excesso_lab + 2*pos_marcador_alerta + 1*lacuna + 1*internacoes) "
                "/ pesos válidos; ausente≠0; excesso=zona do canal",
            ]
        )
        for i, s in enumerate(rel.score_prioridade[:8], 1):
            lines.append(
                f"  {i}. {s.get('municipio', '—')}: score={s.get('score', '—')} "
                f"(lab={s.get('excesso_lab_0_1', '—')}, "
                f"pos={s.get('positividade_anomala_0_1', '—')}, "
                f"lacuna={s.get('lacuna_sinan_0_1', '—')}, "
                f"SIH={s.get('internacoes_graves_0_1', '—')})"
            )
    if rel.briefing_nota_igg or rel.nota_marcadores:
        lines.append(
            f"Marcadores: {(rel.briefing_nota_igg or rel.nota_marcadores)[:220]}"
        )

    lines.extend(
        [
            "",
            "— A · Situação lab-epi [Observado] —",
            rel.variacao_se,
            f"1ª detecção/alerta (SE ref.): {rel.n_primeira_deteccao_alerta} mun.",
            "Top positivos:",
        ]
    )
    for i, x in enumerate(rel.top_positivos, 1):
        lines.append(
            f"  {i}. {x['municipio']} — +{x['positivos']} · "
            f"pos={x['positividade']} · fam={x['familia']}"
        )
    lines.append("Top divergências GAL×SINAN:")
    for i, d in enumerate(rel.top_divergencias, 1):
        lines.append(
            f"  {i}. {d['municipio']} — {d['tipo']} · "
            f"notif={d['notif_sinan']} · exames={d['exames']}"
        )

    lines.extend(
        [
            "",
            "— E · Briefing epidemiológico (5 perguntas) [Observado / Predito] —",
        ]
    )
    lines.append("1) Mais solicitados (N + Δ vs SE-1 + taxa/100 mil):")
    for i, x in enumerate(rel.briefing_mais_solicitados[:10], 1):
        taxa = x.get("frase_taxa_positivos") or ""
        taxa_bit = f" · {taxa}" if taxa else ""
        lines.append(
            f"  {i}. {x['target']} — n_se={x.get('n_se', x['exames'])} · "
            f"n_ant={x.get('n_se_ant', '—')} · Δ={x.get('delta', '—')} "
            f"({x.get('delta_pct', '—')}) {x.get('tendencia', '→')} · "
            f"+{x['positivos']} · pos={x['positividade']}{taxa_bit} "
            f"[{x.get('tipo_sinal', 'Observado')}]"
        )
    lines.append("2) Maior positividade (Δ vs SE-1):")
    for i, x in enumerate(rel.briefing_maior_positividade[:10], 1):
        flags = []
        if x.get("baixa_amostra") == "sim":
            flags.append("baixa_amostra")
        if x.get("caveat_igg") == "sim":
            flags.append("caveat_IgG")
        fl = f" · {', '.join(flags)}" if flags else ""
        lines.append(
            f"  {i}. {x['target']} — pos={x['positividade']} · "
            f"Δ%={x.get('delta_pct', '—')} {x.get('tendencia', '→')} · "
            f"med4SE={x.get('mediana_4se', '—')} · "
            f"{x['exames']} exames{fl} [{x.get('tipo_sinal', 'Observado')}]"
        )
    lines.append("3) Localidades:")
    by_t: dict[str, list[dict[str, str]]] = {}
    for loc in rel.briefing_localidades:
        by_t.setdefault(loc.get("target") or "—", []).append(loc)
    for tgt, locs in list(by_t.items())[:6]:
        muns = ", ".join(
            f"{L['municipio']}(+{L['positivos']})" for L in locs[:5]
        )
        lines.append(f"  · {tgt}: {muns}")
    lines.append("4) Vizinhos na mesma situação:")
    if rel.briefing_vizinhos:
        for i, v in enumerate(rel.briefing_vizinhos[:8], 1):
            lines.append(
                f"  {i}. {v['target']} — {v['par']} · {v['positivos']} · "
                f"{v.get('dist_km', '—')} km [{v.get('tipo_sinal', 'Observado')}]"
            )
    else:
        lines.append("  (nenhum par)")
    lines.append("5) Risco de dispersão:")
    for r in rel.briefing_risco:
        lines.append(f"  · [{r.get('tipo_sinal', 'Observado')}] {r.get('mensagem', '')}")
    if rel.briefing_gal_sinan:
        lines.append("6) GAL×SINAN (qualquer agravo):")
        for g in rel.briefing_gal_sinan[:8]:
            lines.append(
                f"  · {g.get('municipio')} × {g.get('familia')}: "
                f"ex={g.get('exames')} notif={g.get('notificacoes')} "
                f"[{g.get('flag')}]"
            )
    if rel.briefing_geo_nota or rel.briefing_geo_hotspots:
        lines.append(
            f"7) Geo ({rel.briefing_geo_nivel}): {rel.briefing_geo_nota}"
        )
        for h in rel.briefing_geo_hotspots[:5]:
            lines.append(
                f"  · {h.get('municipio')} / {h.get('local')} · "
                f"{h.get('agravo')} n={h.get('n')} ibge={h.get('codigo_ibge')}"
            )
    if rel.briefing_cruzamento:
        presentes = [
            c.get("fonte") for c in rel.briefing_cruzamento if c.get("presente") == "sim"
        ]
        lines.append(
            "Cruzamento DW: "
            + (", ".join(presentes) if presentes else "(nenhuma extra no staging)")
        )
    if rel.briefing_cruzamento_sih_sia:
        lines.append("Cruzamento SIH/SIA (internações correlatas):")
        for row in rel.briefing_cruzamento_sih_sia[:6]:
            lines.append(
                f"  · {row.get('municipio')} × "
                f"{_nome_agravo_pt(str(row.get('cid_familia') or ''))}: "
                f"n={row.get('n')} [{row.get('fonte', 'internações')}]"
            )
        if rel.briefing_cruzamento_sih_sia_caveat:
            lines.append(f"  Caveat: {rel.briefing_cruzamento_sih_sia_caveat[:180]}")
    if rel.internacoes_por_agravo:
        lines.append("Internações por agravo (top mun):")
        for row in rel.internacoes_por_agravo[:15]:
            lines.append(
                f"  · {row.get('familia_pt') or row.get('familia')}: "
                f"{row.get('municipio')} n={row.get('n')}"
            )
    acoes_l = coletar_acoes_lacen(rel, max_n=3)
    if acoes_l:
        lines.append("Apoio laboratorial (só se pertinente ao agravo):")
        for i, a in enumerate(acoes_l, 1):
            lines.append(f"  {i}. {a}")
    rede = rel.briefing_sinais_rede or {}
    if rede.get("presente"):
        lines.append("Sinais IndicaSUS / SISREG:")
        for row in (rede.get("indicasus_ocupacao_top") or [])[:3]:
            lines.append(
                f"  · IndicaSUS: {row.get('tipo_leito')} / {row.get('situacao')} "
                f"n={row.get('n')}"
            )
        for row in (rede.get("sisreg_hosp_top") or [])[:3]:
            lines.append(
                f"  · SISREG hosp: {row.get('municipio')} [{row.get('status')}] "
                f"n={row.get('n')}"
            )
        for row in (rede.get("sisreg_amb_pendente_top") or [])[:2]:
            lines.append(
                f"  · SISREG amb pendente: {row.get('municipio')} n={row.get('n')}"
            )
    if rel.briefing_nota_igg:
        lines.append(f"Nota: {rel.briefing_nota_igg}")
    if rel.briefing_fontes:
        lines.append(f"Fontes briefing: {', '.join(rel.briefing_fontes)}")

    if rel.ve_resumo:
        lines.extend(
            [
                "",
                "— F · Parecer VE (IA + Guia MS) —",
                rel.ve_resumo,
            ]
        )
        for c in rel.ve_casos[:3]:
            lines.append(
                f"  · {c.get('municipio')} × {c.get('target')}: "
                f"{c.get('exames')} ex. / +{c.get('positivos')} "
                f"({c.get('positividade')})"
            )
            lines.append(f"    Veredito: {c.get('veredito', '')[:240]}")
        for r in rel.ve_recomendacoes[:5]:
            lines.append(f"  [{r.get('area')}] {r.get('acao')}")
        if rel.ve_arquivos:
            lines.append(f"  Arquivos: {', '.join(rel.ve_arquivos)}")

    lines.extend(
        [
            "",
            "— B · Rede [Derivado / Observado] —",
            f"TAT p50={rel.tat_mediano}d · p90={rel.tat_p90}d · %≤48h={rel.pct_48h}",
            "Pressão alta/crítica:",
        ]
    )
    for i, p in enumerate(rel.top_pressao, 1):
        lines.append(
            f"  {i}. {p['municipio']} — {p['faixa']} · índice={p['indice']} · "
            f"backlog={p['backlog']} · rejeição={p['rejeicao']}"
        )
    if rel.sla_por_familia:
        lines.append("SLA por família:")
        for s in rel.sla_por_familia:
            lines.append(
                f"  · {s['familia']}: exames={s['exames']} · "
                f"%≤48h={s['pct_48h']} · TAT p90={s['tat_p90']}d · crise={s['sla_crise']}"
            )
    lines.append("Silêncio GAL (vizinho quente):")
    if rel.silencio_vizinho_quente:
        for i, s in enumerate(rel.silencio_vizinho_quente, 1):
            lines.append(
                f"  {i}. {s['municipio']} — {s['tipo_silencio']} · "
                f"vizinho={s['vizinho_quente']}"
            )
    else:
        lines.append("  (nenhum)")

    lines.extend(["", "— C · Ações —", "Fila operacional:"])
    for i, a in enumerate(rel.fila_acoes[:10], 1):
        crs = f" | CRS {a['crs']}" if a.get("crs") and a["crs"] != "—" else ""
        lines.append(
            f"  {i}. {a['municipio']}{crs} | {a['sinal']} | {a['banda']} | "
            f"{a['acao'][:100]} | {a['prazo']} [{a['tipo_sinal']}]"
        )
    lines.append("Predito Alta/Crítica:")
    for i, p in enumerate(rel.preditos_alta, 1):
        lines.append(
            f"  {i}. {p['municipio']} | {p['banda']} | {p['familia']} | "
            f"{p['driver']} | prob={p['prob']}"
        )
    if rel.pressao_predita_top:
        lines.append("Pressão predita (top):")
        for i, p in enumerate(rel.pressao_predita_top, 1):
            lines.append(
                f"  {i}. {p['municipio']} | {p['faixa']} | {p['prob']} | {p['driver']}"
            )

    lines.extend(
        [
            "",
            "— D · Qualidade —",
            rel.cobertura_municipios,
            rel.confirmacao_alertas,
            f"Painel: {rel.dashboard_url}",
            "",
            f"Fonte primária: {rel.fonte_primaria}",
            f"Fontes: {', '.join(rel.fontes_presentes) or '—'}",
            "Modelo: lacen_relatorio_cievs.py",
        ]
    )
    return "\n".join(lines)


def _html_table(headers: list[str], rows_html: list[str], empty: str = "(sem dados)") -> str:
    head = "".join(f"<th style='padding:8px;text-align:left'>{html.escape(h)}</th>" for h in headers)
    body = "".join(rows_html) if rows_html else (
        f"<tr><td colspan='{len(headers)}' style='padding:8px'>{html.escape(empty)}</td></tr>"
    )
    return (
        "<table style='border-collapse:collapse;width:100%;font-size:13px;"
        "border:1px solid #d0d7e2;margin:8px 0 16px'>"
        f"<thead style='background:#1B3281;color:#fff'><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def to_email_html(rel: RelatorioCIEVS) -> str:
    kpi_cards = [
        ("Positivos SE", rel.kpi_positivos_se, rel.kpi_variacao_pct),
        ("Exames SE", rel.kpi_exames_se, f"{rel.kpi_municipios_exame} mun."),
        ("TAT p50 / p90", f"{rel.kpi_tat_p50} / {rel.kpi_tat_p90}d", ""),
        ("% ≤48h", rel.kpi_pct_48h, ""),
        ("Pressão máx", rel.kpi_pressao_max, ""),
        ("Silêncios", rel.kpi_silencios, ""),
        ("Confirmação", rel.kpi_confirmacao, ""),
    ]
    cards_html = []
    for title, value, sub in kpi_cards:
        cards_html.append(
            "<td style='background:#f4f7fb;border:1px solid #d0d7e2;border-radius:6px;"
            "padding:10px 12px;min-width:90px;vertical-align:top'>"
            f"<div style='font-size:11px;color:#5a6a85;text-transform:uppercase;"
            f"letter-spacing:.03em'>{html.escape(title)}</div>"
            f"<div style='font-size:20px;font-weight:700;color:#1B3281;margin-top:4px'>"
            f"{html.escape(value)}</div>"
            f"<div style='font-size:12px;color:#3d4f6f'>{html.escape(sub)}</div>"
            "</td>"
        )

    pos_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(x['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['positivos'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['positividade'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['familia'])}</td>"
        f"<td style='padding:6px 8px'><small>{html.escape(x['tipo_sinal'])}</small></td>"
        "</tr>"
        for x in rel.top_positivos
    ]
    div_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(d['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(d['tipo'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(d['notif_sinan'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(d['exames'])}</td>"
        "</tr>"
        for d in rel.top_divergencias
    ]
    press_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(p['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['faixa'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['indice'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['backlog'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['rejeicao'])}</td>"
        "</tr>"
        for p in rel.top_pressao
    ]
    sla_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(s['familia'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['exames'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['pct_48h'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['tat_p90'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['sla_crise'])}</td>"
        "</tr>"
        for s in rel.sla_por_familia
    ]
    sil_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(s['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['tipo_silencio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(s['vizinho_quente'])}</td>"
        "</tr>"
        for s in rel.silencio_vizinho_quente
    ]
    fila_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(a['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(a.get('crs') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(a['sinal'])}<br>"
        f"<small>{html.escape(a['tipo_sinal'])}</small></td>"
        f"<td style='padding:6px 8px'><b>{html.escape(a['banda'])}</b></td>"
        f"<td style='padding:6px 8px'>{html.escape(a['acao'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(a['prazo'])}</td>"
        "</tr>"
        for a in rel.fila_acoes[:10]
    ]
    pred_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(p['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['banda'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['familia'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['driver'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['prob'])}</td>"
        "</tr>"
        for p in rel.preditos_alta
    ]
    press_pred_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(p['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['faixa'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['prob'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(p['driver'])}</td>"
        "</tr>"
        for p in rel.pressao_predita_top
    ]
    sol_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(x['target'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x.get('n_se', x['exames']))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x.get('n_se_ant', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x.get('delta', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x.get('delta_pct', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x.get('tendencia', '→'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['positividade'])}</td>"
        f"<td style='padding:6px 8px'>"
        f"{html.escape(x.get('frase_taxa_positivos') or x.get('taxa_positivos_100k') or '—')}"
        f"</td>"
        f"<td style='padding:6px 8px'><small>{html.escape(x.get('tipo_sinal', 'Observado'))}</small></td>"
        "</tr>"
        for x in rel.briefing_mais_solicitados[:10]
    ]
    posi_rows = []
    for x in rel.briefing_maior_positividade[:10]:
        flags = []
        if x.get("baixa_amostra") == "sim":
            flags.append("baixa_amostra")
        if x.get("caveat_igg") == "sim":
            flags.append("caveat IgG")
        posi_rows.append(
            "<tr style='border-bottom:1px solid #e6ebf2'>"
            f"<td style='padding:6px 8px'>{html.escape(x['target'])}</td>"
            f"<td style='padding:6px 8px'>{html.escape(x['positividade'])}</td>"
            f"<td style='padding:6px 8px'>{html.escape(x.get('delta_pct', '—'))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(x.get('tendencia', '→'))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(x.get('mediana_4se', '—'))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(x['exames'])}</td>"
            f"<td style='padding:6px 8px'>{html.escape(', '.join(flags) or '—')}</td>"
            "</tr>"
        )
    loc_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(x['target'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['municipio'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['positivos'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['exames'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(x['positividade'])}</td>"
        "</tr>"
        for x in rel.briefing_localidades[:20]
    ]
    viz_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(v['target'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(v['par'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(v['positivos'])}</td>"
        f"<td style='padding:6px 8px'>{html.escape(v.get('dist_km', '—'))}</td>"
        f"<td style='padding:6px 8px'><small>{html.escape(v.get('tipo_sinal', 'Observado'))}</small></td>"
        "</tr>"
        for v in rel.briefing_vizinhos[:10]
    ]
    risco_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'><small>{html.escape(r.get('tipo_sinal', 'Observado'))}</small></td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('mensagem', ''))}</td>"
        "</tr>"
        for r in rel.briefing_risco
    ]
    cartao_rows = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('evento', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('probabilidade', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('impacto', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('confianca', '—'))}</td>"
        f"<td style='padding:6px 8px'><b>{html.escape(c.get('veredito', '—'))}</b></td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('taxa_positivos', '—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(_zona_canal_pt(str(c.get('zona_bortman') or '')) if c.get('zona_bortman') else '—')}</td>"
        f"<td style='padding:6px 8px'><small>"
        f"{html.escape(_tg_clip(str(c.get('acao_cievs') or ''), 120))}"
        f"</small></td>"
        "</tr>"
        for c in (rel.cartoes_risco or [])[:8]
    ]
    canal_rows_html = [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('municipio_pt') or r.get('municipio') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('agravo_pt') or r.get('agravo') or '—')}</td>"
        f"<td style='padding:6px 8px'><b>{html.escape(r.get('zona_pt') or _zona_canal_pt(str(r.get('zona') or '')))}</b></td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('casos') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('exames_marcador') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('mediana') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('limite_superior') or '—')}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('razao_vs_mediana') or '—')}</td>"
        "</tr>"
        for r in (rel.canal_endemico or [])[:10]
    ]
    nota_igg_html = (
        f"<p style='background:#f0f4fa;border-left:4px solid #1B3281;padding:8px 12px;"
        f"font-size:13px'>{html.escape(rel.briefing_nota_igg)}</p>"
        if rel.briefing_nota_igg
        else ""
    )
    briefing_fontes_txt = ", ".join(rel.briefing_fontes) or "—"

    aviso_html = (
        f"<p style='background:#fff4e5;border-left:4px solid #e6a23c;padding:10px 12px'>"
        f"{html.escape(rel.aviso_atraso)}</p>"
        if rel.aviso_atraso
        else ""
    )
    banda_txt = ", ".join(f"{b['banda']}={b['n']}" for b in rel.contagem_banda_risco) or "—"
    faixa_txt = ", ".join(
        f"{b['banda']}={b['n']}" for b in rel.contagem_faixa_pressao
    ) or "—"
    crs_txt = ", ".join(f"{c['crs']} ({c['n']})" for c in rel.crs_top) or "—"

    # Cabeçalho institucional com logos (data-URI) quando disponíveis
    logo_uris: list[tuple[str, str]] = []
    try:
        from lacen_theme import logo_data_uri as _logo_uri

        for _key, _cap in (
            ("ses_governo", "SES-MT"),
            ("cievs_ses", "CIEVS-MT"),
            ("cievs_rede_ses", "Rede CIEVS"),
        ):
            _uri = _logo_uri(_key)
            if _uri:
                logo_uris.append((_cap, _uri))
    except Exception:
        logo_uris = []
    if logo_uris:
        _cells = "".join(
            "<td align='center' style='padding:4px 8px'>"
            f"<img src='{uri}' alt='{html.escape(cap)}' "
            "style='max-height:42px;max-width:140px;display:block;margin:0 auto'/>"
            f"<div style='font-size:10px;color:#c8d4ef;margin-top:2px'>{html.escape(cap)}</div>"
            "</td>"
            for cap, uri in logo_uris
        )
        logos_bar_html = (
            "<tr><td style='background:#0f1f4d;padding:10px 16px'>"
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
            f"<tr>{_cells}</tr></table></td></tr>"
        )
    else:
        logos_bar_html = ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>{html.escape(_cabecalho(rel))}</title></head>
<body style="margin:0;padding:0;background:#eef2f7;color:#1a1a1a;
font-family:'Segoe UI',Tahoma,Arial,sans-serif;line-height:1.45">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7">
<tr><td align="center" style="padding:16px">
<table role="presentation" width="720" cellpadding="0" cellspacing="0"
 style="max-width:720px;background:#ffffff;border:1px solid #d0d7e2">
{logos_bar_html}
<tr><td style="background:linear-gradient(135deg,#1B3281,#2a4fa3);color:#fff;padding:18px 22px">
  <div style="font-size:12px;letter-spacing:.08em;opacity:.9">
    SES-MT · LACEN · CIEVS · Vigidesastres</div>
  <div style="font-size:22px;font-weight:700;margin-top:4px">{html.escape(get_nome_ferramenta())}</div>
  <div style="margin-top:6px;font-size:13px">
    SE <b>{html.escape(rel.semana_epidemiologica)}</b> ·
    Leitura: <b>{html.escape(rel.leitura_situacional)}</b><br>
    Gerado em {html.escape(rel.gerado_em)}
  </div>
</td></tr>
<tr><td style="padding:16px 22px">
{aviso_html}
<table role="presentation" width="100%" cellpadding="4" cellspacing="4"><tr>
{"".join(cards_html)}
</tr></table>
<p style="font-size:12px;color:#5a6a85"><em>{html.escape(rel.nota)}</em></p>

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
Visão executiva — cartões de risco (CIEVS)</h3>
<p style="font-size:13px;color:#3d4f6f">
Probabilidade × impacto × confiança. Veredito operacional — não declara
surto/epidemia automaticamente (Guia MS).
</p>
{_html_table(
    ["Evento", "Prob.", "Impacto", "Confiança", "Veredito", "Taxa", "Canal endêmico", "Ação CIEVS"],
    cartao_rows,
    "(sem cartões nesta SE)",
)}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
Canal endêmico — comparação histórica (método de Bortman)</h3>
<p style="font-size:13px;color:#3d4f6f">
Compara os exames positivos da semana atual (marcador de alerta, não IgG)
com a mesma semana nos anos anteriores (canal de Bortman).
Zona epidêmica (estatística) = acima do P75 — investigar, não declarar.
(mediana e limite superior). <b>Acima do limite histórico</b> = priorizar
investigação; <b>não declara epidemia automaticamente</b> (Guia MS).
</p>
{_html_table(
    ["Município", "Agravo", "Zona (estatística)", "Exames positivos", "Exames no marcador", "Mediana", "Limite superior", "vs mediana"],
    canal_rows_html,
    "(nenhum município×agravo em alerta/epidemia nesta SE)",
)}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
Prioridade municipal — proposta para homologação</h3>
<p style="font-size:13px;color:#3d4f6f">
Fórmula: <code>score = (3×excesso_lab + 2×pos_marcador_alerta + 1×lacuna_sinan
+ 1×internações) / pesos válidos</code>. Ausente ≠ 0. Excesso lab = zona do canal.
Não substitui decisão da VE/CIEVS.
</p>
{_html_table(
    ["Município", "Score", "Excesso lab", "Pos. anômala", "Lacuna SINAN", "Internações"],
    [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(str(s.get('municipio') or ''))}</td>"
        f"<td style='padding:6px 8px'><b>{html.escape(str(s.get('score') or ''))}</b></td>"
        f"<td style='padding:6px 8px'>{html.escape(str(s.get('excesso_lab_0_1') or ''))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(str(s.get('positividade_anomala_0_1') or ''))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(str(s.get('lacuna_sinan_0_1') or ''))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(str(s.get('internacoes_graves_0_1') or ''))}</td>"
        "</tr>"
        for s in (rel.score_prioridade or [])[:10]
    ],
    "(score ainda não calculado nesta SE)",
)}
{f"<p style='font-size:12px;color:#5a6a82'><i>{html.escape((rel.briefing_nota_igg or rel.nota_marcadores or '')[:320])}</i></p>" if (rel.briefing_nota_igg or rel.nota_marcadores) else ""}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
A — Situação lab-epi</h3>
<p>{html.escape(rel.variacao_se)}</p>
<p>1ª detecção/alerta na SE: <b>{rel.n_primeira_deteccao_alerta}</b> municípios</p>
{_html_table(["Município", "Positivos", "Positividade", "Família", "Sinal"], pos_rows)}
{_html_table(["Município", "Tipo", "Notif. SINAN", "Exames"], div_rows, "(nenhuma divergência)")}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
E — Briefing epidemiológico (5 perguntas)</h3>
<p style="font-size:13px;color:#3d4f6f">
Sala de situação — mesma SE de referência. Rótulos <b>Observado</b> (lab) e
<b>Predito</b> (ML). Fontes: {html.escape(briefing_fontes_txt)}.
</p>
{nota_igg_html}
<p><b>1) Mais solicitados</b> <small>(n_se · Δ vs SE-1)</small></p>
{_html_table(["Agravo", "n_se", "n_se_ant", "Δ", "Δ%", "Tend.", "Positividade", "Taxa/100 mil", "Sinal"], sol_rows)}
<p><b>2) Maior positividade</b>
<small style="color:#5a6a85"> · min. 30 exames; Δ% vs SE-1; mediana 4 SE</small></p>
{_html_table(["Agravo", "Positividade", "Δ%", "Tend.", "Med.4SE", "Exames", "Flag"], posi_rows)}
<p><b>3) Localidades</b> (top municípios por positivos / exames)</p>
{_html_table(["Agravo", "Município", "Positivos", "Exames", "Positividade"], loc_rows)}
<p><b>4) Vizinhos na mesma situação</b></p>
{_html_table(["Agravo", "Par", "Positivos", "Dist. km", "Sinal"], viz_rows, "(nenhum par vizinho com positivos)")}
<p><b>5) Risco de dispersão</b></p>
{_html_table(["Sinal", "Interpretação"], risco_rows, "(sem sinal)")}
<p><b>6) GAL×SINAN</b> (qualquer agravo — mun×família)</p>
{_html_table(
    ["Município", "Família", "Exames", "Notif.", "Flag"],
    [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(g.get('municipio','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(g.get('familia','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(g.get('exames','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(g.get('notificacoes','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(g.get('flag','—'))}</td>"
        "</tr>"
        for g in rel.briefing_gal_sinan[:12]
    ],
    "(sem divergência acima do limiar)",
)}
<p><b>7) Geo</b> ({html.escape(rel.briefing_geo_nivel)}) —
<small>{html.escape(rel.briefing_geo_nota)}</small></p>
{_html_table(
    ["Município", "Local", "Agravo", "N", "IBGE"],
    [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(h.get('municipio','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(h.get('local','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(h.get('agravo','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(h.get('n','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(h.get('codigo_ibge','') )}</td>"
        "</tr>"
        for h in rel.briefing_geo_hotspots[:10]
    ],
    "(sem hotspots)",
)}
<p><b>Cruzamento DW</b> — ver <code>conhecimento_ve/cruzamento_bases.md</code></p>
{_html_table(
    ["Fonte", "Status", "Quando agrega"],
    [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('fonte','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('status','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(c.get('quando_agrega','—'))}</td>"
        "</tr>"
        for c in rel.briefing_cruzamento
    ],
    "(inventário vazio)",
)}
<p><b>Internações por agravo</b> (hospital — top municípios)</p>
{_html_table(
    ["Agravo", "Município", "N", "Fonte"],
    [
        "<tr style='border-bottom:1px solid #e6ebf2'>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('familia_pt') or r.get('familia','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('municipio','—'))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(str(r.get('n','—')))}</td>"
        f"<td style='padding:6px 8px'>{html.escape(r.get('fonte','internações'))}</td>"
        "</tr>"
        for r in (rel.internacoes_por_agravo or [])[:15]
    ],
    "(sem agregados de internação nesta remessa)",
)}
{f"<p style='font-size:12px;color:#5a6a82'><i>{html.escape(rel.briefing_cruzamento_sih_sia_caveat[:280])}</i></p>" if rel.briefing_cruzamento_sih_sia_caveat else ""}
{("".join([
    "<p><b>Apoio laboratorial</b> <i>(só se pertinente ao agravo)</i></p><ul>",
    "".join(f"<li>{html.escape(a)}</li>" for a in coletar_acoes_lacen(rel, max_n=3)),
    "</ul>",
]) if coletar_acoes_lacen(rel, max_n=3) else "")}
<p><b>Sinais IndicaSUS / SISREG</b></p>
{_html_table(
    ["Fonte", "Município/Tipo", "Status", "N"],
    (
        [
            "<tr style='border-bottom:1px solid #e6ebf2'>"
            f"<td style='padding:6px 8px'>IndicaSUS</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('tipo_leito','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('situacao','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('n','—')))}</td>"
            "</tr>"
            for r in ((rel.briefing_sinais_rede or {}).get("indicasus_ocupacao_top") or [])[:5]
        ]
        + [
            "<tr style='border-bottom:1px solid #e6ebf2'>"
            f"<td style='padding:6px 8px'>SISREG/hosp</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('municipio','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('status','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('n','—')))}</td>"
            "</tr>"
            for r in ((rel.briefing_sinais_rede or {}).get("sisreg_hosp_top") or [])[:5]
        ]
        + [
            "<tr style='border-bottom:1px solid #e6ebf2'>"
            f"<td style='padding:6px 8px'>SISREG/amb</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('municipio','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('status','—')))}</td>"
            f"<td style='padding:6px 8px'>{html.escape(str(r.get('n','—')))}</td>"
            "</tr>"
            for r in ((rel.briefing_sinais_rede or {}).get("sisreg_amb_pendente_top") or [])[:4]
        ]
    )
    if (rel.briefing_sinais_rede or {}).get("presente")
    else [],
    "(sem IndicaSUS/SISREG no staging)",
)}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
F — Parecer VE (IA + Guia MS)</h3>
<p style="font-size:13px;color:#3d4f6f">
Sinal laboratorial ≠ declaração automática de surto. Critérios do Guia de
Vigilância MS exigem definição de caso, comparação com o esperado e investigação.
{" · LLM rewrite ativo." if rel.ve_usou_llm else ""}
</p>
<p>{html.escape(rel.ve_resumo or "(parecer VE não gerado nesta remessa)")}</p>
{"".join(
    f"<div style='background:#f0f4fa;border-left:4px solid #1B3281;padding:8px 12px;margin:8px 0'>"
    f"<b>{html.escape(c.get('titulo') or (c.get('municipio','')+' × '+c.get('target','')))}</b><br>"
    f"{html.escape(c.get('municipio',''))} — {html.escape(c.get('target',''))}: "
    f"{html.escape(c.get('exames',''))} exames / +{html.escape(c.get('positivos',''))} "
    f"({html.escape(c.get('positividade',''))})<br>"
    f"<small>{html.escape((c.get('veredito') or '')[:400])}</small></div>"
    for c in rel.ve_casos[:3]
)}
{"<p><b>Recomendações (topo)</b></p><ul>" + "".join(
    f"<li><b>{html.escape(r.get('area',''))}:</b> {html.escape(r.get('acao',''))}</li>"
    for r in rel.ve_recomendacoes[:6]
) + "</ul>" if rel.ve_recomendacoes else ""}
{"<p style='font-size:12px;color:#5a6a85'>Arquivos: " + html.escape(", ".join(rel.ve_arquivos)) + "</p>" if rel.ve_arquivos else ""}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
B — Rede laboratorial</h3>
<p>TAT mediano: <b>{html.escape(rel.tat_mediano)} d</b> ·
p90: <b>{html.escape(rel.tat_p90)} d</b> ·
%≤48h: <b>{html.escape(rel.pct_48h)}</b></p>
<p style="font-size:13px">Faixas de pressão: {html.escape(faixa_txt)}</p>
{_html_table(["Município", "Faixa", "Índice", "Backlog", "Rejeição"], press_rows)}
{_html_table(["Família", "Exames", "%≤48h", "TAT p90", "SLA crise"], sla_rows, "(SLA por família indisponível)")}
{_html_table(["Município", "Tipo silêncio", "Vizinho quente"], sil_rows, "(nenhum silêncio GAL com vizinho quente)")}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
C — Ações prioritárias</h3>
{_html_table(["Município", "CRS", "Sinal", "Banda", "Ação", "Prazo"], fila_rows, "(fila vazia)")}
<p><b>Predito — risco Alta/Crítica</b>
<small style="color:#5a6a85"> · bandas: {html.escape(banda_txt)}</small></p>
{_html_table(["Município", "Banda", "Família", "Drivers", "Prob."], pred_rows, "(nenhum)")}
<p><b>Predito — pressão de rede (top 3)</b></p>
{_html_table(["Município", "Faixa", "Prob.", "Drivers"], press_pred_rows, "(nenhum)")}

<h3 style="color:#1B3281;border-bottom:2px solid #1B3281;padding-bottom:4px">
D — Qualidade e fontes</h3>
<p>{html.escape(rel.cobertura_municipios)}</p>
<p>{html.escape(rel.confirmacao_alertas)}</p>
<p>Laboratórios com maior volume recente (DW): {html.escape(crs_txt)}</p>
<p><a href="{html.escape(rel.dashboard_url)}"
 style="display:inline-block;background:#1B3281;color:#fff;text-decoration:none;
 padding:10px 16px;border-radius:4px;font-weight:600">Abrir painel</a></p>
<p style="font-size:12px;color:#5a6a85;margin-top:18px">
Fonte primária: <b>{html.escape(rel.fonte_primaria)}</b><br>
Fontes: {html.escape(", ".join(rel.fontes_presentes) or "—")}<br>
Briefing: integrated_weekly + municipio_vizinhos
{" + ml_risco_predito" if any("ml_risco" in f for f in rel.briefing_fontes) else ""}<br>
Modelo: lacen_relatorio_cievs.py · lacen_briefing_epi.py · lacen_agente_ve.py
</p>
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def coletar_prioridades_secretario(
    rel: RelatorioCIEVS, *, max_n: int = 5
) -> list[dict[str, str]]:
    """
    Prioridades territoriais para o Secretário encaminhar aos gestores.
    Fonte principal: canal endêmico (alerta/epidemia estatística).
    Complementa com Juína/VE se ainda for sinal e não estiver no canal.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(
        mun: str,
        agravo: str,
        acao: str,
        *,
        zona: str = "",
        origem: str = "canal",
    ) -> None:
        if len(out) >= max_n:
            return
        mun_pt = (mun or "").strip() or "—"
        if mun_pt.isupper() or "_" in mun_pt:
            mun_pt = _mun_titulo(mun_pt)
        agr_raw = (agravo or "").strip()
        if "_" in agr_raw or agr_raw == agr_raw.casefold():
            agr_pt = _nome_agravo_pt(agr_raw)
        else:
            agr_pt = agr_raw or "—"
        key = f"{mun_pt.casefold()}|{agr_pt.casefold()}"
        if key in seen or not mun_pt or mun_pt == "—":
            return
        seen.add(key)
        out.append(
            {
                "municipio": mun_pt,
                "agravo": agr_pt,
                "acao": acao.strip(),
                "zona": zona,
                "origem": origem,
            }
        )

    canal = list(rel.canal_endemico or [])
    canal_sorted = sorted(
        canal,
        key=lambda r: (
            0 if str(r.get("zona") or "").casefold() == "epidemia" else 1,
            str(r.get("municipio_pt") or ""),
        ),
    )
    for c in canal_sorted:
        zona = str(c.get("zona") or "").casefold()
        if zona not in {"epidemia", "alerta"}:
            continue
        mun = str(c.get("municipio_pt") or c.get("municipio") or "")
        agr = str(c.get("agravo_pt") or c.get("agravo") or "")
        pos = c.get("casos") or "—"
        lim = c.get("limite_superior") or "—"
        if zona == "epidemia":
            acao = (
                f"investigar ({pos} exames positivos acima do limite histórico "
                f"{lim} no marcador de alerta); não declarar epidemia automaticamente"
            )
            zona_lbl = "zona epidêmica (estatística)"
        else:
            acao = (
                f"reforçar monitoramento e cruzar com notificação "
                f"({pos} exames positivos; limite histórico {lim})"
            )
            zona_lbl = "zona de alerta (estatística)"
        _add(mun, agr, acao, zona=zona_lbl, origem="canal")

    for c in rel.ve_casos or []:
        mun_raw = str(c.get("municipio") or "")
        agr_raw = str(c.get("agravo") or c.get("target") or "")
        mun_u = mun_raw.upper()
        if "JUINA" not in mun_u and "JUÍNA" not in mun_u:
            continue
        mun_pt = _mun_titulo(mun_raw)
        agr_pt = _nome_agravo_pt(agr_raw)
        key = f"{mun_pt.casefold()}|{agr_pt.casefold()}"
        if key in seen:
            continue
        exames = c.get("exames") or "—"
        pos = c.get("positivos") or "—"
        _add(
            mun_pt,
            agr_pt,
            f"abrir/atualizar investigação ({exames} exames / +{pos} positivos); "
            f"cruzar lab × notificação — não declarar surto automaticamente",
            zona="sinal laboratorial",
            origem="ve",
        )

    for x in (rel.briefing_mais_solicitados or [])[:3]:
        tgt = str(x.get("target") or "")
        if "dengue" not in tgt.casefold():
            continue
        delta = _parse_delta_pct(x.get("delta_pct"))
        if delta is None or delta < 50:
            continue
        n_se = x.get("n_se", x.get("exames", "—"))
        var = _fmt_variacao_pt(x.get("delta_pct"), x.get("tendencia"))
        _add(
            "Estado (demanda)",
            "dengue",
            f"acompanhar pressão assistencial ({n_se} exames; {var}); "
            f"baixa confirmação laboratorial — reforçar notificação e busca ativa",
            zona="demanda elevada",
            origem="demanda",
        )
        break

    return out[:max_n]


def _situacao_secretario(rel: RelatorioCIEVS, prioridades: list[dict[str, str]]) -> str:
    """2–3 frases do que importa nesta semana (linguagem de gestão)."""
    partes: list[str] = []
    hbv = [
        p
        for p in prioridades
        if "hepatite" in (p.get("agravo") or "").casefold()
        and p.get("origem") == "canal"
    ]
    if hbv:
        muns = ", ".join(dict.fromkeys(p["municipio"] for p in hbv))
        partes.append(
            f"Sinais de hepatite B acima do histórico (marcador de alerta) em {muns}."
        )
    dengue = next(
        (p for p in prioridades if "dengue" in (p.get("agravo") or "").casefold()),
        None,
    )
    if dengue:
        partes.append(
            "Demanda de exames de dengue elevada no estado, com baixa confirmação "
            "laboratorial — pressão sobre a rede e a vigilância municipal."
        )
    if not partes:
        leitura = (rel.leitura_situacional or "acompanhamento rotineiro").replace(
            "_", " "
        )
        partes.append(
            f"Leitura situacional da semana: {leitura}. "
            f"Priorizar os municípios listados abaixo."
        )
    partes.append(
        "Este alerta orienta investigação e gestão local; "
        "não constitui declaração automática de surto ou epidemia."
    )
    return " ".join(partes)


def _se_secretario_legivel(se: str) -> str:
    """2026-SE30 → SE 30/2026."""
    m = re.search(r"(20\d{2})\s*[-_]?SE?(\d{1,2})", str(se or ""), re.I)
    if m:
        return f"SE {int(m.group(2))}/{m.group(1)}"
    return _tg_se_legivel(se) if se else "—"


def to_secretario_subject(rel: RelatorioCIEVS) -> str:
    se = _se_secretario_legivel(rel.semana_epidemiologica)
    return (
        f"Radar LACEN — Alerta estratégico {se} "
        f"(encaminhar aos gestores)"
    )


def to_secretario_plain(rel: RelatorioCIEVS) -> str:
    """Texto curto para e-mail / MD — 1 página, linguagem de gestão."""
    prioridades = coletar_prioridades_secretario(rel, max_n=5)
    situacao = _situacao_secretario(rel, prioridades)
    se = _se_secretario_legivel(rel.semana_epidemiologica)
    leitura = (rel.leitura_situacional or "—").replace("_", " ")
    lines: list[str] = [
        "Radar LACEN · SES-MT / CIEVS",
        f"Alerta estratégico — {se}",
        f"Gerado em: {rel.gerado_em or '—'}",
        f"Leitura situacional: {leitura}",
        "",
        "SITUAÇÃO",
        situacao,
        "",
        "PRIORIDADES PARA OS MUNICÍPIOS",
    ]
    if prioridades:
        for i, p in enumerate(prioridades, 1):
            lines.append(
                f"{i}. {p['municipio']} — {p['agravo']} — {p['acao']}"
            )
    else:
        lines.append("(Nenhuma prioridade territorial acima do histórico nesta SE.)")

    lines.extend(
        [
            "",
            "PEDIDO AOS GESTORES MUNICIPAIS",
            "1. Abrir ou atualizar a investigação no município citado.",
            "2. Cruzar exame laboratorial × notificação (SINAN).",
            "3. Reforçar busca ativa e aplicar a definição de caso do Ministério da Saúde.",
            "4. Retornar status ao CIEVS / VE regional em até 7 dias.",
            "",
            "LEITURA CORRETA",
            "Sinal laboratorial orienta investigação — não declara surto automaticamente. "
            "IgG/sorologia refletem soroprevalência e não contam como epidemia aguda. "
            "Zonas do canal endêmico são estatísticas (comparação histórica), não declaração formal.",
            "",
            f"Painel: {DASHBOARD_URL}",
            "Detalhamento técnico disponível no alerta CIEVS / Radar LACEN.",
        ]
    )
    return "\n".join(lines)


def to_secretario_html(rel: RelatorioCIEVS) -> str:
    """HTML institucional limpo, 1 coluna, imprimível/encaminhável."""
    prioridades = coletar_prioridades_secretario(rel, max_n=5)
    situacao = _situacao_secretario(rel, prioridades)
    se = _se_secretario_legivel(rel.semana_epidemiologica)
    leitura = html.escape((rel.leitura_situacional or "—").replace("_", " "))
    gerado = html.escape(rel.gerado_em or "—")

    if prioridades:
        lis = "".join(
            (
                "<li style='margin:0 0 10px 0;line-height:1.45'>"
                f"<b>{html.escape(p['municipio'])}</b> — "
                f"{html.escape(p['agravo'])} — "
                f"{html.escape(p['acao'])}"
                "</li>"
            )
            for p in prioridades
        )
        lista_html = f"<ol style='margin:8px 0 0 1.2em;padding:0'>{lis}</ol>"
    else:
        lista_html = (
            "<p style='margin:8px 0 0 0;color:#555'>"
            "Nenhuma prioridade territorial acima do histórico nesta SE."
            "</p>"
        )

    checklist = """
<ol style="margin:8px 0 0 1.2em;padding:0;line-height:1.5">
<li>Abrir ou atualizar a investigação no município citado.</li>
<li>Cruzar exame laboratorial × notificação (SINAN).</li>
<li>Reforçar busca ativa e aplicar a definição de caso do Ministério da Saúde.</li>
<li>Retornar status ao CIEVS / VE regional em até 7 dias.</li>
</ol>
"""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(to_secretario_subject(rel))}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;color:#1a1a1a;
font-family:Georgia,'Times New Roman',serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"
style="background:#f4f6f8;padding:24px 12px">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0"
style="max-width:640px;width:100%;background:#ffffff;border:1px solid #d8dee6">
<tr><td style="padding:28px 32px 8px 32px;border-bottom:3px solid #0b3d5c">
<div style="font-size:13px;letter-spacing:0.04em;text-transform:uppercase;
color:#0b3d5c;font-family:Arial,Helvetica,sans-serif">Radar LACEN · SES-MT / CIEVS</div>
<h1 style="margin:8px 0 4px 0;font-size:22px;font-weight:normal;color:#0b3d5c;
font-family:Arial,Helvetica,sans-serif">Alerta estratégico</h1>
<p style="margin:0;font-size:14px;color:#444;font-family:Arial,Helvetica,sans-serif">
{html.escape(se)} · Leitura situacional: <b>{leitura}</b><br>
<span style="color:#777">Gerado em: {gerado}</span>
</p>
</td></tr>
<tr><td style="padding:20px 32px 8px 32px">
<h2 style="margin:0 0 8px 0;font-size:15px;font-family:Arial,Helvetica,sans-serif;
color:#0b3d5c;text-transform:uppercase;letter-spacing:0.03em">Situação</h2>
<p style="margin:0;font-size:15px;line-height:1.55">{html.escape(situacao)}</p>
</td></tr>
<tr><td style="padding:16px 32px 8px 32px">
<h2 style="margin:0 0 4px 0;font-size:15px;font-family:Arial,Helvetica,sans-serif;
color:#0b3d5c;text-transform:uppercase;letter-spacing:0.03em">
Prioridades para os municípios</h2>
{lista_html}
</td></tr>
<tr><td style="padding:16px 32px 8px 32px">
<h2 style="margin:0 0 4px 0;font-size:15px;font-family:Arial,Helvetica,sans-serif;
color:#0b3d5c;text-transform:uppercase;letter-spacing:0.03em">
Pedido aos gestores municipais</h2>
{checklist}
</td></tr>
<tr><td style="padding:16px 32px 8px 32px">
<h2 style="margin:0 0 8px 0;font-size:15px;font-family:Arial,Helvetica,sans-serif;
color:#0b3d5c;text-transform:uppercase;letter-spacing:0.03em">Leitura correta</h2>
<p style="margin:0;font-size:13px;line-height:1.5;color:#444">
Sinal laboratorial orienta investigação — não declara surto automaticamente.
IgG/sorologia refletem soroprevalência e não contam como epidemia aguda.
Zonas do canal endêmico são estatísticas (comparação histórica), não declaração formal.
</p>
</td></tr>
<tr><td style="padding:20px 32px 28px 32px;border-top:1px solid #e5e9ef;
font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#666;line-height:1.5">
<a href="{html.escape(DASHBOARD_URL)}" style="color:#0b3d5c">Painel Radar LACEN</a>
<br>Detalhamento técnico disponível no alerta CIEVS / Radar LACEN.
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def to_secretario_telegram(rel: RelatorioCIEVS, *, max_chars: int = 3500) -> str:
    """Uma mensagem Telegram HTML — alerta estratégico (não o CIEVS técnico)."""
    prioridades = coletar_prioridades_secretario(rel, max_n=5)
    situacao = _situacao_secretario(rel, prioridades)
    se = _se_secretario_legivel(rel.semana_epidemiologica)
    leitura = (rel.leitura_situacional or "—").replace("_", " ")

    lines: list[str] = [
        "<b>Radar LACEN — Alerta estratégico</b>",
        f"{html.escape(se)} · SES-MT / CIEVS · <b>{html.escape(leitura)}</b>",
        html.escape(rel.gerado_em or ""),
        "",
        "<b>Situação</b>",
        html.escape(_tg_clip(situacao, 420)),
        "",
        "<b>Prioridades para os municípios</b>",
    ]
    if prioridades:
        for i, p in enumerate(prioridades, 1):
            lines.append(
                html.escape(
                    _tg_clip(
                        f"{i}. {p['municipio']} — {p['agravo']} — {p['acao']}",
                        220,
                    )
                )
            )
    else:
        lines.append(html.escape("(Sem prioridade territorial acima do histórico.)"))

    lines.extend(
        [
            "",
            "<b>Pedido aos gestores</b>",
            html.escape(
                "1) Investigar  2) Cruzar lab × SINAN  "
                "3) Busca ativa / definição MS  4) Retorno ao CIEVS em 7 dias"
            ),
            "",
            "<i>"
            + html.escape(
                "Não declara surto automaticamente. "
                "Canal = zona estatística; IgG ≠ epidemia aguda."
            )
            + "</i>",
            f'<a href="{html.escape(DASHBOARD_URL)}">Painel Radar LACEN</a>',
        ]
    )
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def format_email_secretario(rel: RelatorioCIEVS) -> tuple[str, str, str]:
    """Retorna (assunto, corpo_texto, corpo_html) do alerta estratégico."""
    return (
        to_secretario_subject(rel),
        to_secretario_plain(rel),
        to_secretario_html(rel),
    )


def format_email(rel: RelatorioCIEVS) -> tuple[str, str, str]:
    """Retorna (assunto, corpo_texto, corpo_html)."""
    return to_email_subject(rel), to_email_plain(rel), to_email_html(rel)


if __name__ == "__main__":
    rel = montar_relatorio(OUTDIR_DEFAULT)
    subj, plain, _ = format_email(rel)
    print(subj)
    print("-" * 60)
    print(plain)
    print("-" * 60)
    for i, msg in enumerate(to_telegram_messages(rel), 1):
        print(f"--- Telegram parte {i} ---")
        print(msg)
