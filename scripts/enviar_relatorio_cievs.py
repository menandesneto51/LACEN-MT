#!/usr/bin/env python3
"""
LACEN MT — envio do Radar LACEN / alerta CIEVS (Telegram + e-mail).

Gera o payload institucional via `lacen_relatorio_cievs.py` a partir de
`saida_pipeline` e dispara pelos mesmos canais do alerta de teste.

Uso:
  python scripts/enviar_relatorio_cievs.py --dry-run
  python scripts/enviar_relatorio_cievs.py --telegram --email --to menandesneto@gmail.com
  python scripts/enviar_relatorio_cievs.py --secretario-only --email --telegram
  python scripts/enviar_relatorio_cievs.py --secretario --email

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
    format_email_secretario,
    load_relatorio_sources,
    montar_relatorio,
    to_secretario_telegram,
    to_telegram_markdown,
    to_telegram_messages,
)
from enviar_alerta_teste import (  # noqa: E402
    _env,
    _load_dotenv,
    send_email_smtp,
    send_telegram,
)

OUTDIR_DEFAULT = ROOT / "saida_pipeline"
DRY_RUN_OUT = OUTDIR_DEFAULT / "relatorio_cievs_ultimo.txt"
DRY_RUN_HTML = OUTDIR_DEFAULT / "relatorio_cievs_ultimo.html"
SEC_MD = OUTDIR_DEFAULT / "alerta_estrategico_secretario_ultimo.md"
SEC_HTML = OUTDIR_DEFAULT / "alerta_estrategico_secretario_ultimo.html"


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
        description="Radar LACEN — alerta CIEVS / alerta estratégico Secretário"
    )
    parser.add_argument("--outdir", type=Path, default=OUTDIR_DEFAULT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só imprime e grava artefatos em saida_pipeline (sem envio)",
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
        "--secretario",
        action="store_true",
        help="Também gera/envia o alerta estratégico (Secretário → gestores)",
    )
    parser.add_argument(
        "--secretario-only",
        action="store_true",
        help="Só o alerta estratégico (não envia o CIEVS técnico completo)",
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
    parser.add_argument(
        "--no-dw",
        action="store_true",
        help="Não tentar DW; usa apenas saida_pipeline",
    )
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")
    # Credenciais Telegram/SMTP alinhadas ao Sentinela (mesmo host SES)
    _load_dotenv(ROOT.parent / "Sentinela" / ".env")

    outdir = args.outdir if args.outdir.is_absolute() else (ROOT / args.outdir)
    prefer_dw = not args.no_dw
    sources = load_relatorio_sources(outdir, prefer_dw=prefer_dw)
    print(
        _mask_secrets(
            f"Fonte: {sources.fonte_primaria} | DW_ok={sources.dw_ok} | "
            f"tabelas={sources.tabelas_dw or '—'} | "
            f"local={len(sources.arquivos_local)} artefatos"
        )
    )
    rel = montar_relatorio(
        outdir,
        top_fila=max(1, args.top_fila),
        top_predito=max(1, args.top_predito),
        prefer_dw=prefer_dw,
        sources=sources,
    )

    want_sec = bool(args.secretario or args.secretario_only)
    want_cievs = not bool(args.secretario_only)

    # Default canais: ambos se nenhum --email/--telegram
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

    # --- Alerta estratégico (Secretário) ---
    if want_sec:
        sec_subj, sec_plain, sec_html = format_email_secretario(rel)
        sec_tg = to_secretario_telegram(rel)
        try:
            SEC_MD.parent.mkdir(parents=True, exist_ok=True)
            SEC_MD.write_text(sec_plain + "\n", encoding="utf-8")
            SEC_HTML.write_text(sec_html, encoding="utf-8")
            print(f"Alerta estratégico MD: {SEC_MD.relative_to(ROOT)}")
            print(f"Alerta estratégico HTML: {SEC_HTML.relative_to(ROOT)}")
        except OSError as e:
            print(f"Aviso: não gravou alerta estratégico ({e})")

        print(_mask_secrets(sec_subj))
        print("-" * 60)
        print(sec_plain)
        print("-" * 60)
        print(f"--- Telegram estratégico ({len(sec_tg)} chars) ---")
        print(sec_tg)
        print("-" * 60)

        if not args.dry_run:
            if do_tg:
                ok, msg_status = send_telegram(sec_tg)
                print(_mask_secrets(f"[Telegram estratégico] {msg_status}"))
                ok_any = ok_any or ok
                if not ok:
                    exit_code = 1
            if do_mail:
                ok, msg = send_email_smtp(
                    sec_subj, sec_plain, to_addr, html_body=sec_html
                )
                print(_mask_secrets(f"[E-mail estratégico] {msg}"))
                ok_any = ok_any or ok
                if not ok:
                    exit_code = 1

    # --- Alerta CIEVS técnico ---
    if want_cievs:
        subject, body, html_body = format_email(rel)
        tg_messages = to_telegram_messages(rel)
        tg_text = (
            "\n\n———\n\n".join(tg_messages)
            if len(tg_messages) > 1
            else (tg_messages[0] if tg_messages else to_telegram_markdown(rel))
        )

        print(_mask_secrets(subject))
        print("-" * 60)
        print(body)
        print("-" * 60)
        print(f"--- Telegram CIEVS (HTML) · {len(tg_messages)} mensagem(ns) ---")
        for i, msg in enumerate(tg_messages, 1):
            print(f"--- parte {i}/{len(tg_messages)} ({len(msg)} chars) ---")
            print(msg)
        print("-" * 60)

        try:
            DRY_RUN_OUT.parent.mkdir(parents=True, exist_ok=True)
            DRY_RUN_OUT.write_text(
                subject
                + "\n"
                + ("-" * 60)
                + "\n"
                + body
                + "\n\n--- Telegram ---\n"
                + tg_text,
                encoding="utf-8",
            )
            DRY_RUN_HTML.write_text(html_body, encoding="utf-8")
            print(f"Prévia CIEVS: {DRY_RUN_OUT.relative_to(ROOT)}")
            print(f"HTML CIEVS: {DRY_RUN_HTML.relative_to(ROOT)}")
        except OSError as e:
            print(f"Aviso: não gravou prévia CIEVS ({e})")

        if not args.dry_run:
            if do_tg:
                for i, msg in enumerate(tg_messages, 1):
                    ok, msg_status = send_telegram(msg)
                    print(
                        _mask_secrets(
                            f"[Telegram CIEVS {i}/{len(tg_messages)}] {msg_status}"
                        )
                    )
                    ok_any = ok_any or ok
                    if not ok:
                        exit_code = 1
                        break
                    if i < len(tg_messages):
                        import time

                        time.sleep(0.8)
            if do_mail:
                ok, msg = send_email_smtp(
                    subject, body, to_addr, html_body=html_body
                )
                print(_mask_secrets(f"[E-mail CIEVS] {msg}"))
                ok_any = ok_any or ok
                if not ok:
                    exit_code = 1

    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return 0

    if not ok_any:
        print(
            "Nenhum canal enviou. Preencha .env (Telegram e/ou SMTP) — ver .env.example — "
            "ou use --dry-run para só gerar a prévia."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
