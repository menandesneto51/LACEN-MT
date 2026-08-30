# Agendamento automático — ETL DW LACEN

Atualiza GAL (e views SINAN/SIM/IndicaSUS/SISREG quando existirem no DW) via VPN SES.

## Pré-requisitos

1. VPN SES-MT conectada (ou host `DW_HOST` acessível) no horário da tarefa.
2. `LACEN/.env` preenchido (`DW_*`, opcionalmente `TELEGRAM_*` / `SMTP_*`).
3. Python do venv: `LACEN\.venv\Scripts\python.exe`.

## Agendador de Tarefas (Windows)

**Diário (recomendado ~06:30):**

```text
Programa:  C:\Users\...\LACEN\rodar_etl_dw.bat
Args:      (vazio)   — falha se VPN/DW cair
Iniciar em: C:\Users\...\LACEN
```

**Semanal (domingo) com fallback local (SE pode atrasar):**

```text
Programa:  C:\Users\...\LACEN\rodar_etl_dw.bat
Args:      --allow-local-fallback --skip-cievs
```

Via `schtasks` (ajuste o caminho):

```bat
schtasks /Create /TN "LACEN_ETL_DW_diario" /SC DAILY /ST 06:30 ^
  /TR "C:\Users\Menandesneto\OneDrive\Área de Trabalho\LACEN\rodar_etl_dw.bat" ^
  /RL HIGHEST
```

Validação após cada run: `saida_pipeline\validacao_etl_dw_ultimo.txt` (`se_esperada` vs `se_usada`, `sources_extracted`).
