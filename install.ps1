# RagLeap Core installer for Windows PowerShell.
#
#   powershell -c "irm https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.ps1 | iex"
#
# It checks Docker Desktop and Git for Windows, asks which AI to use, downloads install.sh
# and runs it with the bash that comes with Git for Windows.
# Unattended: set RAGLEAP_PROVIDER to gemini, ollama or skip (optionally GEMINI_API_KEY and RAGLEAP_DIR)
# and set RAGLEAP_NONINTERACTIVE to 1 before running.
# An existing .env is never modified.

function Install-RagLeap {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

  function Say([string]$m) { Write-Host $m }
  function Fail([string]$m) { throw $m }
  function Test-Native([string]$exe, [string[]]$a) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $exe @a *> $null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
    finally { $ErrorActionPreference = $old }
  }

  Say 'RagLeap Core installer for Windows'

  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail 'Docker is not installed. Install Docker Desktop first: https://www.docker.com/products/docker-desktop'
  }
  if (-not (Test-Native 'docker' @('info'))) {
    Fail 'Docker is installed but not running. Start Docker Desktop, wait until it says it is running, then run this again.'
  }

  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) {
    Fail 'Git for Windows is not installed (it is needed to download RagLeap). Install it from https://git-scm.com/download/win and run this again.'
  }
  $bash = $null
  $gitDir = Split-Path (Split-Path $git.Source -Parent) -Parent
  foreach ($root in @($gitDir, (Split-Path $gitDir -Parent))) {
    if (-not $root) { continue }
    foreach ($rel in @('bin\bash.exe', 'usr\bin\bash.exe')) {
      $c = Join-Path $root $rel
      if ((-not $bash) -and (Test-Path $c)) { $bash = $c }
    }
  }
  if (-not $bash) {
    Fail 'Could not find the bash that comes with Git for Windows. Reinstall Git for Windows with the default options and run this again.'
  }

  $provider = $env:RAGLEAP_PROVIDER
  $interactive = ($env:RAGLEAP_NONINTERACTIVE -ne '1') -and [Environment]::UserInteractive
  $ollamaUp = $false
  try { $null = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 3; $ollamaUp = $true } catch { }

  if (-not $provider) {
    if ($interactive) {
      Say ''
      Say 'Which AI do you want to use?'
      Say '  1 - Google Gemini (free key, best quality, needs internet)'
      Say '  2 - Ollama (runs on this computer, no key, slower and less accurate)'
      Say '  3 - Skip (choose later in the dashboard: Settings tab)'
      $choice = Read-Host 'Choose 1, 2 or 3 [1]'
      if ($choice -eq '2') { $provider = 'ollama' } elseif ($choice -eq '3') { $provider = 'skip' } else { $provider = 'gemini' }
    } else {
      $provider = 'skip'
      Say 'No AI chosen (non-interactive). Pick one later in the dashboard: Settings tab.'
    }
  }
  if (@('gemini', 'ollama', 'skip') -notcontains $provider) { Fail 'RAGLEAP_PROVIDER must be gemini, ollama or skip.' }

  $geminiKey = $env:GEMINI_API_KEY
  if (($provider -eq 'gemini') -and (-not $geminiKey) -and $interactive) {
    Say 'Get a free Gemini key at https://aistudio.google.com/apikey'
    $sec = Read-Host 'Paste your Gemini API key (hidden, press Enter to skip)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { $geminiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
  }

  if (($provider -eq 'ollama') -and (-not $ollamaUp)) {
    Say ''
    Say 'The Ollama app was not found running on this computer.'
    Say 'Recommended: install it from https://ollama.com/download (small, uses your GPU if you have one), start it, then run this again.'
    Say 'Otherwise RagLeap can run Ollama inside Docker, which needs about 12 GB of free disk.'
    if ($interactive) {
      $a = Read-Host 'Continue with the Docker version? Type y to continue, anything else to stop'
      if ($a -ne 'y') { Say 'Stopped. Nothing was changed.'; return }
    }
  }

  $url = $env:RAGLEAP_INSTALL_URL
  if (-not $url) { $url = 'https://raw.githubusercontent.com/antonyrag/ragleap-core/main/install.sh' }
  $dir = $env:RAGLEAP_DIR
  if (-not $dir) { $dir = Join-Path $env:USERPROFILE 'ragleap-core' }
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ('ragleap-install-' + [Guid]::NewGuid().ToString('N') + '.sh')
  $dirPosix = $dir -replace '\\', '/'
  $tmpPosix = $tmp -replace '\\', '/'

  try {
    Say 'Downloading the installer...'
    Invoke-WebRequest -Uri $url -UseBasicParsing -OutFile $tmp
    $text = [IO.File]::ReadAllText($tmp) -replace "`r`n", "`n"
    [IO.File]::WriteAllText($tmp, $text, (New-Object Text.UTF8Encoding $false))
    $env:RAGLEAP_PROVIDER = $provider
    $env:RAGLEAP_NONINTERACTIVE = '1'
    $env:RAGLEAP_DIR = $dirPosix
    if ($geminiKey) { $env:GEMINI_API_KEY = $geminiKey }
    & $bash -l $tmpPosix
    if ($LASTEXITCODE -ne 0) { Fail 'The installer stopped with an error (see the message above).' }
  } finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $tmp
    Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:RAGLEAP_NONINTERACTIVE -ErrorAction SilentlyContinue
    Remove-Item Env:RAGLEAP_PROVIDER -ErrorAction SilentlyContinue
    Remove-Item Env:RAGLEAP_DIR -ErrorAction SilentlyContinue
  }
}

try { Install-RagLeap } catch { Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red }
Remove-Item Function:\Install-RagLeap -ErrorAction SilentlyContinue
