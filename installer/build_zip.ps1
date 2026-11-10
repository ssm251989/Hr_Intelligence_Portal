<#
  Builds the client package: HR-Automation-<version>.zip
  The client unzips it and double-clicks HRAutomation.exe - nothing else (docs/INSTALLER.md).

  Run on a Windows build PC (once per release), from the repo root:
      powershell -ExecutionPolicy Bypass -File installer\build_zip.ps1 -Version 1.0.0

  Needs on the BUILD PC only (never on the client's PC):
    - Node.js 20+ (npm)        - to build the web app
    - Internet access (python.org, bootstrap.pypa.io, pypi.org, github.com, enterprisedb.com)
  No Python is needed on the build PC: the bundled Python installs its own packages.
  Optional: -PgZip <path> if the PostgreSQL download is blocked (get it from
  https://www.enterprisedb.com/download-postgresql-binaries -> Windows x86-64, version 16).
#>
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [string]$PythonVersion = "3.13.1",
  [string]$PgZip = "",
  [string]$PgUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64-binaries.zip",
  [string]$WinSWUrl = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe",
  [string]$Out = "installer\build"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x faster without the progress bar
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Cache = Join-Path $Root "installer\cache"
$Stage = Join-Path $Root "$Out\HR-Automation"
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

function Get-Cached($url, $name) {
  $f = Join-Path $Cache $name
  if (-not (Test-Path $f)) { Write-Host "Downloading $name ..."; Invoke-WebRequest -Uri $url -OutFile $f -UseBasicParsing }
  return $f
}

# 1. Python (embeddable) + packages ------------------------------------------------------
Write-Host "1/7 Python $PythonVersion"
$pyZip = Get-Cached "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" "python-$PythonVersion-embed-amd64.zip"
$py = Join-Path $Stage "runtime\python"
Expand-Archive -Path $pyZip -DestinationPath $py -Force
$tag = ($PythonVersion.Split(".")[0..1] -join "")          # 3.13.1 -> 313
# sys.path of the bundled Python: its own files, the packages, and the app's backend folder
Set-Content -Encoding ASCII -Path (Join-Path $py "python$tag._pth") -Value @("python$tag.zip", ".", "Lib\site-packages", "..\..\app\backend", "import site")
$site = Join-Path $py "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $site | Out-Null
$req = Join-Path $Root "backend\requirements-lock.txt"
if (-not (Test-Path $req)) { $req = Join-Path $Root "backend\requirements.txt"; Write-Warning "requirements-lock.txt not found - using unpinned requirements.txt" }
# The packages are installed BY THE BUNDLED PYTHON itself (pip bootstrapped with get-pip.py), so the
# build PC needs no Python of its own and the wheels always match the client's Python exactly.
$pyExe = Join-Path $py "python.exe"
$getPip = Get-Cached "https://bootstrap.pypa.io/get-pip.py" "get-pip.py"
Push-Location $Cache
& $pyExe $getPip --disable-pip-version-check --no-warn-script-location
$ok = $LASTEXITCODE; Pop-Location
if ($ok -ne 0) { throw "could not set up pip inside the bundled Python (see the error above)" }
& $pyExe -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: -r $req psycopg2-binary --target $site --upgrade
if ($LASTEXITCODE -ne 0) { throw "pip install failed - a package above has no Windows wheel for Python $PythonVersion (see the error)" }
# pip itself is not needed on the client's PC
Get-ChildItem $site -Directory -Filter "pip*" | Remove-Item -Recurse -Force
Get-ChildItem (Join-Path $py "Scripts") -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

# 2. PostgreSQL 16 binaries ---------------------------------------------------------------
Write-Host "2/7 PostgreSQL"
if (-not $PgZip) { $PgZip = Get-Cached $PgUrl "postgresql-16-windows-x64-binaries.zip" }
$tmpPg = Join-Path $Cache "pg-extract"
if (Test-Path $tmpPg) { Remove-Item -Recurse -Force $tmpPg }
Expand-Archive -Path $PgZip -DestinationPath $tmpPg -Force
$pgsql = Join-Path $Stage "runtime\pgsql"
New-Item -ItemType Directory -Force -Path $pgsql | Out-Null
foreach ($d in "bin", "lib", "share") { Copy-Item -Recurse -Force (Join-Path $tmpPg "pgsql\$d") (Join-Path $pgsql $d) }
Remove-Item -Recurse -Force $tmpPg
# not needed at run time
Get-ChildItem (Join-Path $pgsql "bin") -Include "pgAdmin*", "stackbuilder*" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

# 3. WinSW (runs the app as a Windows service) ---------------------------------------------
Write-Host "3/7 WinSW"
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "runtime\winsw") | Out-Null
Copy-Item (Get-Cached $WinSWUrl "WinSW-x64.exe") (Join-Path $Stage "runtime\winsw\WinSW-x64.exe")

# 4. Web app ---------------------------------------------------------------------------------
Write-Host "4/7 Web app (npm run build)"
Push-Location (Join-Path $Root "frontend")
& npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
$env:VITE_API_BASE_URL = "/_api"       # same origin: the bundled app serves the API under /_api
& npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
Remove-Item Env:\VITE_API_BASE_URL
Pop-Location
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "app\frontend") | Out-Null
Copy-Item -Recurse -Force (Join-Path $Root "frontend\dist") (Join-Path $Stage "app\frontend\dist")

# 5. Backend (code only - never .env, .venv, uploads or tests) ------------------------------
Write-Host "5/7 Backend"
$be = Join-Path $Stage "app\backend"
& robocopy (Join-Path $Root "backend") $be /E /NFL /NDL /NJH /NJS /NP `
  /XD .venv venv uploads tests __pycache__ .pytest_cache /XF .env "*.pyc" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "copying the backend failed (robocopy $LASTEXITCODE)" }
if (Test-Path (Join-Path $be ".env")) { throw "a .env got into the package - stop" }

# 6. Launcher + text files ------------------------------------------------------------------
Write-Host "6/7 Launcher"
$launcher = Join-Path $Root "installer\launcher\HRAutomation.exe"
if (Get-Command go -ErrorAction SilentlyContinue) {
  Push-Location (Join-Path $Root "installer\launcher"); $env:GOOS = "windows"; $env:GOARCH = "amd64"
  & go build -trimpath -ldflags "-s -w" -o HRAutomation.exe .; Pop-Location
}
Copy-Item $launcher (Join-Path $Stage "HRAutomation.exe")
Set-Content -Encoding ASCII -Path (Join-Path $Stage "VERSION.txt") -Value $Version
Copy-Item (Join-Path $Root "installer\README.txt") (Join-Path $Stage "README.txt")

# 7. Smoke test with the BUNDLED python, then zip -------------------------------------------
Write-Host "7/7 Check + zip"
Push-Location $be
& (Join-Path $py "python.exe") -c "import fastapi, sqlalchemy, psycopg2, uvicorn, alembic, bcrypt, app.platform.install.validate, app.platform.install.wizard; print('bundle ok')"
$ok = $LASTEXITCODE; Pop-Location
if ($ok -ne 0) { throw "the bundled Python cannot import the app - see the error above" }
$zip = Join-Path $Root "$Out\HR-Automation-$Version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $Stage -DestinationPath $zip -CompressionLevel Optimal
$size = [math]::Round((Get-Item $zip).Length / 1MB)
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash
Set-Content -Path "$zip.sha256" -Value "$hash  HR-Automation-$Version.zip"
Write-Host "`nDone: $zip ($size MB)  SHA-256 $hash"
