import pandas as pd

from quality.territorial_dimension import normalize_population_source


def test_normalize_population_accepts_staging_dw_aliases():
    total = pd.DataFrame(
        {
            "Ano": [2021],
            "CodigoMunicipio": [510340],
            "Municipio": ["CUIABA"],
            "PopulacaoResidente": [618124],
        }
    )
    tcu = pd.DataFrame(
        {
            "CODIGO": [510340],
            "MUNICÍPIO": ["CUIABA"],
            "População_estimada": [618124],
        }
    )
    n1 = normalize_population_source(total, source_name="DW:POPULACAO_TOTAL")
    n2 = normalize_population_source(tcu, source_name="DW:POPULACAO_TCU")
    assert float(n1.loc[0, "populacao"]) == 618124
    assert float(n2.loc[0, "populacao"]) == 618124
    assert str(n1.loc[0, "municipio"]).upper() == "CUIABA"
    assert str(n2.loc[0, "municipio"]).upper() == "CUIABA"
    # Codigo de 6 digitos nao vira IBGE inventado
    assert pd.isna(n1.loc[0, "municipio_ibge"])
