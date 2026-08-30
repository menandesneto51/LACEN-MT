#!/usr/bin/env python3
"""
LACEN MT — envio do relatório CIEVS 2×/semana (Telegram + e-mail).

Gera o payload institucional via `lacen_relatorio_cievs.py` a partir de
`saida_pipeline` e dispara pelos mesmos canais do alerta de teste.

Uso:
  python scripts/enviar_relatorio_cievs.py --dry-run
  python scripts/enviar_relatorio_cievs.py --telegram --email --to menandesneto@gmail.com
  python scripts/enviar_relatorio_cievs.py --email
  python scripts/enviar_relatorio_cievs.py --telegram

Agenda sugerida: terça e sexta (Agendador de Tarefas Windows / cron).
Credenciais: ver .env.example (TELEGRAM_*, SMTP/EMAIL_*).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lacen_relatorio_cievs import (  # noqa: E402
    format_email,
    montar_relatorio,
    to_telegram_markdown,
)
from enviar_alerta_teste import (  # noqa: E402
    _env,
    _load_dotenv,
    send_email_smtp,
    send_telegram,
)

OUTDIR_DEFAULT = ROOT / "saida_pipeline"
DRY_RUN_OUT = OUTDIR_DEFAULT / "relatorio_cievs_ultimo.txt"


def _mask_secrets(text: str) -> str:
    """Evita vazar tokens/senhas em logs."""
    text = re.sub(
        r"(TELEGRAM_(?:BOT_)?TOKEN|SMTP_PASSWORD|EMAIL_SENHA|SMTP_PASS)\s*[:=]\s*\S+",
        r"\1=***",
        text,
        flags=re.I,
    )
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***:***", text)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Relatório CIEVS 2×/semana (Telegram + e-mail)"
    )
    parser.add_argument("--outdir", type=Path, default=OUTDIR_DEFAULT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só imprime e grava saida_pipeline/relatorio_cievs_ultimo.txt",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Enviar e-mail (com --telegram ou sozinho; default=ambos se nenhum flag)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enviar Telegram",
    )
    parser.add_argument(
        "--to",
        "--email-to",
        dest="email_to",
        default=None,
        help="Destinatário (default: EMAIL_TO / menandesneto@gmail.com)",
    )
    parser.add_argument("--top-fila", type=int, default=10)
    parser.add_argument("--top-predito", type=int, default=5)
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")

    outdir = args.outdir if args.outdir.is_absolute() else (ROOT / args.outdir)
    rel = montar_relatorio(
        outdir, top_fila=max(1, args.top_fila), top_predito=max(1, args.top_predito)
    )
    subject, body, html_body = format_email(rel)
    tg_text = to_telegram_markdown(rel)

    print(_mask_secrets(subject))
    print("-" * 60)
    print(body)
    print("-" * 60)
    print("--- Telegram (HTML) ---")
    print(tg_text)
    print("-" * 60)

    # Sempre grava dry-run artifact (allowlisted)
    try:
        DRY_RUN_OUT.parent.mkdir(parents=True, exist_ok=True)
        DRY_RUN_OUT.write_text(
            subject + "\n" + ("=" * 60) + "\n" + body + "\n\n--- Telegram ---\n" + tg_text,
            encoding="utf-8",
        )
        print(f"Prévia gravada em: {DRY_RUN_OUT.relative_to(ROOT)}")
    except OSError as e:
        print(f"Aviso: não gravou prévia ({e})")

    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return 0

    # Default: ambos os canais se nenhum --email/--telegram
    if args.email or args.telegram:
        do_mail = args.email
        do_tg = args.telegram
    else:
        do_mail = True
        do_tg = True

    to_addr = (
        args.email_to
        or _env(
            "EMAIL_TO",
            "EMAIL_DESTINATARIO",
            "ALERT_EMAIL_TO",
            default="menandesneto@gmail.com",
        )
    )

    ok_any = False
    exit_code = 0

    if do_tg:
        ok, msg = send_telegram(tg_text)
        print(_mask_secrets(msg))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if do_mail:
        ok, msg = send_email_smtp(subject, body, to_addr, html_body=html_body)
        print(_mask_secrets(msg))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if not ok_any:
        print(
            "Nenhum canal enviou. Preencha .env (Telegram e/ou SMTP) — ver .env.example — "
            "ou use --dry-run para só gerar a prévia."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
