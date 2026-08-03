# Liberar o painel LACEN (acesso anônimo)

URL:

https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/

O repositório GitHub `menandesneto51/LACEN-MT` já está **público**.  
Se o link ainda vai para `share.streamlit.io/-/auth/app`, o **app** está marcado como privado no Streamlit Cloud (independente do GitHub).

## Forma mais rápida (recomendado)

1. Abra o app **logado como dono** (`menandesneto51`):  
   https://menandesneto51-lacen-mt-lacen-dashboard-integrado-total-nrdgik.streamlit.app/
2. No canto **superior direito**, clique em **Share**.
3. Ative / clique em **Make this app public**  
   (ou equivalente: tornar o app público).
4. Feche o diálogo.
5. Abra uma **janela anônima** (Ctrl+Shift+N), cole o mesmo link e confirme que **não** pede login.

## Forma pelas Settings

1. https://share.streamlit.io/ → sign-in com GitHub `menandesneto51`
2. Localize o app LACEN-MT
3. **⋮** (três pontos) → **Settings**
4. Aba / seção **Sharing**
5. Em **Who can view this app**, selecione exatamente:

   **This app is public and searchable**

   (não deixe marcado: *Only specific people can view this app*)
6. **Save**
7. Opcional: **Manage app → Reboot**
8. Teste em janela anônima

## Se ainda pedir login

- Confirme que está alterando o app certo (URL `…nrdgik.streamlit.app`).
- Saia da conta Streamlit na janela anônima (não use perfil logado para o teste).
- Desative extensões que bloqueiam cookies do domínio `streamlit.app` / `share.streamlit.io`.
- Como paliativo: em **Share**, convide o e-mail do revisor (ele autentica uma vez).

## Depois de público

Envie de novo o link ao revisor. Ele deve abrir o painel direto, sem `/auth/app`.

## Avaliação sem Cloud (enquanto isso)

```bat
abrir_dashboard_lacen_integrado.bat
```

http://localhost:8510 — prints das abas também servem para a avaliação visual.
