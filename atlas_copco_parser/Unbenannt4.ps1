param(
  [string]$ControllerHost = '10.60.23.12',
  [int]$TimeoutSec = 5,

  # Optional: preselect a set to skip the menu: GA15VS23A, GA15VP13, Custom
  [ValidateSet('GA15VS23A','GA15VP13','Custom')]
  [string]$QuestionSet,

  # Used only if QuestionSet=Custom
  [string]$CustomQuestionHex = ''
)

# === Built-in QUESTION strings (output preserves this order) ===
$Questions = @{
  'GA15VS23A' = @'
30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108
'@
  'GA15VP13' = @'
30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108
'@
}

# === Interactive selection if no -QuestionSet provided ===
function Select-QuestionSet {
  $choices = @(
    New-Object System.Management.Automation.Host.ChoiceDescription '&GA15VS23A', 'Use GA15VS23A built-in question string.'
    New-Object System.Management.Automation.Host.ChoiceDescription 'GA15&VP13',   'Use GA15VP13 built-in question string.'
    New-Object System.Management.Automation.Host.ChoiceDescription '&Custom',     'Paste a custom hex question string.'
  )
  $caption = 'Select Question Set'
  $message = 'Choose which question string to use:'
  $default = 0
  if ($Host -and $Host.UI -and $Host.UI.PromptForChoice) {
    $result = $Host.UI.PromptForChoice($caption, $message, $choices, $default)
    switch ($result) {
      0 { return 'GA15VS23A' }
      1 { return 'GA15VP13' }
      2 { return 'Custom' }
    }
  }
  do {
    Write-Host "[0] GA15VS23A`n[1] GA15VP13`n[2] Custom"
    $sel = Read-Host 'Select 0/1/2'
  } until ($sel -in '0','1','2')
  return @('GA15VS23A','GA15VP13','Custom')[[int]$sel]
}

if (-not $PSBoundParameters.ContainsKey('QuestionSet')) { $QuestionSet = Select-QuestionSet }
switch ($QuestionSet) {
  'GA15VS23A' { $QuestionHex = $Questions['GA15VS23A'] }
  'GA15VP13'  { $QuestionHex = $Questions['GA15VP13'] }
  'Custom' {
    if (-not $CustomQuestionHex) {
      Write-Host "Paste your question hex (whitespace OK):"
      $CustomQuestionHex = Read-Host 'QuestionHex'
    }
    if (-not $CustomQuestionHex) { throw "No custom question hex provided." }
    $QuestionHex = $CustomQuestionHex
  }
  default { throw "Unknown QuestionSet: $QuestionSet" }
}

# === Auto-select ControllerHost based on QuestionSet (unless explicitly provided) ===
if (-not $PSBoundParameters.ContainsKey('ControllerHost')) {
  switch ($QuestionSet) {
    'GA15VP13'  { $ControllerHost = '10.60.23.11' }  # GA15VP13 -> 10.60.23.11
    'GA15VS23A' { $ControllerHost = '10.60.23.12' }  # GA15VS23A -> 10.60.23.12
    default     { }                                  # leave as-is for Custom
  }
}

$QuestionHex = $QuestionHex -replace '\s',''

