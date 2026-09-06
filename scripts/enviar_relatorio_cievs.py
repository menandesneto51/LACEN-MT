#!/usr/bin/env python3
"""
LACEN MT — envio do Radar LACEN / alerta CIEVS (Telegram + e-mail).

Gera o payload institucional via `lacen_relatorio_cievs.py` a partir de
`saida_pipeline` e dispara pelos mesmos canais do alerta de teste.

Uso:
  python scripts/enviar_relatorio_cievs.py --dry-run
  python scripts/enviar_relatorio_cievs.py --telegram --email --to menandesneto@gmail.com
  python scripts/enviar_relatorio_cievs.py --legado --secretario --email
  python scripts/enviar_relatorio_cievs.py --dry-run --no-dw

Modo padrão: alerta unificado (1 e-mail + 1 Telegram).
Modo --legado: alerta estratégico + CIEVS técnico separados.

Agenda sugerida: terça e sexta (Agendador de Tarefas Windows / cron).
Credenciais: ver .env.example (TELEGRAM_*, SMTP/EMAIL_*).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lacen_relatorio_cievs import (  # noqa: E402
    format_alerta_unificado,
    format_email,
    format_email_secretario,
    load_relatorio_sources,
    montar_relatorio,
    to_secretario_telegram,
    to_telegram_markdown,
    to_telegram_messages,
    to_telegram_unificado,
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
SEC_QA = OUTDIR_DEFAULT / "alerta_estrategico_qa_ultimo.txt"
UNI_TXT = OUTDIR_DEFAULT / "alerta_unificado_ultimo.txt"
UNI_HTML = OUTDIR_DEFAULT / "alerta_unificado_ultimo.html"
UNI_MD = OUTDIR_DEFAULT / "alerta_unificado_ultimo.md"


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


def _enviar_unificado(
    rel,
    *,
    args,
    to_addr: str,
    do_mail: bool,
    do_tg: bool,
) -> tuple[bool, int]:
    """Gera e envia alerta unificado (1 e-mail + 1 Telegram)."""
    subject, plain, html_body = format_alerta_unificado(rel)
    tg_text = to_telegram_unificado(rel)

    try:
        UNI_TXT.parent.mkdir(parents=True, exist_ok=True)
        UNI_TXT.write_text(subject + "\n" + ("-" * 60) + "\n" + plain + "\n", encoding="utf-8")
        UNI_HTML.write_text(html_body, encoding="utf-8")
        UNI_MD.write_text(plain + "\n", encoding="utf-8")
        print(f"Alerta unificado TXT: {UNI_TXT.relative_to(ROOT)}")
        print(f"Alerta unificado HTML: {UNI_HTML.relative_to(ROOT)}")
    except OSError as e:
        print(f"Aviso: não gravou alerta unificado ({e})")

    print(_mask_secrets(subject))
    print("-" * 60)
    print(plain)
    print("-" * 60)
    print(f"--- Telegram unificado ({len(tg_text)} chars) ---")
    print(tg_text)
    print("-" * 60)

    ok_any = False
    exit_code = 0
    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return True, 0

    if do_tg:
        ok, msg_status = send_telegram(tg_text)
        print(_mask_secrets(f"[Telegram unificado] {msg_status}"))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1
    if do_mail:
        ok, msg = send_email_smtp(subject, plain, to_addr, html_body=html_body)
        print(_mask_secrets(f"[E-mail unificado] {msg}"))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1
    return ok_any, exit_code


def _enviar_legado(
    rel,
    *,
    args,
    to_addr: str,
    do_mail: bool,
    do_tg: bool,
    want_sec: bool,
    want_cievs: bool,
) -> tuple[bool, int]:
    """Modo legado: estratégico + CIEVS separados."""
    ok_any = False
    exit_code = 0

    if want_sec:
        from lacen_alerta_estrategico import montar_alerta_estrategico

        pack = montar_alerta_estrategico(rel)
        sec_subj, sec_plain, sec_html = pack["subject"], pack["plain"], pack["html"]
        sec_tg = pack["telegram"]
        try:
            SEC_MD.parent.mkdir(parents=True, exist_ok=True)
            SEC_MD.write_text(sec_plain + "\n", encoding="utf-8")
            SEC_HTML.write_text(sec_html, encoding="utf-8")
            SEC_QA.write_text(pack["qa"].log + "\n", encoding="utf-8")
            print(f"Alerta estratégico MD: {SEC_MD.relative_to(ROOT)}")
            print(f"Alerta estratégico HTML: {SEC_HTML.relative_to(ROOT)}")
            print(f"QA estratégico: {SEC_QA.relative_to(ROOT)} · ok={pack['qa'].ok}")
        except OSError as e:
            print(f"Aviso: não gravou alerta estratégico ({e})")

        print(_mask_secrets(sec_subj))
        print("-" * 60)
        print(sec_plain)
        print("-" * 60)
        print(f"--- Telegram estratégico ({len(sec_tg)} chars) ---")
        print(sec_tg)
        print("-" * 60)
        print(pack["qa"].log)
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
        return True, 0

    return ok_any, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Radar LACEN — alerta unificado ou legado (CIEVS + Secretário)"
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
        "--unificado",
        action="store_true",
        default=True,
        help="Alerta único (default): 1 e-mail + 1 Telegram",
    )
    parser.add_argument(
        "--legado",
        action="store_true",
        help="Modo legado: alerta estratégico + CIEVS técnico separados",
    )
    parser.add_argument(
        "--secretario",
        action="store_true",
        help="(Modo legado) Também gera/envia alerta estratégico",
    )
    parser.add_argument(
        "--secretario-only",
        action="store_true",
        help="(Modo legado) Só alerta estratégico",
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

    modo_unificado = not args.legado
    if modo_unificado:
        os.environ.setdefault("LACEN_ALERTA_SEM_PAINEL", "1")

    _load_dotenv(ROOT / ".env")
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

    if modo_unificado:
        ok_any, exit_code = _enviar_unificado(
            rel, args=args, to_addr=to_addr, do_mail=do_mail, do_tg=do_tg
        )
    else:
        want_sec = bool(args.secretario or args.secretario_only)
        want_cievs = not bool(args.secretario_only)
        ok_any, exit_code = _enviar_legado(
            rel,
            args=args,
            to_addr=to_addr,
            do_mail=do_mail,
            do_tg=do_tg,
            want_sec=want_sec,
            want_cievs=want_cievs,
        )

    if not args.dry_run and not ok_any:
        print(
            "Nenhum canal enviou. Preencha .env (Telegram e/ou SMTP) — ver .env.example — "
            "ou use --dry-run para só gerar a prévia."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
