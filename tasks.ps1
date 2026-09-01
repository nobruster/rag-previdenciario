# Equivalente do Makefile para PowerShell.
#   .\tasks.ps1 up | down | logs | ps | test | lint | fmt | api | install
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'up', 'down', 'logs', 'ps', 'test', 'lint', 'fmt', 'api')]
    [string]$Task = 'ps'
)

switch ($Task) {
    'install' { pip install -e ".[dev]" }
    'up'      { docker compose up -d }
    'down'    { docker compose down }
    'logs'    { docker compose logs -f }
    'ps'      { docker compose ps }
    'test'    { pytest -v }
    'lint'    { ruff check src tests }
    'fmt'     { ruff check --fix src tests }
    'api'     {
        $port = if ($env:API_PORT) { $env:API_PORT } else { '8000' }
        uvicorn isp_rag.api.main:app --reload --port $port
    }
}
