# Revisar necessidade de nova fonte SES-MT

Use somente após o SES_DATA_CATALOG.

```powershell
.\scripts\nova-fonte-ses.ps1 -Query "<necessidade de dados>"
```

- reuse_existing: bloquear nova fonte.
- refresh_catalog: bloquear até atualização do catálogo.
- review_new_source: gerar NewSourceReviewPack em draft.
- implementation_allowed deve permanecer false.
- exigir DATA_GUARDIAN, DATAOPS, SECURITY_PRIVACY, DOMAIN_OWNER e ARCHITECTURE.
- nunca incluir credenciais ou microdados.
