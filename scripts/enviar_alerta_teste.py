#!/usr/bin/env python3
"""
LACEN MT — envio de teste de alerta (Telegram + e-mail).

Lê os top alertas reais em saida_pipeline e envia UMA mensagem
marcada como TESTE. Não faz loop nem spam.

Uso:
  python scripts/enviar_alerta_teste.py
  python scripts/enviar_alerta_teste.py --dry-run
  python scripts/enviar_alerta_teste.py --email-only
  python scripts/enviar_alerta_teste.py --telegram-only

Credenciais (via .env na raiz do repo ou variáveis de ambiente):
  TELEGRAM_BOT_TOKEN ou TELEGRAM_TOKEN
  TELEGRAM_CHAT_ID
  EMAIL_TO (default: menandesneto@gmail.com)
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD
  ou EMAIL_USER / EMAIL_SENHA (alias Gmail SMTP)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def _read_csv(path: Path, limit: int = 50) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit]


def _cell(row: dict, *keys: str, default: str = "—") -> str:
    for k in keys:
        if k in row and str(row.get(k) or "").strip():
            return str(row[k]).strip()
    return default


def build_test_message(outdir: Path, top_n: int = 3) -> tuple[str, str]:
    """Monta assunto + corpo a partir de fila e emergência reais."""
    fila = _read_csv(outdir / "fila_operacional.csv", top_n)
    emerg = _read_csv(outdir / "indicadores_emergencia_acoes.csv", top_n)
    if not emerg:
        emerg = _read_csv(outdir / "indicadores_emergencia.csv", top_n)

    agora = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines: list[str] = [
        "=== TESTE LACEN MT — NÃO É ALERTA OPERACIONAL ===",
        f"Gerado em: {agora}",
        f"Fonte: {outdir.name}/ (top {top_n} atuais)",
        "",
        "— Fila operacional —",
    ]
    if not fila:
        lines.append("(fila_operacional.csv ausente ou vazia)")
    else:
        for i, r in enumerate(fila, 1):
            lines.append(
                f"{i}. { _cell(r, 'municipio') } | sinal={_cell(r, 'sinal')} | "
                f"prio={_cell(r, 'prioridade')} | score={_cell(r, 'score')}"
            )
            lines.append(
                f"   ação={_cell(r, 'acao_sugerida')} | prazo={_cell(r, 'prazo_acao')} | "
                f"resp={_cell(r, 'responsavel')}"
            )
            motivo = _cell(r, "motivo", default="")
            if motivo and motivo != "—":
                lines.append(f"   motivo={motivo[:160]}")

    lines.append("")
    lines.append("— Indicadores de emergência / pressão —")
    if not emerg:
        lines.append("(indicadores_emergencia*.csv ausentes)")
    else:
        for i, r in enumerate(emerg, 1):
            pressao = _cell(
                r,
                "faixa_pressao",
                "faixa_pressao_predita",
                "banda_risco",
                "prioridade_emergencia",
            )
            idx = _cell(r, "indice_pressao_rede", "indice_pressao", default="")
            fam = _cell(r, "familia", "agravo_alvo", "target", default="")
            extra = f" | pressão={pressao}"
            if idx and idx != "—":
                extra += f" (índice={idx})"
            if fam and fam != "—":
                extra += f" | família/alvo={fam}"
            lines.append(f"{i}. {_cell(r, 'municipio')}{extra}")
            lines.append(
                f"   ação={_cell(r, 'acao_sugerida')} | prazo={_cell(r, 'prazo_acao')} | "
                f"resp={_cell(r, 'responsavel')}"
            )

    lines.extend(
        [
            "",
            "Canal de teste: scripts/enviar_alerta_teste.py",
            "=== FIM DO TESTE ===",
        ]
    )
    body = "\n".join(lines)
    subject = f"[TESTE LACEN MT] Top {top_n} alertas — {agora}"
    return subject, body


def send_telegram(text: str) -> tuple[bool, str]:
    token = (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("TELEGRAM_TOKEN")
        or ""
    ).strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False, (
            "Telegram: faltam TELEGRAM_BOT_TOKEN (ou TELEGRAM_TOKEN) e/ou TELEGRAM_CHAT_ID. "
            "Defina no .env — ver .env.example."
        )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": "true"}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok"):
            return True, "Telegram: mensagem enviada."
        return False, f"Telegram: API respondeu ok=false — {data.get('description', data)}"
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"Telegram: HTTP {e.code} — {detail}"
    except Exception as e:  # noqa: BLE001 — relatório claro ao operador
        return False, f"Telegram: falha — {type(e).__name__}: {e}"


def send_email_smtp(subject: str, body: str, to_addr: str) -> tuple[bool, str]:
    user = (os.environ.get("SMTP_USER") or os.environ.get("EMAIL_USER") or "").strip()
    password = (
        os.environ.get("SMTP_PASSWORD") or os.environ.get("EMAIL_SENHA") or ""
    ).strip()
    host = (os.environ.get("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(os.environ.get("SMTP_PORT") or "587")
    from_addr = (os.environ.get("EMAIL_FROM") or user or "").strip()

    if not user or not password or not from_addr:
        return False, (
            "E-mail SMTP: faltam SMTP_USER/EMAIL_USER e SMTP_PASSWORD/EMAIL_SENHA "
            "(e EMAIL_FROM opcional). Use senha de app Gmail se 2FA estiver ativo."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
        return True, f"E-mail SMTP: enviado para {to_addr}."
    except Exception as e:  # noqa: BLE001
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
        default=os.environ.get("EMAIL_TO", "menandesneto@gmail.com"),
        help="Destinatário do e-mail de teste",
    )
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")

    outdir = args.outdir if args.outdir.is_absolute() else (ROOT / args.outdir)
    subject, body = build_test_message(outdir, top_n=max(1, args.top))

    print(subject)
    print("-" * 60)
    print(body)
    print("-" * 60)

    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return 0

    do_tg = not args.email_only
    do_mail = not args.telegram_only
    ok_any = False
    exit_code = 0

    if do_tg:
        ok, msg = send_telegram(body)
        print(msg)
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if do_mail:
        ok, msg = send_email_smtp(subject, body, args.email_to)
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
