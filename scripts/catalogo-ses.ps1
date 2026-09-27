param(
    [Parameter(Mandatory = $true)]
    [string]$Query,

    [string]$Context = "LACEN-MT",

    [string]$CatalogRoot = $env:SES_DATA_CATALOG_ROOT,

    [string]$AgentRoot = $env:SES_DATA_CATALOG_AGENT_ROOT
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$localAgent = Join-Path $repoRoot "agents\ses_data_catalog\catalog_agent.py"

if (Test-Path $localAgent) {
    $agent = $localAgent
}
elseif ($AgentRoot) {
    $agent = Join-Path $AgentRoot "agents\ses_data_catalog\catalog_agent.py"
}
else {
    throw "Defina SES_DATA_CATALOG_AGENT_ROOT apontando para o clone canônico do vigia-vsr."
}

if (-not (Test-Path $agent)) {
    throw "Motor SES_DATA_CATALOG não encontrado em: $agent"
}

$pythonArgs = @($agent, $Query, "--context", $Context)

if ($CatalogRoot) {
    $pythonArgs += @("--catalog-root", $CatalogRoot)
}

python @pythonArgs
exit $LASTEXITCODE
