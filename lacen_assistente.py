# -*- coding: utf-8 -*-
"""Assistente de sala de situação com freios: só responde a partir de tabelas agregadas."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent


def _load(outdir: Path, name: str, n: int = 30) -> pd.DataFrame:
    p = outdir / name
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, low_memory=False).head(n)


def responder_sala_situacao(pergunta: str, outdir: Path | str = "saida_pipeline") -> dict:
    """
    Responde perguntas operacionais citando linhas dos CSVs.
    Sem inventar números. LLM externo só se LACEN_LLM_API_KEY estiver definida
    e ainda assim recebe apenas o contexto tabular já filtrado.
    """
    outdir = Path(outdir)
    q = (pergunta or "").casefold()
    citations: list[str] = []
    bullets: list[str] = []

    fila = _load(outdir, "fila_operacional.csv", 20)
    risco = _load(outdir, "municipios_em_risco.csv", 15)
    sil = _load(outdir, "municipios_silenciosos.csv", 15)
    mlr = _load(outdir, "ml_risco_predito.csv", 15)
    mls = _load(outdir, "ml_silencio_predito.csv", 15)
    bt = _load(outdir, "ml_backtest_summary.csv", 20)
    hist = _load(outdir, "alerta_historico.csv", 50)

    if any(x in q for x in ("prioriz", "top", "cinco", "5 município", "o que fazer")):
        src = fila if not fila.empty else risco
        if src.empty:
            return {
                "resposta": "Não há fila operacional nem municípios em risco disponíveis em saida_pipeline.",
                "citacoes": [],
                "fonte": "local_rules",
            }
        cols = [c for c in ("municipio", "sinal", "motivo", "prioridade", "acao_sugerida", "prazo_acao", "responsavel", "alerta_hibrido", "prob_ml") if c in src.columns]
        top = src.head(5)
        for _, r in top.iterrows():
            mun = r.get("municipio", "")
            acao = r.get("acao_sugerida", r.get("motivo", ""))
            prazo = r.get("prazo_acao", "")
            bullets.append(f"**{mun}** — {acao}" + (f" (prazo: {prazo})" if prazo else ""))
            citations.append(str({c: r.get(c) for c in cols}))
        texto = "Prioridades da sala de situação (com base na fila/risco atual):\n\n" + "\n".join(f"- {b}" for b in bullets)
        return {"resposta": texto, "citacoes": citations, "fonte": "fila_operacional/municipios_em_risco"}

    if "silêncio" in q or "silencio" in q or "vizinho" in q:
        if sil.empty:
            return {"resposta": "Arquivo municipios_silenciosos.csv indisponível.", "citacoes": [], "fonte": "local_rules"}
        if "silencio_com_vizinho_alerta" in sil.columns:
            sub = sil[sil["silencio_com_vizinho_alerta"].fillna(False)].head(8)
        else:
            sub = sil.head(8)
        for _, r in sub.iterrows():
            bullets.append(
                f"**{r.get('municipio')}** — {r.get('classificacao_silencio', r.get('tipo_sinal', 'silencio'))}"
                + (f" | vizinhos_alerta={r.get('vizinhos_em_alerta')}" if "vizinhos_em_alerta" in sil.columns else "")
            )
            citations.append(str(r.to_dict()))
        texto = "Municípios com sinal de silêncio (citando CSV):\n\n" + "\n".join(f"- {b}" for b in bullets)
        return {"resposta": texto, "citacoes": citations, "fonte": "municipios_silenciosos"}

    if any(x in q for x in ("backtest", "acurácia", "auc", "confirma")):
        if bt.empty:
            return {"resposta": "ml_backtest_summary.csv indisponível. Rode o pipeline ML.", "citacoes": [], "fonte": "local_rules"}
        glob = bt[bt.get("escopo", pd.Series(dtype=str)).astype(str).eq("global")] if "escopo" in bt.columns else bt
        for _, r in glob.head(8).iterrows():
            bullets.append(
                f"{r.get('modelo')} thr={r.get('threshold')}: AUC={r.get('auc')} "
                f"confirmação={r.get('confirmacao')} P@20={r.get('precision_at_20')}"
            )
            citations.append(str(r.to_dict()))
        texto = "Desempenho do modelo (backtest temporal):\n\n" + "\n".join(f"- {b}" for b in bullets)
        return {"resposta": texto, "citacoes": citations, "fonte": "ml_backtest_summary"}

    if "predit" in q or "ml" in q or "probabilidade" in q:
        if mlr.empty and mls.empty:
            return {"resposta": "Arquivos ML preditos indisponíveis.", "citacoes": [], "fonte": "local_rules"}
        if not mlr.empty:
            for _, r in mlr.head(5).iterrows():
                bullets.append(
                    f"Risco **{r.get('municipio')}**/{r.get('target')}: prob={r.get('prob_alerta_proxima_janela')} "
                    f"| drivers: {r.get('drivers', '')[:120]}"
                )
                citations.append(str(r.to_dict()))
        texto = "Sinais preditivos (somente valores do CSV):\n\n" + "\n".join(f"- {b}" for b in bullets)
        return {"resposta": texto, "citacoes": citations, "fonte": "ml_risco_predito"}

    if "desfecho" in q or "histórico" in q or "historico" in q:
        hist_full = _load(outdir, "alerta_historico.csv", 5000)
        if hist_full.empty:
            return {"resposta": "alerta_historico.csv ainda não gerado.", "citacoes": [], "fonte": "local_rules"}
        conf_flag = hist_full["confirmado"].astype(str).str.replace(r"\.0$", "", regex=True)
        conf = hist_full[conf_flag.isin(["0", "1"])].copy()
        conf["confirmado"] = conf_flag[conf_flag.isin(["0", "1"])].values
        if conf.empty:
            texto = f"Há {len(hist_full)} alertas emitidos; desfechos ainda não avaliados (aguardar SE seguintes)."
        else:
            taxa = (conf["confirmado"].astype(str) == "1").mean()
            por_tipo = conf.groupby(conf["tipo"].astype(str))["confirmado"].apply(
                lambda s: f"n={len(s)} conf={(s.astype(str)=='1').mean():.0%}"
            ).to_dict()
            texto = (
                f"Alertas com desfecho: {len(conf)}/{len(hist_full)} | "
                f"taxa de confirmação={taxa:.1%} | por tipo={por_tipo} "
                "(fonte: alerta_historico.csv)."
            )
        citations.append(f"n_hist={len(hist_full)}; n_fechados={len(conf)}")
        return {"resposta": texto, "citacoes": citations, "fonte": "alerta_historico"}

    # Default: resumo executivo
    n_fila = len(fila)
    n_risco = len(risco)
    n_sil = len(sil)
    texto = (
        f"Resumo disponível nos agregados: fila={n_fila}, risco={n_risco}, silêncio={n_sil}. "
        "Pergunte por: prioridades, silêncio com vizinhos, backtest/AUC, predição ou desfecho."
    )
    return {"resposta": texto, "citacoes": citations, "fonte": "local_rules"}


def talvez_enriquecer_com_llm(resposta: dict, pergunta: str) -> dict:
    """Opcional: reescreve o texto com LLM, sem alterar números (contexto = resposta já citada)."""
    key = os.getenv("LACEN_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return resposta
    try:
        # Freio: só envia a resposta já calcada + pergunta; não envia microdados
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "model": os.getenv("LACEN_LLM_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": (
                    "Você é assistente CIEVS/LACEN. Reescreva de forma clara para gestores. "
                    "NÃO invente números. Use apenas o texto fornecido. Cite a fonte."
                )},
                {"role": "user", "content": f"Pergunta: {pergunta}\n\nBase factual:\n{resposta['resposta']}\n\nCitações:\n{resposta.get('citacoes', [])}"},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        resposta = dict(resposta)
        resposta["resposta"] = text
        resposta["fonte"] = resposta.get("fonte", "") + "+llm_rewrite"
    except Exception as exc:
        resposta = dict(resposta)
        resposta["llm_erro"] = str(exc)
    return resposta
