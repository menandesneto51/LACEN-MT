# Buscar no Catálogo Mestre SES-MT

Execute o preflight de dados deste projeto antes de propor nova fonte ou integração.

```powershell
.\scripts\catalogo-ses.ps1 -Query "<necessidade de dados>"
```

O comando deve retornar um `CatalogEvidencePack` contendo:
- fontes candidatas;
- objetos/tabelas/views;
- campos candidatos;
- sensibilidade/PII;
- `catalog_health`;
- ranking/termos correspondentes;
- limitações;
- próximo passo.

Se houver fonte existente, não criar coletor novo antes de validar qualidade e disponibilidade.

Se não houver match e algum inventário estiver `partial` ou `missing`, atualizar o Catálogo Mestre antes de concluir que uma nova fonte é necessária.
