# Tornar o painel LACEN público no Streamlit Community Cloud

**Reenvio (2026-08-03):** último código em `main` inclui parquet, ML sklearn e aba Integração SINAN/SIM/CNES.
Após o push, faça **Manage app → Reboot** e confirme Sharing público.

Se o link redireciona para `share.streamlit.io/-/auth/app`, o app está **privado**.

## Passo a passo

1. Entre em https://share.streamlit.io/ com GitHub (`menandesneto51`).
2. Abra o app **LACEN-MT** (ou o nome que você criou).
3. Clique nos **⋮** (Manage app) → **Settings** → **Sharing**.
4. Marque:
   - **This app is public and searchable**  
   (ou equivalente: *Anyone can access this app*).
5. **Manage app → Reboot app** (para puxar o commit mais recente).
6. Teste em aba anônima / outro navegador sem login.

## Link esperado

Após público, o formato é:

`https://<seu-subdominio>.streamlit.app`

Ex.: `https://lacen-mt.streamlit.app` (se o nome estiver livre).

## Se ainda pedir login

- Confirme que não há *Viewer authentication* / *Google/GitHub only*.
- Confirme que o repositório GitHub `menandesneto51/LACEN-MT` continua **público**.
- Redeploy: Manage app → Reboot app.

## Validação local (sem Cloud)

```bat
abrir_dashboard_lacen_integrado.bat
```

Abre em http://localhost:8510
