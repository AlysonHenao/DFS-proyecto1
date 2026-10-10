$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$source = Join-Path $root "smoke-input.txt"
$destination = Join-Path $root "smoke-output.txt"
"DFSha integration smoke test" | Set-Content -Path $source -NoNewline

docker compose build control-leader client
docker compose up -d control-leader datanode1 datanode2
docker compose run --rm client mkdir /smoke
docker compose run --rm client ls /
docker compose run --rm client put /work/smoke-input.txt /smoke/input.txt
docker compose run --rm client get /smoke/input.txt /work/smoke-output.txt

$sourceHash = (Get-FileHash $source -Algorithm SHA256).Hash
$destinationHash = (Get-FileHash $destination -Algorithm SHA256).Hash
if ($sourceHash -ne $destinationHash) {
    throw "SHA-256 mismatch: source=$sourceHash destination=$destinationHash"
}

docker compose run --rm client rm /smoke/input.txt
docker compose run --rm client rmdir /smoke
Remove-Item -LiteralPath $source, $destination -Force
Write-Host "Smoke test passed: RF1 + RF2 + SHA-256"
