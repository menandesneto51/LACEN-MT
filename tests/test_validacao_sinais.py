# -*- coding: utf-8 -*-
from etl.epi_week import shift_se
from lacen_alerta_estrategico import SignalFact
import lacen_validacao_sinais as vs

SE = (2026, 36)


def _fact(target="dengue", mun="CUIABA", tipo="volume", ex=40, pos=0, p=1e-5, exc=25.0):
    return SignalFact(
        signal_id=f"{mun}|{target}|{tipo}", municipio=mun.title(), municipio_key=mun,
        codigo_ibge="", agravo=target, agravo_raw=target, marcador=target, tipo_sinal=tipo,
        atual_exames=ex, atual_positivos=pos, anterior_exames=10, anterior_positivos=0,
        referencia=15.0, positividade=None, severidade_estatistica="alta",
        robustez_amostral="alta", persistencia="—", prioridade_epidemiologica="ALTA",
        notificacoes_pareadas=None, interpretacao="", recomendacao="",
        p_valor=p, excesso=exc,
    )


def _weekly(tot_se=1200, base=1200, pos_frac=0.10):
    rows = []
    for i in range(0, 9):
        y, w = shift_se(SE[0], SE[1], -i)
        t = tot_se if i == 0 else base
        rows.append({"epi_year": y, "epi_week": w, "tests": t, "positives": t * pos_frac})
    return rows


def _ctx(anom=(), viz=(), **kw):
    return vs.montar_contexto(se=SE, weekly=_weekly(**kw), anomalias=anom, vizinhos=viz)


def _anom(mun, target, se, metric="tests"):
    return {"municipio": mun, "target": target, "metric": metric,
            "epi_year": se[0], "epi_week": se[1], "tipo_anomalia": "alta_atipica"}


def test_classes():
    assert vs.classe_alvo("dengue") == "aguda"
    assert vs.classe_alvo("raiva_raiva") == "imediata"
    assert vs.classe_alvo("zika_zika_igg") == "nao_agudo"
    assert vs.classe_alvo("papilomavirus_humano_hpv_papiloma_v_rus_biologia_molecular") == "assistencial"
    assert vs.classe_alvo("hepatite_b_hbv") == "cronica"
    assert vs.classe_alvo("algo_novo") == "indefinida"


def test_sem_corroboracao_fica_em_observacao():
    v = vs.avaliar_sinal(_fact(), _ctx())
    assert v.status == vs.EM_OBSERVACAO and "corroboração" in v.motivos[0]


def test_persistencia_valida():
    ctx = _ctx(anom=[_anom("CUIABA", "dengue", shift_se(*SE, -1))])
    v = vs.avaliar_sinal(_fact(), ctx)
    assert v.publicar and "persistência" in v.corroboracoes[0]


def test_vizinho_valida():
    ctx = _ctx(anom=[_anom("VARZEA GRANDE", "dengue", SE)],
               viz=[{"municipio": "CUIABA", "vizinho": "VARZEA GRANDE", "rank_vizinho": 1}])
    assert vs.avaliar_sinal(_fact(), ctx).publicar


def test_nao_significativo_e_excesso_pequeno():
    ctx = _ctx(anom=[_anom("CUIABA", "dengue", shift_se(*SE, -1))])
    assert vs.avaliar_sinal(_fact(p=0.2), ctx).status == vs.EM_OBSERVACAO
    assert vs.avaliar_sinal(_fact(exc=2.0), ctx).status == vs.EM_OBSERVACAO


def test_rastreio_e_igg_descartados():
    ctx = _ctx()
    assert vs.avaliar_sinal(_fact(target="papilomavirus_humano_hpv"), ctx).status == vs.DESCARTADO
    assert vs.avaliar_sinal(_fact(target="chikungunya_igg"), ctx).status == vs.DESCARTADO


def test_carga_suspeita_descarta():
    v = vs.avaliar_sinal(_fact(), _ctx(tot_se=200))
    assert v.status == vs.DESCARTADO and "carga suspeita" in v.motivos[0]


def test_imediata_com_positivo_valida_sem_estatistica():
    v = vs.avaliar_sinal(_fact(target="raiva_raiva", ex=1, pos=1, p=None, exc=0.0), _ctx())
    assert v.publicar


def test_positividade_implausivel_bloqueia_criterio():
    ctx = _ctx(pos_frac=0.005)
    assert not ctx.positividade_valida
    v = vs.avaliar_sinal(_fact(tipo="positividade", pos=5), ctx)
    assert v.status == vs.EM_OBSERVACAO
    # imediata com positivo também não valida se a positividade não é confiável
    v2 = vs.avaliar_sinal(_fact(target="raiva_raiva", ex=1, pos=1, p=None, exc=0.0), ctx)
    assert not v2.publicar


def test_cronica_exige_persistencia():
    ctx = _ctx(viz=[{"municipio": "JUINA", "vizinho": "CASTANHEIRA", "rank_vizinho": 1}],
               anom=[_anom("CASTANHEIRA", "hepatite_b_hbv", SE)])
    v = vs.avaliar_sinal(_fact(target="hepatite_b_hbv", mun="JUINA"), ctx)
    assert v.status == vs.EM_OBSERVACAO and "persistência" in v.motivos[0]
