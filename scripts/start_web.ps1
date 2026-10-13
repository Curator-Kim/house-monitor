param([int]$Port = 8501)
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port
