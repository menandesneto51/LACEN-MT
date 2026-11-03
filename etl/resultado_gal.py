# -*- coding: utf-8 -*-
"""Classificação do resultado de exames GAL — fonte única para Python e SQL.

Problemas que este módulo corrige (ver ``docs/avaliacao_pipeline_alertas.md`` §1):

* o critério anterior era ``LIKE '%positiv%'`` / ``'%reagent%'`` sobre a
  **concatenação** dos campos de resultado + observação: não reconhecia
  "Detectável"/"Detectado" (PCR, TRM, painéis respiratórios) e classificava
  como negativo um exame com "IgG: Reagente; IgM: Não reagente";
* o denominador era ``COUNT(*)``, incluindo exames sem resultado (pendentes).

Regras:

1. Cada campo (``Campo_Resultado_1..6``) é classificado isoladamente; a
   observação livre não entra (texto administrativo gera falso positivo).
2. Expressões negativas são **removidas** antes de procurar termos positivos
   ("não detectável" contém "detect"; "não reagente" contém "reagente"); se
   ainda restar termo positivo, o campo é positivo — cobre campos com vários
   alvos ("Positivo para Influenza A; negativo para B").
3. Exame = POSITIVO se algum campo é positivo; senão NEGATIVO se algum é
   negativo; senão INDETERMINADO se algum é indeterminado; senão, se liberado,
   NAO_CLASSIFICADO (valor numérico, unidade, texto livre); senão PENDENTE.
4. Positividade = positivos / (positivos + negativos) = positivos / válidos.

As listas de padrões são as mesmas no SQL (``sql_classe_exame``) e no Python
(``classificar_exame``); os testes em ``tests/test_resultado_gal.py`` garantem
a equivalência dos casos documentados. Calibrar com amostra rotulada pelo
LACEN (``diagnosticar_codigo_resultados_gal.py``) antes de reprocessar o histórico.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

POSITIVO = "positivo"
NEGATIVO = "negativo"
INDETERMINADO = "indeterminado"
NAO_CLASSIFICADO = "nao_classificado"
PENDENTE = "pendente"

RESULT_FIELDS: tuple[str, ...] = tuple(f"Campo_Resultado_{i}" for i in range(1, 7))

# Padrões sobre texto minúsculo e SEM acento (o SQL compara as duas grafias).
PADROES_NEGATIVO: tuple[str, ...] = (
    "nao detect", "indetectavel", "negativ", "nao reag", "nao reat",
    "ausencia", "ausente", "nao encontrad", "nao foram encontrad", "nao observad",
    "nao visualizad", "nao isolad", "nao houve crescimento", "sem crescimento",
)
PADROES_POSITIVO: tuple[str, ...] = (
    "positiv", "detectavel", "detectado", "detectada", "reagente", "reativo",
    "presenca de", "presente",
)
PADROES_INDETERMINADO: tuple[str, ...] = (
    "inconclusiv", "indeterminad", "equivoc", "limitrofe", "zona cinza",
    "invalid", "amostra inadequada",
)
# Campo exatamente igual a cruzes (baciloscopia: +, ++, +++).
CRUZES = ("+", "++", "+++", "(+)", "(++)", "(+++)")


def _norm(txt: object) -> str:
    s = "" if txt is None else str(txt)
    if s.lower() in ("nan", "none", "null"):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().casefold()


def classificar_campo(txt: object) -> Optional[str]:
    """Classe de um único campo de resultado (ou None se não informativo)."""
    s = _norm(txt)
    if not s:
        return None
    sem_neg = s
    for p in PADROES_NEGATIVO:
        sem_neg = sem_neg.replace(p, " ")
    if s in CRUZES or any(p in sem_neg for p in PADROES_POSITIVO):
        return POSITIVO
    if sem_neg != s:
        return NEGATIVO
    if any(p in s for p in PADROES_INDETERMINADO):
        return INDETERMINADO
    return None


def classificar_exame(campos: Iterable[object], *, liberado: bool | None = None) -> str:
    """Classe do exame a partir dos campos de resultado (regra 3)."""
    classes = [classificar_campo(c) for c in campos]
    if POSITIVO in classes:
        return POSITIVO
    if NEGATIVO in classes:
        return NEGATIVO
    if INDETERMINADO in classes:
        return INDETERMINADO
    tem_texto = any(_norm(c) for c in campos)
    if liberado or (liberado is None and tem_texto):
        return NAO_CLASSIFICADO
    return PENDENTE


def eh_liberado(status: object, data_liberacao: object = None) -> bool:
    s = _norm(status)
    if "liber" in s:
        return True
    d = _norm(data_liberacao)
    return bool(d) and d not in ("nat",)


# ---------------------------------------------------------------- SQL Server
def _variantes(padroes: Iterable[str]) -> list[str]:
    """Grafias sem e com acento (a collation do DW pode ser sensível a acento)."""
    out: list[str] = []
    for p in padroes:
        acent = (p.replace("nao ", "não ").replace("ausencia", "ausência")
                 .replace("indetectavel", "indetectável").replace("detectavel", "detectável")
                 .replace("presenca", "presença").replace("limitrofe", "limítrofe")
                 .replace("equivoc", "equívoc").replace("invalid", "inválid"))
        for v in (acent, p):  # acentuada primeiro (REPLACE mais específico antes)
            v = v.replace("'", "''")
            if v not in out:
                out.append(v)
    return out


def _like_any(expr: str, padroes: Iterable[str]) -> str:
    return "(" + " OR ".join(f"{expr} LIKE N'%{v}%'" for v in _variantes(padroes)) + ")"


def _strip_neg(expr: str) -> str:
    out = expr
    for v in _variantes(PADROES_NEGATIVO):
        out = f"REPLACE({out}, N'{v}', N' ')"
    return out


def sql_classe_campo(col: str) -> str:
    """CASE SQL → 'N' | 'P' | 'I' | NULL para um campo (mesma ordem do Python)."""
    e = f"LOWER(LTRIM(RTRIM(ISNULL(CAST([{col}] AS NVARCHAR(4000)), N''))))"
    cruzes = ", ".join(f"N'{c}'" for c in CRUZES)
    sem_neg = _strip_neg(e)
    return (
        f"CASE WHEN {e} = N'' THEN NULL "
        f"WHEN {e} IN ({cruzes}) OR {_like_any(sem_neg, PADROES_POSITIVO)} THEN 'P' "
        f"WHEN {_like_any(e, PADROES_NEGATIVO)} THEN 'N' "
        f"WHEN {_like_any(e, PADROES_INDETERMINADO)} THEN 'I' "
        f"ELSE 'X' END"
    )


def sql_classe_exame(codigos: Iterable[str], liberado_expr: str) -> str:
    """CASE SQL da classe do exame a partir dos códigos por campo (regra 3).

    ``codigos``: aliases de colunas já calculadas com ``sql_classe_campo``
    (cada uma 'P' | 'N' | 'I' | 'X' | NULL) — calcule-as uma vez numa subconsulta.
    ``liberado_expr``: condição SQL de exame liberado.
    """
    cs = ", ".join(f"[{c}]" for c in codigos)
    if not cs:
        return f"CASE WHEN {liberado_expr} THEN '{NAO_CLASSIFICADO}' ELSE '{PENDENTE}' END"
    return (
        f"CASE WHEN 'P' IN ({cs}) THEN '{POSITIVO}' "
        f"WHEN 'N' IN ({cs}) THEN '{NEGATIVO}' "
        f"WHEN 'I' IN ({cs}) THEN '{INDETERMINADO}' "
        f"WHEN ({liberado_expr}) OR 'X' IN ({cs}) THEN '{NAO_CLASSIFICADO}' "
        f"ELSE '{PENDENTE}' END"
    )
