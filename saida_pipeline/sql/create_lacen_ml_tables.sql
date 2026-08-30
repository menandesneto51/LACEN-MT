-- LACEN MT — DDL para espelho ML no Datawarehouse
-- Executar com usuário que tenha CREATE TABLE no schema alvo.
-- Schema sugerido: dbo

IF OBJECT_ID(N'[dbo].[lacen_ml_risco_predito]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_ml_risco_predito] (
    [municipio] NVARCHAR(500),
    [target] NVARCHAR(500),
    [epi_year] BIGINT,
    [epi_week] BIGINT,
    [familia] NVARCHAR(500),
    [prob_alerta_proxima_janela] FLOAT,
    [limiar_operacional] FLOAT,
    [acima_limiar] BIT,
    [faixa_predita] NVARCHAR(500),
    [drivers] NVARCHAR(500),
    [tipo_sinal] NVARCHAR(500),
    [acao_sugerida] NVARCHAR(500),
    [metodo] NVARCHAR(500),
    [modelo_versao] NVARCHAR(500),
    [risco_composto] FLOAT,
    [positividade] FLOAT,
    [tests] BIGINT,
    [banda_absoluta] NVARCHAR(500),
    [percentil_estadual] FLOAT,
    [banda_percentil] NVARCHAR(500),
    [banda_risco] NVARCHAR(500),
    [criterio_banda] NVARCHAR(500),
    [legenda_banda] NVARCHAR(500),
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_ml_silencio_predito]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_ml_silencio_predito] (
    [municipio] NVARCHAR(500),
    [target] NVARCHAR(500),
    [epi_year] BIGINT,
    [epi_week] BIGINT,
    [prob_silencio_proxima_janela] FLOAT,
    [limiar_operacional] FLOAT,
    [acima_limiar] BIT,
    [tests_ultima_semana] BIGINT,
    [tests_ma8] FLOAT,
    [notificacoes_ultima_semana] FLOAT,
    [semanas_sem_exame] FLOAT,
    [faixa_silencio_predita] NVARCHAR(500),
    [tipo_sinal] NVARCHAR(500),
    [acao_sugerida] NVARCHAR(500),
    [metodo] NVARCHAR(500),
    [modelo_versao] NVARCHAR(500),
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_ml_backtest_summary]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_ml_backtest_summary] (
    [modelo] NVARCHAR(500),
    [escopo] NVARCHAR(500),
    [status] NVARCHAR(500),
    [metodo] NVARCHAR(500),
    [threshold] FLOAT,
    [f1_at_threshold] FLOAT,
    [n_train] FLOAT,
    [n_test] FLOAT,
    [n_train_weeks] BIGINT,
    [n_test_weeks] BIGINT,
    [n] BIGINT,
    [n_alerta_emitido] BIGINT,
    [n_confirmado] BIGINT,
    [auc] FLOAT,
    [precision] FLOAT,
    [recall] FLOAT,
    [brier] FLOAT,
    [confirmacao] FLOAT,
    [pos_rate] FLOAT,
    [precision_at_20] FLOAT,
    [precision_at_50] FLOAT,
    [rotulo] FLOAT,
    [rotulo_nota] FLOAT,
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_alerta_historico]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_alerta_historico] (
    [data_emissao] NVARCHAR(500),
    [tipo] NVARCHAR(500),
    [municipio] NVARCHAR(500),
    [agravo_alvo] NVARCHAR(500),
    [epi_year] BIGINT,
    [epi_week] BIGINT,
    [prob] FLOAT,
    [horizon_weeks] BIGINT,
    [desfecho] NVARCHAR(500),
    [confirmado] BIGINT,
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_alerta_emergencia_historico]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_alerta_emergencia_historico] (
    [ano_se] BIGINT,
    [semana_epidemiologica] BIGINT,
    [codigo_ibge] FLOAT,
    [municipio] NVARCHAR(500),
    [sla_crise] BIT,
    [silencio_gal_alerta] BIT,
    [divergencia_gal_notif] BIT,
    [faixa_pressao] NVARCHAR(500),
    [pressao_alta] BIT,
    [indice_pressao_rede] FLOAT,
    [prob_pressao_alta_proxima_janela] FLOAT,
    [faixa_pressao_predita] FLOAT,
    [pressao_predita_acima_limiar] FLOAT,
    [prioridade_emergencia] FLOAT,
    [ts_geracao] NVARCHAR(500),
    [tipo_sinal] NVARCHAR(500),
    [fonte_stamp] NVARCHAR(500),
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_fila_operacional]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_fila_operacional] (
    [municipio] NVARCHAR(500),
    [sinal] NVARCHAR(500),
    [motivo] NVARCHAR(500),
    [prioridade] NVARCHAR(500),
    [acao_sugerida] NVARCHAR(500),
    [responsavel] NVARCHAR(500),
    [prazo_acao] NVARCHAR(500),
    [checklist_operacional] NVARCHAR(500),
    [agravo_alvo] FLOAT,
    [exames] FLOAT,
    [positividade] FLOAT,
    [score] FLOAT,
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_indicadores_rede]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_indicadores_rede] (
    [municipio] NVARCHAR(500),
    [exames] BIGINT,
    [tat_mediano_dias] FLOAT,
    [tat_p90_dias] FLOAT,
    [tat_lab_mediano_dias] FLOAT,
    [logistica_mediana_dias] FLOAT,
    [pct_liberado_48h] FLOAT,
    [pct_liberado_48h_coleta] FLOAT,
    [pct_liberado_7d] FLOAT,
    [pct_liberado_14d] FLOAT,
    [pct_rejeitado] FLOAT,
    [backlog_estimado] BIGINT,
    [pct_inconclusivo] FLOAT,
    [pct_liberado] FLOAT,
    [fonte] NVARCHAR(500),
    [anos_referencia] NVARCHAR(500),
    [interpretacao] NVARCHAR(500),
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

IF OBJECT_ID(N'[dbo].[lacen_qualidade_dado]', N'U') IS NULL
BEGIN
    CREATE TABLE [dbo].[lacen_qualidade_dado] (
    [municipio] NVARCHAR(500),
    [exames] BIGINT,
    [positivos] BIGINT,
    [notif_join] FLOAT,
    [semanas_com_dado] BIGINT,
    [populacao] FLOAT,
    [notif_sinan] FLOAT,
    [confianca_dado] FLOAT,
    [faixa_confianca] NVARCHAR(500),
    [gap_sinan_sem_exame] BIT,
    [join_sinan_fraco] BIT,
    [interpretacao] NVARCHAR(500),
    [_loaded_at] DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO
