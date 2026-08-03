# -*- coding: utf-8 -*-
"""Tema visual institucional LACEN MT — alinhado ao padrão SES-MT/SISREG/CIEVS."""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from theme.tokens import (
    BACKGROUND,
    BORDER,
    PRIMARY,
    PRIMARY_DARK,
    SURFACE,
    TEXT,
    TEXT_MUTED,
)

BASE_DIR = Path(__file__).resolve().parent
LOGO_DIR = BASE_DIR / "assets" / "logos"
_STYLES = BASE_DIR / "theme" / "styles.css"

LOGO_FILES = {
    # Oficiais (preferenciais)
    "ses_governo": LOGO_DIR / "ses_governo_mt_banner.png",
    "cievs_rede_ses": LOGO_DIR / "cievs_rede_ses_banner.png",
    "cievs_ses": LOGO_DIR / "cievs_ses_faixa_preta.png",
    "vigidesastres": LOGO_DIR / "vigidesastres.png",
    # Legado / fallback
    "brasao": LOGO_DIR / "brasao_mato_grosso.png",
    "governo": LOGO_DIR / "governo_mt.svg",
    "ses": LOGO_DIR / "ses_mt_oficial.png",
    "cievs": LOGO_DIR / "cievs_mt.svg",
    "bandeira": LOGO_DIR / "bandeira_mato_grosso.svg",
}


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".svg":
        return "image/svg+xml"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "image/png"


def logo_data_uri(key: str) -> str | None:
    path = LOGO_FILES.get(key)
    if path is None or not path.exists():
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{_mime(path)};base64,{b64}"


def inject_theme() -> None:
    try:
        css = _STYLES.read_text(encoding="utf-8")
    except OSError:
        css = f"""
:root {{
  --primary: {PRIMARY};
  --primary-dark: {PRIMARY_DARK};
  --background: {BACKGROUND};
  --surface: {SURFACE};
  --text: {TEXT};
  --text-muted: {TEXT_MUTED};
  --border: {BORDER};
}}
.stApp {{ background: {BACKGROUND} !important; }}
"""
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)


def _logo_item(uri: str | None, caption: str, sub: str = "") -> str:
    if not uri:
        return (
            f'<div class="sis-logo-item"><div class="sis-logo-caption">{caption}'
            f'<span class="sis-logo-sub">{sub}</span></div></div>'
        )
    sub_html = f'<span class="sis-logo-sub">{sub}</span>' if sub else ""
    return (
        f'<div class="sis-logo-item">'
        f'<img src="{uri}" alt="{caption}" />'
        f'<div class="sis-logo-caption">{caption}{sub_html}</div>'
        f"</div>"
    )


def hero(
    title: str,
    subtitle: str,
    *,
    brand: str = "SES-MT · CIEVS-MT · LACEN MT",
    org_line: str = "Governo de Mato Grosso · Secretaria de Estado de Saúde",
    system_line: str = "Sistema Inteligente de Monitoramento Laboratorial — LACEN MT",
    right_line: str = "Vigilância Laboratorial",
    versao: str = "",
) -> None:
    """Header institucional com logomarcas oficiais SES/CIEVS/Governo MT."""
    banner = logo_data_uri("cievs_rede_ses") or logo_data_uri("ses_governo")
    ses = logo_data_uri("ses_governo") or logo_data_uri("ses")
    vigi = logo_data_uri("vigidesastres")
    versao_html = f" · {versao}" if versao else ""

    if banner:
        logos = (
            f'<div class="sis-logo-banner">'
            f'<img src="{banner}" alt="CIEVS · REDE CIEVS · SES · Governo de Mato Grosso" />'
            f"</div>"
        )
    else:
        logos = "".join(
            [
                _logo_item(ses, "SES-MT / Governo de Mato Grosso", "Secretaria de Estado de Saúde"),
            ]
        )

    vigi_html = ""
    if vigi:
        vigi_html = (
            f'<div class="sis-logo-vigi"><img src="{vigi}" alt="Vigidesastres" /></div>'
        )

    st.markdown(
        f"""
<div class="sis-logo-row sis-logo-row-oficial">{logos}{vigi_html}</div>
<div class="sis-topbar">
  <div class="sis-topbar-left">
    <div class="sis-topbar-titles">
      <div class="sis-org">{org_line}</div>
      <div class="sis-sys">{system_line}{versao_html}</div>
    </div>
  </div>
  <div class="sis-topbar-right">{right_line}</div>
</div>
<div class="sis-hero">
  <div class="sis-brand">{brand}</div>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</div>
        """,
        unsafe_allow_html=True,
    )


def meta_bar(
    *,
    atualizado: str = "—",
    fonte: str = "LACEN/GAL · SINAN · SIM · CNES · clima · território",
    status: str = "OK",
    periodo: str = "—",
) -> None:
    st.markdown(
        f"""
<div class="sis-meta-bar" role="status" aria-label="Metadados da carga">
  <div class="sis-meta-items">
    <span><strong>Atualização:</strong> {atualizado}</span>
    <span><strong>Período:</strong> {periodo}</span>
    <span><strong>Fonte:</strong> {fonte}</span>
    <span><strong>Status:</strong> {status}</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def footer_institucional(
    texto: str = (
        "<strong>SES-MT / CIEVS-MT / LACEN</strong> · Uso institucional · "
        "Dados laboratoriais e epidemiológicos · Não substitui sistemas oficiais (GAL/SINAN/SIM)"
    ),
) -> None:
    st.markdown(f'<div class="sis-footer-inst">{texto}</div>', unsafe_allow_html=True)


def section_title(title: str, subtitle: str = "") -> None:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f'<div class="sis-section"><h3>{title}</h3>{sub}</div>',
        unsafe_allow_html=True,
    )
