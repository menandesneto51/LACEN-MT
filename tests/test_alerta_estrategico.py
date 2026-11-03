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


def test_positivo_isolado_imediato_vira_candidato():
    from lacen_alerta_estrategico import _candidatos_imediatos

    wk = [
        {"epi_year": "2026", "epi_week": "36", "municipio": "CUIABA",
         "target": "raiva_raiva", "tests": "1", "positives": "1"},
        {"epi_year": "2026", "epi_week": "36", "municipio": "CUIABA",
         "target": "dengue", "tests": "40", "positives": "1"},  # não imediata
        {"epi_year": "2026", "epi_week": "36", "municipio": "SINOP",
         "target": "sarampo_sarampo_igm", "tests": "3", "positives": "0"},  # sem positivo
    ]
    out = _candidatos_imediatos(wk, (2026, 36), (2026, 35), set())
    assert [f.agravo_raw for f in out] == ["raiva_raiva"]
    f = out[0]
    assert f.prioridade_epidemiologica == "CRITICA" and f.prazo == "24h"


def _val_ok():
    import lacen_validacao_sinais as vs

    return vs.Validacao(status=vs.VALIDADO, classe_alvo="cronica",
                        atendidos=["ok"], corroboracoes=["persistência (SE anterior)"])


def test_destaque_juina_so_com_validados():
    from lacen_alerta_estrategico import destaque_juina

    assert destaque_juina(None, []) is None
    # sinal validado de dengue em Juína não habilita bloco de HBV
    d = _fact("d", "ALTA", municipio="Juína", municipio_key="JUINA", agravo_raw="dengue")
    d.validacao = _val_ok()
    assert destaque_juina(None, [d]) is None
    h = _fact("h", "ALTA", municipio="Juína", municipio_key="JUINA",
              agravo_raw="hepatite_b_hbv", agravo="hepatite b",
              atual_exames=49, anterior_exames=57, referencia=17.6)
    h.validacao = _val_ok()
    txt = "\n".join(destaque_juina(None, [h]))
    assert "Hepatite B" in txt and "diferença: -8" in txt
    assert "Hepatite C" not in txt and "Lacuna" not in txt
    assert "Aumento importante" not in txt
