# Stops the local AssureOps Python services started from this repository.
$patterns = 'assureops_mcp|assureops_api|assureops_worker'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match $patterns } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "stopped $($_.ProcessId)" }
