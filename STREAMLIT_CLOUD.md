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

## Autenticação institucional (opcional)

Por padrão o app fica **público/anônimo** (sem secrets → sem login). Isso evita lockout no Cloud antes de configurar.

Para exigir acesso SES/CIEVS:

1. **Manage app → Settings → Secrets**
2. Cole um bloco como o de `.streamlit/secrets.toml.example`, por exemplo:

```toml
[auth]
password = "troque-esta-senha"
```

ou usuários nomeados:

```toml
[auth.users]
cievs = "senha-cievs"
lacen = "senha-lacen"
```

3. **Manage app → Reboot app**
4. (Opcional) `LACEN_REQUIRE_AUTH = "1"` força o gate mesmo se a senha estiver vazia — use só com credenciais já definidas.

Local: copie `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`, ou use env `LACEN_DASHBOARD_PASSWORD` / `LACEN_AUTH_USERS=user:pass,user2:pass2` e `LACEN_REQUIRE_AUTH=1`.

Desligar: remova o bloco `[auth]` / senhas dos Secrets e faça **Reboot** (ou apague `LACEN_REQUIRE_AUTH`).

## Alertas e notificações

O Cloud **exibe** alertas (fila, emergência, risco, silêncio, pressão) lidos de `saida_pipeline/`.
Disparo Telegram/e-mail **não** roda no Streamlit Cloud; use localmente:

- Alerta teste: `python scripts/enviar_alerta_teste.py`
- Relatório CIEVS 2×/semana (terça/sexta): `python scripts/enviar_relatorio_cievs.py --dry-run` ou `enviar_relatorio_cievs.bat`

Credenciais em `.env` — ver `.env.example` (`TELEGRAM_*`, `SMTP`/`EMAIL_*`).

## Atualizar dados locais antes do push

```bat
rodar_ml_lacen.bat
```

ou:

```bat
.venv\Scripts\python.exe atualizar_sistema_lacen.py
```
