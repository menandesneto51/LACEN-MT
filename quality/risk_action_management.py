# -*- coding: utf-8 -*-
"""Gestão de riscos e ações — LACEN-MT V2.1.

Converte sinais do Radar LACEN em um registro persistente de riscos e ações.
Não declara surto/epidemia automaticamente e não fecha riscos sem decisão humana.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import hashlib
import json

import pandas as pd


_LEVEL = {"baixo": 1, "médio": 2, "medio": 2, "alto": 3}
_PRIORITY_ORDER = {"CRITICA": 0, "ALTA": 1, "MODERADA": 2, "BAIXA": 3}
_ALLOWED_RISK_STATES = {
    "ABERTO", "EM_ANALISE", "EM_MITIGACAO", "MONITORAMENTO",
    "CONTROLADO", "FECHADO",
}
_ALLOWED_ACTION_STATES = {
    "PLANEJADA", "EM_ANDAMENTO", "BLOQUEADA", "CONCLUIDA",
    "VALIDADA", "CANCELADA",
}

_ACTION_COLUMNS = (
    ("acao_cievs", "CIEVS-MT"),
    ("acao_ve_mun", "Vigilância Epidemiológica municipal"),
    ("acao_area_tecnica", "Área técnica"),
    ("acao_vizinhos", "Municípios vizinhos / regional"),
    ("acao_lacen", "LACEN-MT"),
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(_norm(x).casefold() for x in parts)
    return f"{prefix}-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def risk_id_for(row: pd.Series | dict[str, Any]) -> str:
    """ID estável entre semanas para o mesmo agravo × território."""
    return _stable_id(
        "RK",
        row.get("agravo"),
        row.get("familia"),
        row.get("municipio"),
    )


def action_id_for(risk_id: str, owner: str, action: str) -> str:
    return _stable_id("AC", risk_id, owner, action)


def _risk_matrix(probability: str, impact: str) -> tuple[int, str]:
    p = _LEVEL.get(_norm(probability).casefold(), 1)
    i = _LEVEL.get(_norm(impact).casefold(), 1)
    score = p * i
    if score >= 9:
        priority = "CRITICA"
    elif score >= 6:
        priority = "ALTA"
    elif score >= 3:
        priority = "MODERADA"
    else:
        priority = "BAIXA"
    return score, priority


def _due_days(priority: str) -> int:
    return {"CRITICA": 1, "ALTA": 2, "MODERADA": 7, "BAIXA": 14}.get(priority, 7)


def build_risk_register(
    radar: pd.DataFrame,
    *,
    previous: pd.DataFrame | None = None,
    now: str | None = None,
) -> pd.DataFrame:
    """Cria/atualiza registro de riscos preservando decisões humanas."""
    now = now or datetime.now().isoformat(timespec="seconds")
    cols = [
        "risk_id", "se_primeira_deteccao", "se_ultima_deteccao", "evento",
        "agravo", "familia", "municipio", "tipo_sinal", "probabilidade",
        "impacto", "score_inerente", "prioridade", "confianca", "veredito",
        "evidencias_sinal", "estado_risco", "responsavel_risco",
        "estrategia_tratamento", "decisao", "evidencia_decisao",
        "probabilidade_residual", "impacto_residual", "score_residual",
        "prioridade_residual", "justificativa_residual", "data_abertura",
        "data_atualizacao", "data_fechamento",
    ]
    if radar is None or radar.empty:
        if previous is not None and not previous.empty:
            return previous.copy().reset_index(drop=True)
        return pd.DataFrame(columns=cols)

    rows: list[dict[str, Any]] = []
    for _, src in radar.iterrows():
        rid = risk_id_for(src)
        score, priority = _risk_matrix(src.get("probabilidade"), src.get("impacto"))
        rows.append({
            "risk_id": rid,
            "se_primeira_deteccao": src.get("se"),
            "se_ultima_deteccao": src.get("se"),
            "evento": src.get("evento"),
            "agravo": src.get("agravo"),
            "familia": src.get("familia"),
            "municipio": src.get("municipio"),
            "tipo_sinal": src.get("tipo_sinal"),
            "probabilidade": src.get("probabilidade"),
            "impacto": src.get("impacto"),
            "score_inerente": score,
            "prioridade": priority,
            "confianca": src.get("confianca"),
            "veredito": src.get("veredito"),
            "evidencias_sinal": src.get("regras"),
            "estado_risco": "ABERTO",
            "responsavel_risco": "CIEVS-MT",
            "estrategia_tratamento": "INVESTIGAR" if _norm(src.get("veredito")).casefold() == "investigar" else "MONITORAR",
            "decisao": pd.NA,
            "evidencia_decisao": pd.NA,
            "probabilidade_residual": pd.NA,
            "impacto_residual": pd.NA,
            "score_residual": pd.NA,
            "prioridade_residual": pd.NA,
            "justificativa_residual": pd.NA,
            "data_abertura": now,
            "data_atualizacao": now,
            "data_fechamento": pd.NA,
        })

    out = pd.DataFrame(rows).drop_duplicates(subset=["risk_id"], keep="last")
    if previous is None or previous.empty or "risk_id" not in previous.columns:
        return out[cols].sort_values(
            "prioridade", key=lambda s: s.map(_PRIORITY_ORDER).fillna(9)
        ).reset_index(drop=True)

    prev = previous.drop_duplicates("risk_id", keep="last").set_index("risk_id")
    preserved = [
        "se_primeira_deteccao", "estado_risco", "responsavel_risco",
        "estrategia_tratamento", "decisao", "evidencia_decisao",
        "probabilidade_residual", "impacto_residual", "score_residual",
        "prioridade_residual", "justificativa_residual", "data_abertura",
        "data_fechamento",
    ]
    for idx, rid in out["risk_id"].items():
        if rid not in prev.index:
            continue
        for col in preserved:
            if col not in prev.columns:
                continue
            value = prev.at[rid, col]
            if pd.notna(value) and str(value).strip() != "":
                out.at[idx, col] = value
        out.at[idx, "data_atualizacao"] = now
        # Risco previamente fechado reapareceu: reabre para análise.
        if str(out.at[idx, "estado_risco"]) in {"CONTROLADO", "FECHADO"}:
            out.at[idx, "estado_risco"] = "EM_ANALISE"
            out.at[idx, "data_fechamento"] = pd.NA

    return out[cols].sort_values(
        "prioridade", key=lambda s: s.map(_PRIORITY_ORDER).fillna(9)
    ).reset_index(drop=True)


def build_action_register(
    radar: pd.DataFrame,
    risks: pd.DataFrame,
    *,
    previous: pd.DataFrame | None = None,
    now: str | None = None,
) -> pd.DataFrame:
    """Materializa ações do Radar em plano persistente com prazos."""
    now = now or datetime.now().isoformat(timespec="seconds")
    now_dt = datetime.fromisoformat(now)
    risk_priority = (
        risks.set_index("risk_id")["prioridade"].to_dict()
        if risks is not None and not risks.empty else {}
    )
    rows: list[dict[str, Any]] = []
    if radar is not None and not radar.empty:
        for _, src in radar.iterrows():
            rid = risk_id_for(src)
            priority = risk_priority.get(rid, _risk_matrix(
                src.get("probabilidade"), src.get("impacto")
            )[1])
            for col, owner in _ACTION_COLUMNS:
                action = _norm(src.get(col))
                if not action:
                    continue
                aid = action_id_for(rid, owner, action)
                due = now_dt + timedelta(days=_due_days(priority))
                rows.append({
                    "action_id": aid,
                    "risk_id": rid,
                    "prioridade_risco": priority,
                    "acao": action,
                    "responsavel": owner,
                    "estado_acao": "PLANEJADA",
                    "prazo": due.isoformat(timespec="seconds"),
                    "dependencia": pd.NA,
                    "bloqueio": pd.NA,
                    "evidencia_execucao": pd.NA,
                    "resultado": pd.NA,
                    "validacao": pd.NA,
                    "criada_em": now,
                    "atualizada_em": now,
                    "concluida_em": pd.NA,
                    "validada_em": pd.NA,
                })

    cols = [
        "action_id", "risk_id", "prioridade_risco", "acao", "responsavel",
        "estado_acao", "prazo", "dependencia", "bloqueio",
        "evidencia_execucao", "resultado", "validacao", "criada_em",
        "atualizada_em", "concluida_em", "validada_em",
    ]
    out = pd.DataFrame(rows, columns=cols)
    if out.empty:
        if previous is not None and not previous.empty:
            return previous.copy().reset_index(drop=True)
        return out
    out = out.drop_duplicates("action_id", keep="last")

    if previous is not None and not previous.empty and "action_id" in previous.columns:
        prev = previous.drop_duplicates("action_id", keep="last").set_index("action_id")
        preserved = [
            "estado_acao", "prazo", "dependencia", "bloqueio",
            "evidencia_execucao", "resultado", "validacao", "criada_em",
            "concluida_em", "validada_em",
        ]
        for idx, aid in out["action_id"].items():
            if aid not in prev.index:
                continue
            for col in preserved:
                if col not in prev.columns:
                    continue
                value = prev.at[aid, col]
                if pd.notna(value) and str(value).strip() != "":
                    out.at[idx, col] = value
            out.at[idx, "atualizada_em"] = now

    return out[cols].reset_index(drop=True)


def update_action(
    actions: pd.DataFrame,
    action_id: str,
    *,
    estado: str,
    responsavel: str | None = None,
    prazo: str | None = None,
    dependencia: str | None = None,
    bloqueio: str | None = None,
    evidencia_execucao: str | None = None,
    resultado: str | None = None,
    validacao: str | None = None,
    now: str | None = None,
) -> pd.DataFrame:
    if estado not in _ALLOWED_ACTION_STATES:
        raise ValueError(f"Estado de ação inválido: {estado}")
    out = actions.copy()
    mask = out["action_id"].astype(str) == str(action_id)
    if not mask.any():
        raise KeyError(f"action_id não encontrado: {action_id}")
    now = now or datetime.now().isoformat(timespec="seconds")
    out.loc[mask, "estado_acao"] = estado
    out.loc[mask, "atualizada_em"] = now
    updates = {
        "responsavel": responsavel, "prazo": prazo, "dependencia": dependencia,
        "bloqueio": bloqueio, "evidencia_execucao": evidencia_execucao,
        "resultado": resultado, "validacao": validacao,
    }
    for col, value in updates.items():
        if value is not None:
            out.loc[mask, col] = value

    if estado in {"CONCLUIDA", "VALIDADA"}:
        evidence = evidencia_execucao if evidencia_execucao is not None else out.loc[mask, "evidencia_execucao"].iloc[0]
        result = resultado if resultado is not None else out.loc[mask, "resultado"].iloc[0]
        if pd.isna(evidence) or not str(evidence).strip() or pd.isna(result) or not str(result).strip():
            raise ValueError("CONCLUIDA/VALIDADA exige evidência de execução e resultado.")
        out.loc[mask, "concluida_em"] = out.loc[mask, "concluida_em"].fillna(now)
    if estado == "VALIDADA":
        val = validacao if validacao is not None else out.loc[mask, "validacao"].iloc[0]
        if pd.isna(val) or not str(val).strip():
            raise ValueError("VALIDADA exige validação explícita.")
        out.loc[mask, "validada_em"] = now
    return out


def update_risk(
    risks: pd.DataFrame,
    risk_id: str,
    *,
    estado: str,
    actions: pd.DataFrame | None = None,
    responsavel: str | None = None,
    estrategia: str | None = None,
    decisao: str | None = None,
    evidencia_decisao: str | None = None,
    probabilidade_residual: str | None = None,
    impacto_residual: str | None = None,
    justificativa_residual: str | None = None,
    now: str | None = None,
) -> pd.DataFrame:
    if estado not in _ALLOWED_RISK_STATES:
        raise ValueError(f"Estado de risco inválido: {estado}")
    out = risks.copy()
    mask = out["risk_id"].astype(str) == str(risk_id)
    if not mask.any():
        raise KeyError(f"risk_id não encontrado: {risk_id}")
    now = now or datetime.now().isoformat(timespec="seconds")
    out.loc[mask, "estado_risco"] = estado
    out.loc[mask, "data_atualizacao"] = now

    updates = {
        "responsavel_risco": responsavel, "estrategia_tratamento": estrategia,
        "decisao": decisao, "evidencia_decisao": evidencia_decisao,
        "probabilidade_residual": probabilidade_residual,
        "impacto_residual": impacto_residual,
        "justificativa_residual": justificativa_residual,
    }
    for col, value in updates.items():
        if value is not None:
            out.loc[mask, col] = value

    if probabilidade_residual is not None or impacto_residual is not None:
        p = probabilidade_residual or out.loc[mask, "probabilidade_residual"].iloc[0]
        i = impacto_residual or out.loc[mask, "impacto_residual"].iloc[0]
        if pd.notna(p) and pd.notna(i) and str(p).strip() and str(i).strip():
            score, priority = _risk_matrix(str(p), str(i))
            out.loc[mask, "score_residual"] = score
            out.loc[mask, "prioridade_residual"] = priority

    if estado in {"CONTROLADO", "FECHADO"}:
        row = out.loc[mask].iloc[0]
        required = {
            "decisao": row.get("decisao"),
            "evidencia_decisao": row.get("evidencia_decisao"),
            "probabilidade_residual": row.get("probabilidade_residual"),
            "impacto_residual": row.get("impacto_residual"),
            "justificativa_residual": row.get("justificativa_residual"),
        }
        missing = [k for k, v in required.items() if pd.isna(v) or not str(v).strip()]
        if missing:
            raise ValueError(
                f"{estado} exige decisão, evidência e risco residual. Ausentes: "
                + ", ".join(missing)
            )
    if estado == "FECHADO" and actions is not None and not actions.empty:
        related = actions[actions["risk_id"].astype(str) == str(risk_id)]
        unresolved = related[~related["estado_acao"].isin(["VALIDADA", "CANCELADA"])]
        if not unresolved.empty:
            raise ValueError("FECHADO exige todas as ações VALIDADA ou CANCELADA.")
        out.loc[mask, "data_fechamento"] = now
    return out


def summarize_risk_management(
    risks: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    now_dt = datetime.fromisoformat(now) if now else datetime.now()
    if risks is None:
        risks = pd.DataFrame()
    if actions is None:
        actions = pd.DataFrame()

    if risks.empty:
        open_risks = risks
        critical_open = high_open = 0
    else:
        open_risks = risks[risks["estado_risco"] != "FECHADO"]
        critical_open = int((open_risks["prioridade"] == "CRITICA").sum())
        high_open = int((open_risks["prioridade"] == "ALTA").sum())

    overdue = 0
    blocked = 0
    open_actions = 0
    if not actions.empty:
        state = actions["estado_acao"].astype(str)
        open_mask = ~state.isin(["VALIDADA", "CANCELADA"])
        open_actions = int(open_mask.sum())
        blocked = int((state == "BLOQUEADA").sum())
        due = pd.to_datetime(actions["prazo"], errors="coerce")
        overdue = int((open_mask & due.notna() & (due < pd.Timestamp(now_dt))).sum())

    if critical_open > 0 or overdue > 0 and critical_open + high_open > 0:
        status = "BLOCK"
    elif high_open > 0 or blocked > 0 or open_actions > 0:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "status": status,
        "open_risks": int(len(open_risks)),
        "critical_open": critical_open,
        "high_open": high_open,
        "open_actions": open_actions,
        "blocked_actions": blocked,
        "overdue_actions": overdue,
        "promotion_ready": status == "PASS",
        "automatic_closure_allowed": False,
    }


def write_risk_management(
    risks: pd.DataFrame,
    actions: pd.DataFrame,
    outdir: Path | str,
    *,
    now: str | None = None,
) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    risk_csv = out / "risk_register_v2_1.csv"
    action_csv = out / "action_register_v2_1.csv"

    # O merge de estado humano deve ocorrer em build_risk_register/build_action_register.
    # Aqui apenas persistimos o snapshot já resolvido para não ressuscitar estado antigo.
    current_risks = risks.copy()
    current_actions = actions.copy()

    current_risks.to_csv(risk_csv, index=False, encoding="utf-8-sig")
    current_actions.to_csv(action_csv, index=False, encoding="utf-8-sig")
    try:
        current_risks.to_parquet(out / "risk_register_v2_1.parquet", index=False)
        current_actions.to_parquet(out / "action_register_v2_1.parquet", index=False)
    except Exception:
        pass

    summary = summarize_risk_management(current_risks, current_actions, now=now)
    json_path = out / "risk_action_summary_v2_1.json"
    txt_path = out / "risk_action_summary_v2_1.txt"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(
        "\n".join([
            "LACEN-MT V2.1 — GESTÃO DE RISCOS E AÇÕES",
            f"status: {summary['status']}",
            f"riscos_abertos: {summary['open_risks']}",
            f"criticos_abertos: {summary['critical_open']}",
            f"altos_abertos: {summary['high_open']}",
            f"acoes_abertas: {summary['open_actions']}",
            f"acoes_bloqueadas: {summary['blocked_actions']}",
            f"acoes_atrasadas: {summary['overdue_actions']}",
            f"promotion_ready: {str(summary['promotion_ready']).lower()}",
            "automatic_closure_allowed: false",
        ]) + "\n",
        encoding="utf-8",
    )
    return {
        "risk_csv": risk_csv, "action_csv": action_csv,
        "summary_json": json_path, "summary_txt": txt_path,
    }


def build_risk_register_from_existing(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    *,
    now: str | None = None,
) -> pd.DataFrame:
    """Preserva campos humanos em um registro já normalizado."""
    if current is None or current.empty or previous is None or previous.empty:
        return current.copy() if isinstance(current, pd.DataFrame) else pd.DataFrame()
    out = current.copy()
    prev = previous.drop_duplicates("risk_id", keep="last").set_index("risk_id")
    preserve = [
        "se_primeira_deteccao", "estado_risco", "responsavel_risco",
        "estrategia_tratamento", "decisao", "evidencia_decisao",
        "probabilidade_residual", "impacto_residual", "score_residual",
        "prioridade_residual", "justificativa_residual", "data_abertura",
        "data_fechamento",
    ]
    for idx, rid in out["risk_id"].items():
        if rid not in prev.index:
            continue
        for col in preserve:
            if col in prev.columns:
                value = prev.at[rid, col]
                if pd.notna(value) and str(value).strip():
                    out.at[idx, col] = value
        if now:
            out.at[idx, "data_atualizacao"] = now
    return out


def build_action_register_from_existing(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    *,
    now: str | None = None,
) -> pd.DataFrame:
    if current is None or current.empty or previous is None or previous.empty:
        return current.copy() if isinstance(current, pd.DataFrame) else pd.DataFrame()
    out = current.copy()
    prev = previous.drop_duplicates("action_id", keep="last").set_index("action_id")
    preserve = [
        "estado_acao", "prazo", "dependencia", "bloqueio",
        "evidencia_execucao", "resultado", "validacao", "criada_em",
        "concluida_em", "validada_em",
    ]
    for idx, aid in out["action_id"].items():
        if aid not in prev.index:
            continue
        for col in preserve:
            if col in prev.columns:
                value = prev.at[aid, col]
                if pd.notna(value) and str(value).strip():
                    out.at[idx, col] = value
        if now:
            out.at[idx, "atualizada_em"] = now
    return out


def run_risk_action_management(
    outdir: Path | str,
    *,
    radar_filename: str = "radar_eventos_risco.csv",
    now: str | None = None,
) -> dict[str, Any]:
    """Executa a camada sobre o Radar persistido, sem inventar sinais novos."""
    out = Path(outdir)
    radar_path = out / radar_filename
    if not radar_path.exists():
        return {
            "status": "WARN",
            "reason": f"{radar_filename} ausente",
            "promotion_ready": False,
        }
    radar = pd.read_csv(radar_path, low_memory=False)
    risk_path = out / "quality" / "risk_register_v2_1.csv"
    action_path = out / "quality" / "action_register_v2_1.csv"
    prev_risks = pd.read_csv(risk_path, low_memory=False) if risk_path.exists() else pd.DataFrame()
    prev_actions = pd.read_csv(action_path, low_memory=False) if action_path.exists() else pd.DataFrame()

    risks = build_risk_register(radar, previous=prev_risks, now=now)
    actions = build_action_register(radar, risks, previous=prev_actions, now=now)
    write_risk_management(risks, actions, out / "quality", now=now)
    return summarize_risk_management(risks, actions, now=now)
