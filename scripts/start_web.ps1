$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -m streamlit run app.py
