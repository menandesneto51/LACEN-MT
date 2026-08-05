# Runbook — deploy do painel LACEN MT em servidor SES

Uso institucional (Windows ou Linux). **Não** copie microdados GAL brutos para o servidor; só agregados em `saida_pipeline`.

## Checklist rápido

1. [ ] Clone/pull: `git clone https://github.com/menandesneto51/LACEN-MT.git` (ou `git pull` em `main`)
2. [ ] Python 3.10+ e venv
3. [ ] `pip install -r requirements.txt`
4. [ ] Pasta `saida_pipeline` com CSV/Parquet essenciais (já versionados no repo para o Cloud; atualize via pipeline/ML quando houver rede)
5. [ ] Secrets locais (opcional): `.streamlit/secrets.toml` a partir de `.streamlit/secrets.toml.example`
6. [ ] Sem ODBC/SQL Server no servidor de *somente leitura do painel* — espelho DW só se for espelhar localmente (`ml/mirror_dw.py` + VPN)
7. [ ] Firewall/porta liberada (ex.: 8510) só na rede SES
8. [ ] Após mudança de secrets ou código: reiniciar o processo Streamlit

## Windows (atalho)

Na raiz do repositório:

```bat
abrir_dashboard_lacen_integrado.bat
```

Sobe em `http://localhost:8510` (cria `.venv` se faltar).

Com auth:

```bat
set LACEN_REQUIRE_AUTH=1
set LACEN_DASHBOARD_PASSWORD=troque-esta-senha
abrir_dashboard_lacen_integrado.bat
```

## Linux / manual

```bash
cd /opt/lacen-mt   # ou caminho da SES
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# opcional: cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # editar senhas
streamlit run lacen_dashboard_integrado_total.py \
  --server.port 8510 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
```

Dados: diretório `saida_pipeline` relativo ao cwd. Override admin só com `MODO_ADMIN=1` + secrets.

## O que NÃO colocar no servidor

- Extratos GAL/SINAN/SIM brutos (`.csv` gigantes da raiz)
- `.env` / `secrets.toml` com senhas reais no Git
- Driver ODBC, a menos que este host faça espelho DW

## Atualização operacional

```bash
git pull origin main
# atualizar saida_pipeline se houver pacote novo da equipe de dados
# reiniciar o serviço/processo Streamlit
```

Cloud (alternativa à VM SES): `STREAMLIT_CLOUD.md` — Secrets + **Reboot app**.