# === Helpers ===
function Normalize-Key([string]$k) {
  if (-not $k) { return '' }
  $k = $k.Trim().ToUpper()
  if ($k -match '^([0-9A-F]{4})[\.\s]?([0-9A-F]{2})$') { return "$($Matches[1]).$($Matches[2])" }
  return $k
}
function Expand-KeysFromQuestion([string]$qHex) {
  $qHex = ($qHex -replace '\s','').ToUpper()
  $keys = New-Object System.Collections.Generic.List[string]
  for ($i = 0; $i -lt $qHex.Length; $i += 6) {
    $keys.Add(("{0}.{1}" -f $qHex.Substring($i,4).ToUpper(), $qHex.Substring($i+4,2).ToUpper()))
  }
  $keys
}
function Get-Answer([string]$TargetHost, [string]$qHex, [int]$timeout) {
  $uri = "http://$TargetHost/cgi-bin/mkv.cgi"
  try {
    $resp = Invoke-WebRequest -Uri $uri -Method Post `
            -Body @{ QUESTION = $qHex } `
            -ContentType 'application/x-www-form-urlencoded' `
            -TimeoutSec $timeout -ErrorAction Stop
    ($resp.Content)
  } catch {
    throw "Request failed: $($_.Exception.Message)"
  }
}
function HexSanitize([string]$s) { ($s -replace '[^0-9A-Fa-f]','').ToUpper() }
function HexSlice([string]$hex, [int]$offset, [int]$len) {
  if ($offset -lt 0 -or $offset + $len -gt $hex.Length) { return '' }
  $hex.Substring($offset, $len).ToUpper()
}
function HexToUInt32BE([string]$hex8) {
  if ([string]::IsNullOrWhiteSpace($hex8) -or $hex8.Length -ne 8 -or ($hex8 -notmatch '^[0-9A-F]{8}$')) { return $null }
  [uint32]([convert]::ToUInt32($hex8,16))
}
function LoU16([uint32]$u32) { if ($null -eq $u32) { $null } else { [uint32]($u32 -band 0xFFFF) } }
function HiU16([uint32]$u32) { if ($null -eq $u32) { $null } else { [uint32]($u32 -shr 16) } }

# --- Eval with support for cross-key refs like UInt32of3007.01 / LoU16ofABCD.EF ---
function Resolve-ExternalRefs([string]$expr) {
  $script:__resolve_ok = $true

  $sub = {
    param($m, $dict)
    $key = ("{0}.{1}" -f $m.Groups[1].Value, $m.Groups[2].Value).ToUpper()
    if ($dict.ContainsKey($key) -and $null -ne $dict[$key]) { return ($dict[$key] -as [string]) }
    $script:__resolve_ok = $false
    return ''
  }

  $expr = [regex]::Replace($expr, '\bUInt32of([0-9A-F]{4})\.([0-9A-F]{2})\b', { param($m) & $sub $m $script:KeyToU32 })
  $expr = [regex]::Replace($expr, '\bLoU16of([0-9A-F]{4})\.([0-9A-F]{2})\b',  { param($m) & $sub $m $script:KeyToLo  })
  $expr = [regex]::Replace($expr, '\bHiU16of([0-9A-F]{4})\.([0-9A-F]{2})\b',  { param($m) & $sub $m $script:KeyToHi  })

  return @{ expr=$expr; ok=$script:__resolve_ok }
}
function Eval-Calc([string]$calc, [uint32]$u32, [uint32]$lo, [uint32]$hi) {
  if ([string]::IsNullOrWhiteSpace($calc) -or $calc -eq '?') { return $null }
  $expr = $calc
  $expr = $expr -replace '\bUInt32\b', ($u32 -as [string])
  $expr = $expr -replace '\bLoU16\b',  ($lo  -as [string])
  $expr = $expr -replace '\bHiU16\b',  ($hi  -as [string])

  $resolved = Resolve-ExternalRefs $expr
  if (-not $resolved.ok) { return $null }
  $expr = $resolved.expr

  try {
    if ($expr -notmatch '^[0-9\.\+\-\*\/\(\)\s]+$') { return $null }
    [double](Invoke-Expression $expr)
  } catch { $null }
}

# === Model-specific lookup tables ===

# ------ GA15VP13 ------
$MetaVP13 = [ordered]@{
  '3002.01' = @{ Name='Compressor Outlet'; Unit='bar'; Encoding='HiU16'; Calc='HiU16/1000' }
  '3002.03' = @{ Name='Element Outlet'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }
  '3002.05' = @{ Name='Ambient Air'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }
  '3002.08' = @{ Name='Controller Temperature'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }

  # keep both metas under the same key, in-place
  '3021.01' = @(
    @{ Name='Motor requested rpm'; Unit='rpm'; Encoding='LoU16'; Calc='LoU16' }
    @{ Name='Motor actual rpm';    Unit='rpm'; Encoding='HiU16'; Calc='HiU16' }
  )

  '3003.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.02' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.0A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3007.01' = @{ Name='Running Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.03' = @{ Name='Motor Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.04' = @{ Name='Load Relay'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.05' = @{ Name='VSD 1-20'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.06' = @{ Name='VSD 20-40'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.07' = @{ Name='VSD 40-60'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.08' = @{ Name='VSD 60-80'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.09' = @{ Name='VSD 80-100'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.0B' = @{ Name='Fan Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.0C' = @{ Name='Accumulated Volume'; Unit='m3'; Encoding='UInt32'; Calc='UInt32*1000' }
  '3007.0D' = @{ Name='Module Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.0E' = @{ Name='Emergency Stops'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.0F' = @{ Name='Direct Stops'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.14' = @{ Name='Recirculation Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.15' = @{ Name='Recirculation Failures'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.18' = @{ Name='Low Load Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.22' = @{ Name='Available Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.23' = @{ Name='Unavailable Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.24' = @{ Name='Emergency Stop Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3021.05' = @{ Name='Motor amperage'; Unit='A'; Encoding='HiU16'; Calc='HiU16' }
  '3021.0A' = @{ Name='Flow'; Unit='%'; Encoding='HiU16'; Calc='HiU16' }
  '3005.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.02' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.05' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.08' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.09' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.03' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.2A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.88' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.03' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.05' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.08' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.09' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.10' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.11' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.12' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.13' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.14' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.15' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.16' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.17' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.18' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.19' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.20' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.21' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.22' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.23' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.24' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.25' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.26' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.27' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.28' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.29' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.06' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.11' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.12' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3001.08' = @{ Name='Machine Status'; Unit='code'; Encoding='?'; Calc='?' }
}

# ------ GA15VS23A ------
$MetaVS23A = [ordered]@{
  '3002.01' = @{ Name='Controller Temperature'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }
  '3002.24' = @{ Name='Compressor Outlet'; Unit='bar'; Encoding='HiU16'; Calc='HiU16/1000' }
  '3002.26' = @{ Name='Ambient Air'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }
  '3002.27' = @{ Name='Relative Humidity'; Unit='%'; Encoding='HiU16'; Calc='HiU16' }
  '3002.2A' = @{ Name='Element Outlet'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }
  '3002.66' = @{ Name='Aftercooler drain PCB Temperature'; Unit='°C'; Encoding='HiU16'; Calc='HiU16/10' }

  # both motor RPM metas
  '3021.01' = @(
    @{ Name='Motor requested rpm'; Unit='rpm'; Encoding='LoU16'; Calc='LoU16' }
    @{ Name='Motor actual rpm';    Unit='rpm'; Encoding='HiU16'; Calc='HiU16' }
  )
  # both fan RPM metas
  '3022.01' = @(
    @{ Name='Fan Motor requested rpm'; Unit='rpm'; Encoding='LoU16'; Calc='LoU16' }
    @{ Name='Fan Motor actual rpm';    Unit='rpm'; Encoding='HiU16'; Calc='HiU16' }
  )

  '3007.01' = @{ Name='Running Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.03' = @{ Name='Motor Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.04' = @{ Name='Load Relay'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.05' = @{ Name='VSD 1-20'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.06' = @{ Name='VSD 20-40'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.07' = @{ Name='VSD 40-60'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.08' = @{ Name='VSD 60-80'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.09' = @{ Name='VSD 80-100'; Unit='%'; Encoding='UInt32'; Calc='UInt32/UInt32of3007.01*100' }
  '3007.0B' = @{ Name='Fan Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.0C' = @{ Name='Accumulated Volume'; Unit='m3'; Encoding='UInt32'; Calc='UInt32*1000' }
  '3007.0D' = @{ Name='Module Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.0E' = @{ Name='Emergency Stops'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.0F' = @{ Name='Direct Stops'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.17' = @{ Name='Recirculation Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.18' = @{ Name='Recirculation Failures'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.1B' = @{ Name='Low Load Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.25' = @{ Name='Available Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.26' = @{ Name='Unavailable Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.27' = @{ Name='Emergency Stop Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.43' = @{ Name='Display Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.4C' = @{ Name='Boostflow Hours'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.4D' = @{ Name='Boostflow Activations'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.54' = @{ Name='Emergency Stops During Running'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.55' = @{ Name='Drain 1 Operation Time'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3007.56' = @{ Name='Drain 1 number of switching actions'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.57' = @{ Name='Drain 1 number of manual drainings'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3021.05' = @{ Name='Flow'; Unit='%'; Encoding='HiU16'; Calc='HiU16' }
  '3021.0A' = @{ Name='Motor amperage'; Unit='A'; Encoding='HiU16'; Calc='HiU16' }
  '3022.0A' = @{ Name='Fan Motor amperage'; Unit='A'; Encoding='HiU16'; Calc='HiU16' }
  '3005.1F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.20' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.21' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.27' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.28' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.29' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3005.2A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.03' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.05' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.2A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '300E.F3' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '310E.23' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '310E.27' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '310E.2B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '310E.3B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.03' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.05' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.08' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.09' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.0F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.10' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.11' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.12' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.13' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.14' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.15' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.16' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.17' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.18' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.19' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.1F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.20' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.21' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.22' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.23' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.24' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.25' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.26' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.27' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.28' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.29' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3113.2F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.02' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.03' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.04' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.05' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.06' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.08' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.09' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0B' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0C' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0D' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.0F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.10' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.11' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3114.12' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.06' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.11' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.07' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.12' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.09' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3009.14' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3001.08' = @{ Name='Machine Status'; Unit='code'; Encoding='?'; Calc='?' }
}

# ------ Choose active $Meta ------
switch ($QuestionSet) {
  'GA15VP13'  { $Meta = $MetaVP13 }
  'GA15VS23A' { $Meta = $MetaVS23A }
  'Custom'    { $Meta = [ordered]@{} }
  default     { $Meta = [ordered]@{} }
}

# --- Build a case-insensitive lookup that ALWAYS returns an array of metas (PS 5.x-safe) ---
$script:MetaLookup = @{}
foreach ($k in $Meta.Keys) {
  $nk = Normalize-Key $k
  $v  = $Meta[$k]
  if ($v -is [System.Collections.IList]) {
    $script:MetaLookup[$nk] = @($v | ForEach-Object { $_ })
  } else {
    $script:MetaLookup[$nk] = ,$v
  }
}

function Get-MetaForKey($key) {
  $nk = Normalize-Key $key
  if ($script:MetaLookup.ContainsKey($nk)) { return $script:MetaLookup[$nk] }  # always array
  return @(@{ 'Name'='?'; 'Unit'='?'; 'Encoding'='?'; 'Calc'='?' })
}

# Track unknown keys once
$UnknownKeys = New-Object System.Collections.Generic.HashSet[string]

# === Fetch answer and PRE-INDEX all raw values for cross-key calcs ===
$keys      = (Expand-KeysFromQuestion $QuestionHex)
$answerRaw = Get-Answer -TargetHost $ControllerHost -qHex $QuestionHex -timeout $TimeoutSec
$ansHex    = HexSanitize $answerRaw

$script:KeyToU32 = @{}
$script:KeyToLo  = @{}
$script:KeyToHi  = @{}

for ($i = 0; $i -lt $keys.Count; $i++) {
  $k   = Normalize-Key $keys[$i]
  $raw = HexSlice -hex $ansHex -offset ($i*8) -len 8
  $u32 = HexToUInt32BE $raw
  $lo  = LoU16 $u32
  $hi  = HiU16 $u32
  $script:KeyToU32[$k] = $u32
  $script:KeyToLo[$k]  = $lo
  $script:KeyToHi[$k]  = $hi
}

# === Build rows ONLY for the selected question (NO SORT) ===
$rows = foreach ($idx in 0..($keys.Count-1)) {
  $key = Normalize-Key $keys[$idx]
  $raw = HexSlice -hex $ansHex -offset ($idx*8) -len 8
  $u32 = $script:KeyToU32[$key]
  $lo  = $script:KeyToLo[$key]
  $hi  = $script:KeyToHi[$key]

  $metas = Get-MetaForKey $key  # -> array of meta entries
  foreach ($meta in $metas) {
    if ($meta.Name -eq '?' -and $meta.Encoding -eq '?' -and $meta.Calc -eq '?') { [void]$UnknownKeys.Add($key) }

    $calc = $meta['Calc']
    $val  = Eval-Calc -calc $calc -u32 $u32 -lo $lo -hi $hi

    $encSuffix = switch ($meta['Encoding']) {
      'LoU16'  { ' (Lo)' }
      'HiU16'  { ' (Hi)' }
      default  { '' }
    }

    [pscustomobject]([ordered]@{
      Key      = $key
      Name     = ($meta['Name'] + $encSuffix)
      Raw      = $raw
      UInt32   = $u32
      LoU16    = $lo
      HiU16    = $hi
      Encoding = $meta['Encoding']
      Calc     = $calc
      Value    = $val
      Unit     = $meta['Unit']
    })
  }
}

# === PRINT as-is (NO SORT) to preserve the question order ===
$rows | Format-Table -Property Key,Name,Raw,UInt32,LoU16,HiU16,Encoding,Calc,Value,Unit -AutoSize

if ($UnknownKeys.Count -gt 0) {
  Write-Host "`n[Info] Keys without metadata in table:" -ForegroundColor Yellow
  $UnknownKeys | Sort-Object | ForEach-Object { Write-Host "  $_" }
}
