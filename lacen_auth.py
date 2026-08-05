# -*- coding: utf-8 -*-
"""Controle de acesso institucional — dashboard LACEN MT (SES-MT / CIEVS / Vigidesastres).

Padrão: modo público/anônimo quando não há segredos nem LACEN_REQUIRE_AUTH.
Com senha/usuários em st.secrets (Cloud) ou variáveis de ambiente (local), exige login.
"""
from __future__ import annotations

import hmac
import os
from typing import Any

import streamlit as st

from lacen_theme import footer_institucional, logo_data_uri


def _flag_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "on"}


def _env_flag(name: str) -> bool:
    return _flag_true(os.environ.get(name, ""))


def _secrets_safe() -> Any:
    try:
        return st.secrets
    except Exception:
        return None


def _secret_get(key: str, default: Any = None) -> Any:
    secrets = _secrets_safe()
    if secrets is None:
        return default
    try:
        return secrets.get(key, default)
    except Exception:
        return default


def _auth_block() -> dict:
    raw = _secret_get("auth", {})
    if raw is None:
        return {}
    try:
        return dict(raw)
    except Exception:
        return {}


def configured_credentials() -> tuple[str | None, dict[str, str]]:
    """Retorna (senha_compartilhada|None, {usuario: senha})."""
    shared = str(os.environ.get("LACEN_DASHBOARD_PASSWORD", "")).strip() or None
    users: dict[str, str] = {}

    raw_users = str(os.environ.get("LACEN_AUTH_USERS", "")).strip()
    if raw_users:
        for part in raw_users.split(","):
            part = part.strip()
            if ":" not in part:
                continue
            user, pwd = part.split(":", 1)
            user, pwd = user.strip(), pwd.strip()
            if user and pwd:
                users[user] = pwd

    auth = _auth_block()
    if auth:
        for key in ("password", "dashboard_password", "senha"):
            if auth.get(key) and not shared:
                shared = str(auth[key]).strip() or None
                break
        u_sec = auth.get("users")
        if isinstance(u_sec, dict):
            for user, pwd in u_sec.items():
                user_s, pwd_s = str(user).strip(), str(pwd).strip()
                if user_s and pwd_s:
                    users[user_s] = pwd_s

    for key in ("LACEN_DASHBOARD_PASSWORD", "DASHBOARD_PASSWORD"):
        top = _secret_get(key)
        if top and not shared:
            shared = str(top).strip() or None

    return shared, users


def auth_is_enforced() -> bool:
    """True se o painel deve exigir login."""
    if _env_flag("LACEN_REQUIRE_AUTH"):
        return True
    if _flag_true(_secret_get("LACEN_REQUIRE_AUTH", False)):
        return True
    auth = _auth_block()
    if _flag_true(auth.get("require_auth", False)):
        return True
    shared, users = configured_credentials()
    return bool(shared or users)


def _safe_eq(a: str, b: str) -> bool:
    a_b = a.encode("utf-8")
    b_b = b.encode("utf-8")
    if len(a_b) != len(b_b):
        return hmac.compare_digest(a_b, a_b) and False
    return hmac.compare_digest(a_b, b_b)


def verify_credentials(username: str, password: str) -> bool:
    shared, users = configured_credentials()
    username = (username or "").strip()
    password = password or ""

    if users:
        expected = users.get(username)
        return expected is not None and _safe_eq(password, expected)

    if shared:
        return _safe_eq(password, shared)

    return False


def is_authenticated() -> bool:
    return bool(st.session_state.get("lacen_authenticated"))


def logout() -> None:
    for key in ("lacen_authenticated", "lacen_auth_user"):
        st.session_state.pop(key, None)


def _render_login_screen(*, needs_username: bool) -> None:
    banner = logo_data_uri("cievs_rede_ses") or logo_data_uri("ses_governo")
    vigi = logo_data_uri("vigidesastres")

    logos_html = ""
    if banner:
        logos_html += (
            f'<div class="sis-logo-banner">'
            f'<img src="{banner}" alt="CIEVS · SES · Governo de Mato Grosso" />'
            f"</div>"
        )
    if vigi:
        logos_html += (
            f'<div class="sis-logo-vigi"><img src="{vigi}" alt="Vigidesastres" /></div>'
        )

    st.markdown(
        f"""
<div class="sis-logo-row sis-logo-row-oficial">{logos_html}</div>
<div class="sis-topbar">
  <div class="sis-topbar-left">
    <div class="sis-topbar-titles">
      <div class="sis-org">Governo de Mato Grosso · Secretaria de Estado de Saúde</div>
      <div class="sis-sys">Acesso institucional — LACEN MT / CIEVS-MT / Vigidesastres</div>
    </div>
  </div>
  <div class="sis-topbar-right">Uso restrito SES-MT</div>
</div>
<div class="sis-hero">
  <div class="sis-brand">SES-MT · CIEVS-MT · LACEN MT</div>
  <h1>Acesso ao painel de vigilância laboratorial</h1>
  <p>Entre com as credenciais institucionais para visualizar a sala de situação.
  Dados agregados de LACEN/GAL, SINAN, SIM e rede laboratorial.</p>
</div>
        """,
        unsafe_allow_html=True,
    )

    col_l, col_m, col_r = st.columns([1, 2, 1])
    with col_m:
        st.markdown("#### Identificação")
        with st.form("lacen_login_form", clear_on_submit=False):
            username = ""
            if needs_username:
                username = st.text_input("Usuário institucional", autocomplete="username")
            password = st.text_input(
                "Senha",
                type="password",
                autocomplete="current-password",
            )
            submitted = st.form_submit_button("Entrar", use_container_width=True)

        if submitted:
            if verify_credentials(username, password):
                st.session_state["lacen_authenticated"] = True
                st.session_state["lacen_auth_user"] = (
                    username.strip() if username.strip() else "institucional"
                )
                st.rerun()
            st.error("Credenciais inválidas. Verifique usuário/senha com a equipe CIEVS/SES-MT.")

        st.caption(
            "Acesso destinado a equipes da SES-MT, CIEVS-MT, LACEN e Vigidesastres. "
            "Não compartilhe senhas em canais públicos."
        )

    footer_institucional(
        "<strong>SES-MT / CIEVS-MT / LACEN</strong> · Acesso institucional · "
        "Configure segredos em Streamlit Cloud ou `.streamlit/secrets.toml` local"
    )


def require_auth() -> None:
    """Bloqueia o painel até autenticação, se a política estiver ativa."""
    if not auth_is_enforced():
        return
    if is_authenticated():
        return

    shared, users = configured_credentials()
    if not shared and not users:
        st.error(
            "Autenticação exigida (`LACEN_REQUIRE_AUTH`), mas nenhuma senha/usuário "
            "foi configurado."
        )
        st.info(
            "No Streamlit Cloud: **Manage app → Secrets** e defina `auth.password` "
            "ou `[auth.users]`. Local: copie `.streamlit/secrets.toml.example`."
        )
        footer_institucional()
        st.stop()

    _render_login_screen(needs_username=bool(users))
    st.stop()


def auth_sidebar_status() -> None:
    """Mostra usuário autenticado e botão Sair (quando o gate está ativo)."""
    if not auth_is_enforced() or not is_authenticated():
        return
    user = str(st.session_state.get("lacen_auth_user") or "institucional")
    st.caption(f"Sessão: **{user}**")
    if st.button("Encerrar sessão", key="lacen_logout_btn"):
        logout()
        st.rerun()
