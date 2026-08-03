# Deploy Streamlit Community Cloud

App: **LACEN MT — Sistema Inteligente de Monitoramento Laboratorial**

## Criar / atualizar o app

1. Acesse: https://share.streamlit.io/
2. Entre com a conta GitHub `menandesneto51`
3. **New app** (ou abra o app existente) → repositório `menandesneto51/LACEN-MT`
4. Branch: `main`
5. Main file path: `lacen_dashboard_integrado_total.py`
6. App URL sugerida: `lacen-mt` → `https://lacen-mt.streamlit.app`
7. Após cada push importante: **Manage app → Reboot app**

Repositório: https://github.com/menandesneto51/LACEN-MT

## Torná-lo público (obrigatório para avaliação anônima)

Se o link redireciona para `share.streamlit.io/-/auth/app`, o app está **privado**.

1. Manage app → **Settings** → **Sharing**
2. Marque **This app is public and searchable**
3. Teste em aba anônima / outro navegador

Detalhes: `STREAMLIT_PUBLICO.md`

## Dependências Cloud

O Cloud instala `requirements.txt` (inclui `scikit-learn`, `pyarrow`, `joblib`).

O app lê preferencialmente `.parquet` em `saida_pipeline` (mais rápido) e cai para `.csv`.

## Atualizar dados locais antes do push

```bat
rodar_ml_lacen.bat
```

ou:

```bat
.venv\Scripts\python.exe atualizar_sistema_lacen.py
```
