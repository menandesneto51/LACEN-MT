#!/usr/bin/env python3
"""
LACEN MT — envio de teste de alerta (Telegram + e-mail).

Usa o modelo institucional `lacen_alerta_modelo.py` (fila + emergência + risco)
e credenciais alinhadas a Sentinela / Araras / TITAN / Vigidesastres.

Uso:
  python scripts/enviar_alerta_teste.py
  python scripts/enviar_alerta_teste.py --dry-run
  python scripts/enviar_alerta_teste.py --email-only
  python scripts/enviar_alerta_teste.py --telegram-only

Credenciais (via .env na raiz do repo ou variáveis de ambiente):
  Telegram:
    TELEGRAM_BOT_TOKEN | TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID | TG_CHAT_ID
  E-mail SMTP (aliases Sentinela/Araras):
    EMAIL_TO | EMAIL_DESTINATARIO | ALERT_EMAIL_TO
    EMAIL_FROM | EMAIL_REMETENTE | SMTP_FROM
    SMTP_USER | EMAIL_USER | EMAIL_REMETENTE
    SMTP_PASSWORD | EMAIL_SENHA | SMTP_PASS
    SMTP_HOST | SMTP_SERVER   (default smtp.gmail.com)
    SMTP_PORT                 (default 587; 465 se SMTP_SSL=1)
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lacen_alerta_modelo import (  # noqa: E402
    format_email,
    format_telegram,
    montar_alerta_from_outdir,
)

OUTDIR_DEFAULT = ROOT / "saida_pipeline"


def _load_dotenv(path: Path) -> None:
    """Carrega .env simples (KEY=VALUE) sem sobrescrever env já definida."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _env(*keys: str, default: str = "") -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return default


def send_telegram(text: str, *, parse_mode: str = "HTML") -> tuple[bool, str]:
    token = _env("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID", "TG_CHAT_ID")
    if not token or not chat_id:
        return False, (
            "Telegram: faltam TELEGRAM_BOT_TOKEN (ou TELEGRAM_TOKEN) e/ou "
            "TELEGRAM_CHAT_ID (ou TG_CHAT_ID). Defina no .env — ver .env.example."
        )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload_dict = {
        "chat_id": chat_id,
        "text": text[:4000],
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        payload_dict["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            return True, "Telegram: mensagem enviada."
        # Retry sem parse_mode se HTML falhar
        if parse_mode and "parse" in str(data.get("description", "")).lower():
            return send_telegram(text, parse_mode="")
        return False, f"Telegram: API respondeu ok=false — {data.get('description', data)}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        if parse_mode and e.code == 400:
            return send_telegram(text, parse_mode="")
        return False, f"Telegram: HTTP {e.code} — {detail}"
    except Exception as e:  # noqa: BLE001
        return False, f"Telegram: falha — {type(e).__name__}: {e}"


def send_email_smtp(
    subject: str, body: str, to_addr: str, html_body: str | None = None
) -> tuple[bool, str]:
    user = _env("SMTP_USER", "EMAIL_USER", "EMAIL_REMETENTE")
    password = _env("SMTP_PASSWORD", "EMAIL_SENHA", "SMTP_PASS")
    host = _env("SMTP_HOST", "SMTP_SERVER", default="smtp.gmail.com")
    port_raw = _env("SMTP_PORT")
    ssl_flag = _env("SMTP_SSL", default="").lower() in ("1", "true", "yes", "on")
    port = int(port_raw or ("465" if ssl_flag else "587"))
    from_addr = _env("EMAIL_FROM", "EMAIL_REMETENTE", "SMTP_FROM", default=user)

    if not user or not password or not from_addr:
        return False, (
            "E-mail SMTP: faltam SMTP_USER/EMAIL_USER/EMAIL_REMETENTE e "
            "SMTP_PASSWORD/EMAIL_SENHA/SMTP_PASS (e EMAIL_FROM/SMTP_FROM opcional). "
            "Use senha de app Gmail se 2FA estiver ativo."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()
        if port == 465 or ssl_flag:
            with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(user, password)
                server.send_message(msg)
        return True, f"E-mail SMTP: enviado para {to_addr}."
    except Exception as e:  # noqa: BLE001
        # Fallback Titan/host secundário (padrão Araras/Sentinela)
        fb_host = _env("SMTP_FALLBACK_HOST")
        fb_port = int(_env("SMTP_FALLBACK_PORT", default="465") or "465")
        if fb_host and fb_host != host:
            try:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(fb_host, fb_port, timeout=30, context=context) as server:
                    server.login(user, password)
                    server.send_message(msg)
                return True, f"E-mail SMTP (fallback {fb_host}): enviado para {to_addr}."
            except Exception as e2:  # noqa: BLE001
                return False, (
                    f"E-mail SMTP: falha — {type(e).__name__}: {e} | "
                    f"fallback — {type(e2).__name__}: {e2}"
                )
        return False, f"E-mail SMTP: falha — {type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Teste de alerta LACEN (Telegram + e-mail)")
    parser.add_argument("--outdir", type=Path, default=OUTDIR_DEFAULT)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="Só imprime a mensagem")
    parser.add_argument("--email-only", action="store_true")
    parser.add_argument("--telegram-only", action="store_true")
    parser.add_argument(
        "--email-to",
        default=None,
        help="Destinatário (default: EMAIL_TO / EMAIL_DESTINATARIO / menandesneto@gmail.com)",
    )
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")

    outdir = args.outdir if args.outdir.is_absolute() else (ROOT / args.outdir)
    alerta = montar_alerta_from_outdir(outdir, tipo="TESTE", top_n=max(1, args.top))
    subject, body, html_body = format_email(alerta)
    tg_text = format_telegram(alerta)

    print(subject)
    print("-" * 60)
    print(body)
    print("-" * 60)
    print("--- Telegram (HTML) ---")
    print(tg_text)
    print("-" * 60)

    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return 0

    to_addr = (
        args.email_to
        or _env("EMAIL_TO", "EMAIL_DESTINATARIO", "ALERT_EMAIL_TO", default="menandesneto@gmail.com")
    )

    do_tg = not args.email_only
    do_mail = not args.telegram_only
    ok_any = False
    exit_code = 0

    if do_tg:
        ok, msg = send_telegram(tg_text)
        print(msg)
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if do_mail:
        ok, msg = send_email_smtp(subject, body, to_addr, html_body=html_body)
        print(msg)
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if not ok_any:
        print(
            "Nenhum canal enviou. Preencha .env (Telegram e/ou SMTP) e rode de novo, "
            "ou use o Gmail MCP autenticado no Cursor para o e-mail."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
