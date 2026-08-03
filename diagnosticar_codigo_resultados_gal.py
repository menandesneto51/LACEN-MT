from pathlib import Path
import re
import pandas as pd

ROOT = Path.cwd()
OUT = ROOT / "diagnostico_codigo_resultados_gal"
OUT.mkdir(exist_ok=True)

padroes = [
    "Campo_Resultado_1",
    "Campo_Resultado_2",
    "Campo_Resultado_3",
    "Campo_Resultado_4",
    "Campo_Resultado_5",
    "Campo_Resultado_6",
    "RESULT_COLS",
    "positividade",
    "positivo",
    "detect",
    "reagente",
    "não detect",
    "nao detect",
    "negativo",
    "inconclusivo",
    "normaliz",
    "melt",
    "wide_to_long",
    "classe_resultado",
    "resultado",
]

arquivos = sorted(ROOT.glob("*.py"))
achados = []

for arq in arquivos:
    try:
        linhas = arq.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        try:
            linhas = arq.read_text(encoding="latin1", errors="ignore").splitlines()
        except Exception:
            continue

    texto = "\n".join(linhas).lower()
    score = 0
    hits = []

    for p in padroes:
        if p.lower() in texto:
            score += 1
            hits.append(p)

    if score == 0:
        continue

    for i, linha in enumerate(linhas, start=1):
        linha_low = linha.lower()
        if any(p.lower() in linha_low for p in padroes):
            ini = max(1, i - 4)
            fim = min(len(linhas), i + 6)
            contexto = "\n".join(
                f"{j:04d}: {linhas[j-1]}"
                for j in range(ini, fim + 1)
            )

            achados.append({
                "arquivo": arq.name,
                "linha": i,
                "score_arquivo": score,
                "padroes_arquivo": ", ".join(hits),
                "linha_texto": linha.strip(),
                "contexto": contexto
            })

df = pd.DataFrame(achados)

if df.empty:
    print("Nenhum trecho encontrado.")
else:
    df = df.sort_values(["score_arquivo", "arquivo", "linha"], ascending=[False, True, True])
    csv = OUT / "achados_codigo_resultados_gal.csv"
    txt = OUT / "achados_codigo_resultados_gal.txt"

    df.to_csv(csv, index=False, encoding="utf-8-sig")

    with txt.open("w", encoding="utf-8") as f:
        for arq, bloco in df.groupby("arquivo"):
            f.write("\n" + "="*100 + "\n")
            f.write(f"ARQUIVO: {arq}\n")
            f.write("="*100 + "\n")
            for _, r in bloco.iterrows():
                f.write(f"\n--- Linha {r['linha']} | score {r['score_arquivo']} ---\n")
                f.write(r["contexto"])
                f.write("\n")

    ranking = (
        df.groupby("arquivo", as_index=False)
          .agg(
              score=("score_arquivo", "max"),
              ocorrencias=("linha", "count"),
              padroes=("padroes_arquivo", "first")
          )
          .sort_values(["score", "ocorrencias"], ascending=False)
    )

    ranking_csv = OUT / "ranking_scripts_lacen_para_reaproveitar.csv"
    ranking.to_csv(ranking_csv, index=False, encoding="utf-8-sig")

    print("\nRANKING DE SCRIPTS MAIS ÚTEIS:")
    print(ranking.to_string(index=False))

    print("\nArquivos gerados:")
    print(csv)
    print(txt)
    print(ranking_csv)
