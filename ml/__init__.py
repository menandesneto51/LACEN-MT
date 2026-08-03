# -*- coding: utf-8 -*-
"""Módulo de sinais preditivos LACEN MT.

Arquitetura: treino/inferência em Python; resultados gravados em saida_pipeline
(e futuramente no DW). O dashboard apenas consome os CSVs finais.
"""

__all__ = ["run_ml_pipeline"]


def run_ml_pipeline(*args, **kwargs):
    from .run_ml_pipeline import run_ml_pipeline as _run
    return _run(*args, **kwargs)
