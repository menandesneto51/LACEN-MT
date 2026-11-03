# -*- coding: utf-8 -*-
from lacen_alerta_estrategico import (
    SignalFact,
    cobertura_sinan_semana,
    qa_alerta_estrategico,
    selecionar_sinais_alerta,
)


def _fact(sid, prio, tipo="volume", **kw):
    base = dict(
        signal_id=sid, municipio="Cuiabá", municipio_key="CUIABA", codigo_ibge="",
        agravo="dengue", agravo_raw="dengue", marcador="dengue", tipo_sinal=tipo,
        atual_exames=50, atual_positivos=0, anterior_exames=20, anterior_positivos=0,
        referencia=20.0, positividade=None, severidade_estatistica="alta",
        robustez_amostral="alta", persistencia="—", prioridade_epidemiologica=prio,
        notificacoes_pareadas=None, interpretacao="", recomendacao="",
    )
    base.update(kw)
    return SignalFact(**base)


def test_critica_entra_e_vem_primeiro():
    facts = [_fact("a", "MODERADA"), _fact("b", "ALTA"), _fact("c", "CRITICA")]
    chosen, _, _ = selecionar_sinais_alerta(facts, max_n=7)
    assert [f.signal_id for f in chosen] == ["c", "b", "a"]


def test_qa_redundancia_e_linguagem_surto():
    txt = "ALERTA ESTRATÉGICO\nSemana analisada\nCompletude\nHá possível surto em Cuiabá."
    qa = qa_alerta_estrategico(txt, [_fact("x", "ALTA"), _fact("x", "ALTA")])
    assert qa.items["Redundância"].startswith("FALHA")
    assert qa.items["Linguagem anomalia ≠ surto"] == "FALHA"
    assert not qa.ok


def test_qa_lacuna_sem_sinan_bloqueia():
    txt = "ALERTA ESTRATÉGICO\nSemana analisada\nCompletude\n"
    lac = _fact("l", "ALTA", tipo="lacuna")
    qa = qa_alerta_estrategico(txt, [lac], cobertura_sinan={"sem_cobertura": True})
    assert qa.items["SINAN_COBERTURA"].startswith("FALHA")
    assert not qa.ok


def test_qa_positividade_implausivel():
    txt = (
        "ALERTA ESTRATÉGICO\nSemana analisada\nCompletude\n"
        "Positividade estadual da semana analisada: 0,6% (8/1231)."
    )
    qa = qa_alerta_estrategico(txt, [])
    assert qa.items["POSITIVIDADE_PLAUSIVEL"].startswith("ATENÇÃO")


def test_cobertura_sinan():
    wk = [
        {"epi_year": "2026", "epi_week": "19", "notificacoes": "23"},
        {"epi_year": "2026", "epi_week": "36", "notificacoes": "0"},
    ]
    c = cobertura_sinan_semana(wk, (2026, 36))
    assert c["sem_cobertura"] and c["ultima_se_com_notificacao"] == (2026, 19)
    assert not cobertura_sinan_semana(wk, (2026, 19))["sem_cobertura"]
