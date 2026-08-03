# Liberar o painel LACEN no Streamlit Community Cloud (público)

URL atual:

https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/

Se o link redireciona para `share.streamlit.io/-/auth/app`, o app **ainda não está público para anônimos** (ou há autenticação de viewers ligada).

## Checklist completo (conta GitHub `menandesneto51`)

### 1) Sharing do app
1. Abra https://share.streamlit.io/
2. **My apps** → app **LACEN-MT** (ou nome equivalente)
3. **⋮** → **Settings** → **Sharing**
4. Marque **This app is public and searchable**
5. Salve

### 2) Autenticação de viewers (causa comum do redirect)
No mesmo **Settings**, verifique se existe:
- **Viewer authentication** / **Require viewers to log in**
- **Google / GitHub / password only**

Deixe **desligado** (Anyone can view without signing in).

### 3) Workspace / organização
Se o app estiver em um workspace da SES/empresa:
- Confirme que não há política “all apps require login”
- Se possível, mova o app para a conta pessoal ou workspace sem SSO obrigatório

### 4) Reboot + teste anônimo
1. **Manage app → Reboot**
2. Abra o link em **janela anônima** (Ctrl+Shift+N) **sem** estar logado no Streamlit
3. O painel deve abrir direto, sem tela de login

### 5) Alternativa pelo botão Share
No app aberto (logado como dono): canto superior direito **Share** → tornar público / “Anyone with the link”.

## Separação recomendada (dados de saúde)

| Ambiente | Conteúdo | Acesso |
|----------|----------|--------|
| **Protótipo público** | Agregados estaduais, rankings sem microdado sensível | Público |
| **Institucional (SES/VPN)** | Detalhe municipal, SIM/SINAN nominais, DW | Restrito / intranet |

O repositório Cloud já usa só CSVs/parquet agregados de `saida_pipeline` (não sobe bases brutas).

## Validação local (sempre funciona)

```bat
abrir_dashboard_lacen_integrado.bat
```

http://localhost:8510
