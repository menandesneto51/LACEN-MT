# -*- coding: utf-8 -*-
"""SINAN do DW → ``sinan_weekly_municipio.csv`` (notificações por SE × município × agravo).

Antes, o ETL copiava ``SELECT TOP (30000) *`` de cada ``VW_SINAN_*`` (sem ORDER
BY: linhas arbitrárias) para o staging e **nunca** agregava esses dados; a série
SINAN vinha só do CSV local ``SINAN 2010 a 2025.csv`` e parava na SE 19/2026.
Além disso, o CSV local não tinha alvo "hepatite" (caía em "outros"), então o
cruzamento GAL×SINAN de hepatites nunca pareava.

Este módulo:

* descobre, por view, as colunas de data de notificação, município e agravo
  (nomes variam entre views: ``DT_NOTIFIC``, ``DataNotificacao``…);
* agrega no próprio DW (SE ISO × município × agravo), últimas ``weeks_back`` SE;
* define o agravo pelo nome da view (``VW_SINAN_HEPATITE`` → ``hepatite``) ou,
  na ``VW_SINAN_NOTIFICACAOINDIVIDUAL``, pelo CID (``A90`` → ``dengue``…);
* resolve município por nome ou por código IBGE (6 ou 7 dígitos);
* substitui em ``sinan_weekly_municipio.csv`` apenas as SE × agravo extraídas.

Os nomes de agravo seguem ``map_lacen_target_to_sinan`` (integração final).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

VIEW_TARGET: dict[str, str] = {
    "VW_SINAN_DENGUE": "dengue",
    "VW_SINAN_CHIKUNGUNYA": "chikungunya",
    "VW_SINAN_ZIKA": "zika",
    "VW_SINAN_TUBERCULOSE": "tuberculose",
    "VW_SINAN_HEPATITE": "hepatite",
    "VW_SINAN_MENINGITE": "meningite",
    "VW_SINAN_SINDROMERESPIRATORIAAGUDAGRAVE": "srag",
    "VW_SINAN_HANSENIASE": "hanseniase",
    "VW_SINAN_HANTAVIROSE": "hantavirus",
    "VW_SINAN_LEISHMANIOSEVISCERAL": "leishmaniose",
    "VW_SINAN_LEISHMANIOSETEGUMENTAR": "leishmaniose",
    "VW_SINAN_SIFILISGESTANTE": "sifilis",
    "VW_SINAN_SIFILISCONGENITA": "sifilis",
    "VW_SINAN_AIDSADULTO": "hiv",
    "VW_SINAN_AIDSCRIANCA": "hiv",
    "VW_SINAN_FEBREMACULOSA": "febre_maculosa",
    "VW_SINAN_ESQUISTOSSOMOSE": "esquistossomose",
    "VW_SINAN_LEPTOSPIROSE": "leptospirose",
    "VW_SINAN_FEBREAMARELA": "febre_amarela",
}
# Views sem relação com exame laboratorial do GAL (não entram no cruzamento).
VIEWS_IGNORADAS = {
    "VW_SINAN_ACIDENTETRABALHOEXPOSICAOMATERIALBIOLOGICO", "VW_SINAN_ACIDENTETRABALHOGRAVE",
    "VW_SINAN_DOENCARELACIONADATRABALHOLERDORT", "VW_SINAN_VIOLENCIADOMESTICASEXUALEOUOUTRAS",
    "VW_SINAN_ANIMAISPECONHENTOS", "VW_SINAN_INTOXICACAOEXOGENA",
}
VIEW_INDIVIDUAL = "VW_SINAN_NOTIFICACAOINDIVIDUAL"

# CID-10 (prefixo) → agravo, para a ficha de notificação individual.
CID_TARGET: tuple[tuple[str, str], ...] = (
    ("A90", "dengue"), ("A91", "dengue"), ("A920", "chikungunya"), ("A928", "zika"),
    ("A95", "febre_amarela"), ("A27", "leptospirose"), ("A985", "hantavirus"),
    ("B05", "sarampo"), ("B06", "rubeola"), ("A39", "meningite"), ("G00", "meningite"),
    ("G01", "meningite"), ("G02", "meningite"), ("G03", "meningite"),
    ("A15", "tuberculose"), ("A16", "tuberculose"), ("A17", "tuberculose"),
    ("A18", "tuberculose"), ("A19", "tuberculose"), ("B15", "hepatite"), ("B16", "hepatite"),
    ("B17", "hepatite"), ("B18", "hepatite"), ("B19", "hepatite"), ("A50", "sifilis"),
    ("A51", "sifilis"), ("A53", "sifilis"), ("B20", "hiv"), ("B21", "hiv"), ("B22", "hiv"),
    ("B23", "hiv"), ("B24", "hiv"), ("Z21", "hiv"), ("A30", "hanseniase"),
    ("B55", "leishmaniose"), ("A82", "raiva"), ("A00", "colera"), ("A051", "botulismo"),
    ("A20", "peste"), ("A80", "poliomielite"), ("A22", "antraz"), ("A77", "febre_maculosa"),
    ("B57", "chagas"), ("B65", "esquistossomose"), ("B50", "malaria"), ("B51", "malaria"),
    ("B52", "malaria"), ("B53", "malaria"), ("B54", "malaria"), ("U07", "covid19"),
    ("B342", "covid19"), ("J09", "influenza"), ("J10", "influenza"), ("J11", "influenza"),
    ("A37", "coqueluche"),
)

DATE_EXATAS = ("DT_NOTIFIC", "DataNotificacao", "Data_Notificacao", "DT_NOTIFICACAO",
               "DataDaNotificacao", "DtNotificacao")
AGRAVO_EXATAS = ("ID_AGRAVO", "CodigoAgravo", "Codigo_Agravo", "CID", "CID10", "Agravo",
                 "ID_CID", "CodigoCid")


def _lc(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).casefold())


def norm_municipio(x: Any) -> str:
    s = "" if x is None else str(x)
    if s.lower() in ("nan", "none", "null"):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"^\d+\s*[-\.]?\s*", "", s.upper()).replace("MUNICIPIO DE ", "")
    return re.sub(r"\s+", " ", s).strip()


def pick_columns(cols: Iterable[str]) -> dict[str, Optional[str]]:
    """Escolhe data de notificação, município (nome ou código) e agravo/CID."""
    cols = list(cols)
    low = {c: _lc(c) for c in cols}
    date_col = next((c for c in DATE_EXATAS if c in cols), None) or next(
        (c for c in cols if "notific" in low[c] and ("dt" in low[c] or "data" in low[c])), None
    ) or next((c for c in cols if "sinpri" in low[c] or "sintoma" in low[c]), None)

    def is_code(c: str) -> bool:
        lc = low[c]
        return any(k in lc for k in ("cod", "ibge", "idmn", "idmunic")) or lc.startswith("id")

    mun_cands = [c for c in cols if ("munic" in low[c] or "idmn" in low[c]) and "uf" not in low[c]]
    resid = [c for c in mun_cands if "resi" in low[c]] or mun_cands
    nome = next((c for c in resid if not is_code(c)), None)
    codigo = next((c for c in resid if is_code(c)), None)
    agravo_col = next((c for c in AGRAVO_EXATAS if c in cols), None) or next(
        (c for c in cols if "agravo" in low[c] or low[c].startswith("cid")), None
    )
    encerra = next((c for c in cols if "encerra" in low[c]), None)
    return {
        "date": date_col,
        "mun": nome or codigo,
        "mun_tipo": "nome" if nome else ("codigo" if codigo else None),
        "agravo": agravo_col,
        "encerramento": encerra,
    }


def cid_to_target(cid: Any) -> str:
    c = re.sub(r"[^A-Z0-9]", "", str(cid or "").upper())
    for pref, tgt in CID_TARGET:
        if c.startswith(pref):
            return tgt
    return "outros"


def target_from_view(view: str) -> Optional[str]:
    v = str(view).upper()
    if v in VIEWS_IGNORADAS:
        return None
    return VIEW_TARGET.get(v)


def sql_agg(schema: str, view: str, cols: dict[str, Optional[str]], days: int) -> str:
    """Agregação SE ISO × município (× agravo na ficha individual) no DW."""
    d = f"CAST([{cols['date']}] AS date)"
    yr = f"YEAR(DATEADD(day, 26 - DATEPART(iso_week, {d}), {d}))"
    wk = f"DATEPART(iso_week, {d})"
    mun = f"LTRIM(RTRIM(CAST([{cols['mun']}] AS NVARCHAR(200))))"
    agr = (f"UPPER(LTRIM(RTRIM(CAST([{cols['agravo']}] AS NVARCHAR(50)))))"
           if cols.get("agravo") else "CAST(NULL AS NVARCHAR(50))")
    enc = (f"SUM(CASE WHEN [{cols['encerramento']}] IS NOT NULL THEN 1 ELSE 0 END)"
           if cols.get("encerramento") else "0")
    return f"""
    SELECT {yr} AS epi_year, {wk} AS epi_week, {mun} AS municipio_raw, {agr} AS agravo_raw,
           COUNT_BIG(*) AS notificacoes_sinan, {enc} AS encerrados_sinan
    FROM [{schema}].[{view}]
    WHERE [{cols['date']}] IS NOT NULL
      AND {d} >= DATEADD(day, -{int(days)}, CAST(GETDATE() AS date))
      AND {d} <= CAST(GETDATE() AS date)
    GROUP BY {yr}, {wk}, {mun}, {agr}
    """


def mapa_codigo_municipio(master: Optional[pd.DataFrame]) -> dict[str, str]:
    """Código IBGE (7 e 6 dígitos) → nome normalizado do município."""
    out: dict[str, str] = {}
    if master is None or master.empty or "codigo_ibge" not in master.columns:
        return out
    for nome, cod in zip(master["municipio"], master["codigo_ibge"]):
        try:
            c7 = str(int(float(cod)))
        except (TypeError, ValueError):
            continue
        n = norm_municipio(nome)
        out[c7] = n
        out[c7[:6]] = n
    return out


def resolver_municipio(valores: pd.Series, tipo: str, cod_map: dict[str, str]) -> pd.Series:
    if tipo == "codigo":
        def _cod(v: Any) -> str:
            s = re.sub(r"\D", "", str(v or ""))
            return cod_map.get(s) or cod_map.get(s[:6]) or ""
        return valores.map(_cod)
    return valores.map(norm_municipio)


def normalizar_agg(raw: pd.DataFrame, view: str, tipo: str, cod_map: dict[str, str]) -> pd.DataFrame:
    """Resultado SQL de uma view → linhas no formato de ``sinan_weekly_municipio.csv``."""
    cols_out = ["epi_year", "epi_week", "ano", "target", "municipio",
                "notificacoes_sinan", "encerrados_sinan"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols_out)
    df = raw.copy()
    df["municipio"] = resolver_municipio(df["municipio_raw"], tipo, cod_map)
    if str(view).upper() == VIEW_INDIVIDUAL:
        df["target"] = df["agravo_raw"].map(cid_to_target)
    else:
        df["target"] = target_from_view(view)
    df = df[(df["municipio"] != "") & df["target"].notna()]
    for c in ("epi_year", "epi_week", "notificacoes_sinan", "encerrados_sinan"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["ano"] = df["epi_year"]
    return (
        df.groupby(["epi_year", "epi_week", "ano", "target", "municipio"], as_index=False)
        [["notificacoes_sinan", "encerrados_sinan"]].sum()
    )[cols_out]


def merge_sinan_weekly(old: Optional[pd.DataFrame], new: pd.DataFrame) -> pd.DataFrame:
    """Substitui no histórico as combinações (SE × agravo) presentes em ``new``."""
    if old is None or old.empty:
        return new.copy()
    if new is None or new.empty:
        return old.copy()
    keys = ["epi_year", "epi_week", "target"]
    o = old.copy()
    for c in ("epi_year", "epi_week"):
        o[c] = pd.to_numeric(o[c], errors="coerce")
    cobre = new[keys].drop_duplicates()
    m = o.merge(cobre, on=keys, how="left", indicator=True)
    keep = m[m["_merge"] == "left_only"].drop(columns="_merge")
    out = pd.concat([keep, new], ignore_index=True)
    return out.sort_values(["epi_year", "epi_week", "target", "municipio"]).reset_index(drop=True)


def status_sinan(sinan: Optional[pd.DataFrame], se_gal: Optional[tuple[int, int]],
                 *, max_atraso: int = 2) -> dict[str, Any]:
    """Última SE com notificação e defasagem frente à SE usada do GAL."""
    from etl.epi_week import atraso_semanas, format_se

    info: dict[str, Any] = {"sinan_se_max": None, "sinan_atraso_se": None, "sinan_ok": False}
    if sinan is None or sinan.empty:
        info["sinan_aviso"] = "SINAN semanal ausente."
        return info
    s = sinan.copy()
    s["epi_year"] = pd.to_numeric(s["epi_year"], errors="coerce")
    s["epi_week"] = pd.to_numeric(s["epi_week"], errors="coerce")
    n = pd.to_numeric(s.get("notificacoes_sinan", s.get("notificacoes")), errors="coerce").fillna(0)
    s = s[n > 0].dropna(subset=["epi_year", "epi_week"])
    if s.empty:
        info["sinan_aviso"] = "SINAN semanal sem notificações."
        return info
    y, w = max(zip(s["epi_year"].astype(int), s["epi_week"].astype(int)))
    info["sinan_se_max"] = format_se(y, w)
    if se_gal:
        atr = atraso_semanas(tuple(se_gal), (y, w))
        info["sinan_atraso_se"] = atr
        info["sinan_ok"] = atr <= max_atraso
        if not info["sinan_ok"]:
            info["sinan_aviso"] = (
                f"SINAN {atr} SE atrás do GAL ({format_se(y, w)} × {format_se(*se_gal)}): "
                "lacunas GAL×SINAN não são avaliáveis."
            )
    return info


def run_sinan_dw(outdir: Path | str, *, weeks_back: int = 60) -> dict[str, Any]:
    """Conecta ao DW, agrega todas as VW_SINAN_* úteis e atualiza o CSV semanal."""
    from lacen_dw import read_sql

    from etl.dw_extract import _safe_ident, connect_or_raise, discover_table_columns, list_relevant_objects

    outdir = Path(outdir)
    meta: dict[str, Any] = {"views_ok": [], "views_falha": {}, "linhas": 0}
    master_p = outdir / "municipal_master.csv"
    master = pd.read_csv(master_p) if master_p.exists() else None
    cod_map = mapa_codigo_municipio(master)
    days = max(7, int(weeks_back) * 7 + 14)

    mode, q = connect_or_raise()
    partes: list[pd.DataFrame] = []
    try:
        inv = list_relevant_objects(mode, q)
        views = [
            (str(r["TABLE_SCHEMA"]), str(r["TABLE_NAME"]).upper())
            for _, r in inv.iterrows()
            if str(r["TABLE_NAME"]).upper().startswith("VW_SINAN_")
        ]
        for schema, view in views:
            if view not in VIEW_TARGET and view != VIEW_INDIVIDUAL:
                continue
            try:
                cols = pick_columns(discover_table_columns(mode, q, _safe_ident(schema), _safe_ident(view)))
                if not cols["date"] or not cols["mun"]:
                    meta["views_falha"][view] = f"colunas não identificadas: {cols}"
                    continue
                if view == VIEW_INDIVIDUAL and not cols["agravo"]:
                    meta["views_falha"][view] = "sem coluna de agravo/CID"
                    continue
                raw = read_sql(mode, q, sql_agg(schema, view, cols, days))
                df = normalizar_agg(raw, view, cols["mun_tipo"], cod_map)
                partes.append(df)
                meta["views_ok"].append(view)
            except Exception as exc:  # noqa: BLE001 — uma view ruim não derruba as outras
                meta["views_falha"][view] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        try:
            if mode == "pyodbc":
                q.close()
            else:
                q.dispose()
        except Exception:  # noqa: BLE001
            pass

    new = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    if new.empty:
        meta["aviso"] = "Nenhuma notificação SINAN agregada do DW."
        return meta
    new = (new.groupby(["epi_year", "epi_week", "ano", "target", "municipio"], as_index=False)
           [["notificacoes_sinan", "encerrados_sinan"]].sum())
    path = outdir / "sinan_weekly_municipio.csv"
    old = pd.read_csv(path, low_memory=False) if path.exists() else None
    merged = merge_sinan_weekly(old, new)
    merged.to_csv(path, index=False, encoding="utf-8-sig")
    meta["linhas"] = int(len(new))
    from etl.epi_week import format_se

    yw = sorted(zip(new["epi_year"].astype(int), new["epi_week"].astype(int)))
    meta["se_extraidas"] = [format_se(*yw[0]), format_se(*yw[-1])]
    return meta
