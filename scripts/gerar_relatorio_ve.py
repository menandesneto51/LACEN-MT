#!/usr/bin/env python3
"""
Gera o parecer VE inteligente (Top notif/proxy + positividade + ΔSE +
destinatários Guia MS) e opcionalmente envia alertas Telegram + HTML por e-mail.

Uso:
  python scripts/gerar_relatorio_ve.py
  python scripts/gerar_relatorio_ve.py --dry-run
  python scripts/gerar_relatorio_ve.py --enviar --to menandesneto@gmail.com
  python scripts/gerar_relatorio_ve.py --telegram --email
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

from lacen_agente_ve import (  # noqa: E402
    gerar_parecer_ve,
    juina_hbv_one_liner,
)
from enviar_alerta_teste import (  # noqa: E402
    _env,
    _load_dotenv,
    send_email_smtp,
    send_telegram,
)

OUTDIR_DEFAULT = ROOT / "saida_pipeline"


def _mask_secrets(text: str) -> str:
    text = re.sub(
        r"(TELEGRAM_(?:BOT_)?TOKEN|SMTP_PASSWORD|EMAIL_SENHA|SMTP_PASS|"
        r"LACEN_LLM_API_KEY|OPENAI_API_KEY)\s*[:=]\s*\S+",
        r"\1=***",
        text,
        flags=re.I,
    )
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot***:***", text)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parecer VE inteligente LACEN-MT / CIEVS (Guia MS)"
    )
    parser.add_argument("--outdir", type=Path, default=OUTDIR_DEFAULT)
    parser.add_argument("--se", default=None, help="SE preferida (ex.: 2026-SE30)")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só gera artefatos em saida_pipeline (sem envio)",
    )
    parser.add_argument(
        "--enviar",
        action="store_true",
        help="Envia Telegram + e-mail (atalho para --telegram --email)",
    )
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--email", action="store_true")
    parser.add_argument(
        "--to",
        dest="email_to",
        default=None,
        help="Destinatário (default: EMAIL_TO / menandesneto@gmail.com)",
    )
    parser.add_argument(
        "--no-download-ms",
        action="store_true",
        help="Não tentar baixar páginas MS (usa só conhecimento_ve local)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Desliga reescrita LLM mesmo com API key",
    )
    args = parser.parse_args(argv)

    _load_dotenv(ROOT / ".env")
    _load_dotenv(ROOT.parent / "Sentinela" / ".env")

    outdir = args.outdir if args.outdir.is_absolute() else (ROOT / args.outdir)
    parecer = gerar_parecer_ve(
        outdir,
        se=args.se,
        top=max(1, args.top),
        tentar_download_ms=not args.no_download_ms,
        usar_llm=not args.no_llm,
        persistir=True,
    )

    print(f"SE {parecer.se_iso} · gerado {parecer.gerado_em}")
    print(f"Fonte Top notificações: {parecer.fonte_notificacoes}")
    print(juina_hbv_one_liner(parecer))
    print("-" * 60)
    print(parecer.resumo_executivo)
    print("-" * 60)
    if parecer.recomendacoes_por_agravo:
        b0 = parecer.recomendacoes_por_agravo[0]
        print(f"Amostra destinatários — {b0.get('municipio')} × {b0.get('agravo')}:")
        for dest, texto in list((b0.get("destinatarios") or {}).items())[:5]:
            print(f"  · {dest}: {texto[:120]}…")
        print("-" * 60)
    print(f"MD:   {outdir / 'relatorio_ve_inteligente.md'}")
    print(f"HTML: {outdir / 'relatorio_ve_inteligente.html'}")
    print(f"CSV:  {outdir / 'relatorio_ve_acoes.csv'}")
    print(f"Alertas TG (top): {len(parecer.telegram_alertas)}")

    if args.dry_run and not (args.enviar or args.telegram or args.email):
        print("Dry-run: nenhum envio.")
        return 0

    do_tg = args.telegram or args.enviar
    do_mail = args.email or args.enviar
    if not do_tg and not do_mail and not args.dry_run:
        # default ao rodar sem flags: só gera (como dry-run de artefatos)
        print("Artefatos gerados. Use --enviar ou --telegram/--email para disparar.")
        return 0

    if args.dry_run:
        print("Dry-run: nenhum envio.")
        return 0

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
        ok, msg = send_telegram(parecer.telegram_resumo)
        print(_mask_secrets(msg))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if do_mail:
        subject = (
            f"[CIEVS Parecer VE] {parecer.se_iso} — LACEN-MT · {parecer.gerado_em}"
        )
        body = parecer.markdown[:15000]
        ok, msg = send_email_smtp(
            subject, body, to_addr, html_body=parecer.html_doc
        )
        print(_mask_secrets(msg))
        ok_any = ok_any or ok
        if not ok:
            exit_code = 1

    if not ok_any:
        print(
            "Nenhum canal enviou. Preencha .env (Telegram e/ou SMTP) — ver .env.example."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
