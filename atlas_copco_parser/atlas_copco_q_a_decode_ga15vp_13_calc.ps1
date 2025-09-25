param(
  [string]$ControllerHost = '10.60.23.11',
  [int]$TimeoutSec = 5,
  [switch]$Discover,          # run the key discovery workflow (generates a minimal QuestionHex)
  [int]$BatchSize = 32        # discovery sends keys in batches of N
)

# === QUESTION 2 (paste your hex; whitespace OK) ===
$QuestionHex = @'
30020130020330020530020830030130030230030a30070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071430071530071830072230072330072430210130210530210a300501300502300504300505300507300508300509300e03300e04300e2a300e8831130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300108
'@ -replace '\s',''

# --- build a QUESTION hex from a list of keys like '3002.01'
function Build-QuestionHexFromKeys([string[]]$Keys) {
  ($Keys | ForEach-Object {
    $parts = $_ -split '\.'
    ($parts[0] + $parts[1])
  }) -join ''
}

# --- expand QUESTION into key list like 3002.01, 3002.03, ... ---
function Expand-KeysFromQuestion([string]$qHex) {
  $qHex = ($qHex -replace '\s','').ToUpper()
  $keys = New-Object System.Collections.Generic.List[string]
  for ($i = 0; $i -lt $qHex.Length; $i += 6) {
    $idx = $qHex.Substring($i, 4).ToUpper()
    $si  = $qHex.Substring($i + 4, 2).ToUpper()
    $keys.Add("$idx.$si")
  }
  $keys
}

# --- send QUESTION and get full answer string (verbatim) ---
function Get-Answer([string]$TargetHost, [string]$qHex, [int]$timeout) {
  $uri = "http://$TargetHost/cgi-bin/mkv.cgi"
  $resp = Invoke-WebRequest -Uri $uri -Method Post `
          -Body @{ QUESTION = $qHex } `
          -ContentType 'application/x-www-form-urlencoded' `
          -TimeoutSec $timeout -ErrorAction Stop
  ($resp.Content)
}

# --- split map: fan out one key into multiple output rows
$SplitKeys = @{
  '3021.01' = @('3021.01-Hi','3021.01-Lo')  # Hi=actual RPM, Lo=requested RPM
}

# === Meta: Name / Unit / Encoding / Calc ===
$Meta = [ordered]@{
  # 3002.* (added 03, 05, 08)
  '3002.01' = @{ Name='Comrpessor Outlet';      Unit='Bar';      Encoding='HiU16';          Calc='HiU16/1000' }
  '3002.03' = @{ Name='Element Outlet';                            Unit='°C';       Encoding='HiU16';          Calc='HiU16/10' }
  '3002.05' = @{ Name='Ambient Air Temperature';                            Unit='°C';       Encoding='HiU16';          Calc='HiU16/10' }
  '3002.08' = @{ Name='Controller Temperature';                            Unit='°C';       Encoding='HiU16';          Calc='HiU16/10' }
  '3002.24' = @{ Name='Compressor Outlet';           Unit='bar abs'; Encoding='HiU16';          Calc='HiU16/1000' }
  '3002.26' = @{ Name='Ambient Temperature';         Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }
  '3002.27' = @{ Name='Relative Humidity';           Unit='%';       Encoding='HiU16';          Calc='HiU16' }
  '3002.2A' = @{ Name='Element Outlet';              Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }
  '3002.66' = @{ Name='Aftercooler drain PCB Temp';  Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }

  # 3003.* (added 01, 02, 0A)
  '3003.01' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.02' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.0A' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }

  # 3007.* (added 14, 15, 18, 22, 23, 24)
  '3007.01' = @{ Name='Running Hours';                Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.03' = @{ Name='Motor Starts';                 Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.04' = @{ Name='Load Relay';                   Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.05' = @{ Name='VSD 1-20% RPM';                Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.06' = @{ Name='VSD 20-40% RPM';               Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.07' = @{ Name='VSD 40-60% RPM';               Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.08' = @{ Name='VSD 60-80% RPM';               Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.09' = @{ Name='VSD 80-100% RPM';              Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.0B' = @{ Name='Fan Starts';                   Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.0C' = @{ Name='Accumulated Volume';           Unit='m3';      Encoding='UInt32';         Calc='UInt32*1000' }
  '3007.0D' = @{ Name='Module Hours';                 Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.0E' = @{ Name='Emergency Stops';              Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.0F' = @{ Name='Direct Stops';                 Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.14' = @{ Name='Recirculation Starts';                            Unit='?';       Encoding='UInt32';         Calc='UInt32' }
  '3007.15' = @{ Name='Recirculation Failures';                            Unit='?';       Encoding='UInt32';         Calc='UInt32' }
  '3007.18' = @{ Name='?';       Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.22' = @{ Name='?';                            Unit='?';       Encoding='UInt32';         Calc='UInt32' }
  '3007.23' = @{ Name='?';                            Unit='?';       Encoding='UInt32';         Calc='UInt32' }
  '3007.24' = @{ Name='?';                            Unit='?';       Encoding='UInt32';         Calc='UInt32' }

  # 3021.* (with split)
  '3021.01-Hi' = @{ Name='Motor RPM (actual)';        Unit='RPM';     Encoding='HiU16';          Calc='HiU16' }
  '3021.01-Lo' = @{ Name='Motor RPM (requested)';     Unit='RPM';     Encoding='LoU16';          Calc='LoU16' }
  '3021.05'    = @{ Name='Flow';                      Unit='%';       Encoding='LoU16';          Calc='LoU16' }
  '3021.0A'    = @{ Name='Motor Ampere';              Unit='A';       Encoding='HiU16';          Calc='HiU16' }

  # 3005.* (new set here)
  '3005.01' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.02' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.04' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.05' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.07' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.08' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.09' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }

  # 300E.* (added 88)
  '300E.03' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.04' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.2A' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.88' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }

  # 3113.* (same broad block as before)
  '3113.01' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3113.03' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3113.04' = @{ Name='?'; Unit='?'; Encoding='LoU16';    Calc='LoU16' }
  # 05..46 generic UInt32
  '3113.05' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.07' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.08' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.09' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0A' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0B' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0C' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0D' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0E' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.0F' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.10' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.11' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.12' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.13' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.14' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.15' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.16' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.17' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.18' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.19' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1A' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1B' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1C' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1D' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1E' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.1F' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.20' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.21' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.22' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.23' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.24' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.25' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.26' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.27' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.28' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.29' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2A' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2B' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2C' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2D' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2E' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.2F' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.30' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.31' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.32' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.33' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.34' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.35' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.36' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.37' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.38' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.39' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3A' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3B' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3C' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3D' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3E' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.3F' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.40' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.41' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.42' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.43' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.44' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.45' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.46' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }

  # 3114.* (same handling)
  '3114.01' = @{ Name='?'; Unit='?'; Encoding='LoU16'; Calc='?' }
  '3114.02' = @{ Name='?'; Unit='?'; Encoding='LoU16'; Calc='?' }
  '3114.03' = @{ Name='?'; Unit='?'; Encoding='LoU16'; Calc='?' }
  '3114.04' = @{ Name='?'; Unit='?'; Encoding='LoU16'; Calc='?' }
  '3114.05' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.06' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.07' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.08' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.09' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0A' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0B' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0C' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0D' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0E' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.0F' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.10' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.11' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }
  '3114.12' = @{ Name='?'; Unit='?'; Encoding='?';     Calc='?' }

  # 3009.* (service plan groups + status)
  '3009.01' = @{ Name='?';            Unit='?';  Encoding='UInt32';         Calc='UInt32' }
  '3009.06' = @{ Name='Service_A_1';  Unit='h';  Encoding='UInt32';         Calc='UInt32/3600' }
  '3009.11' = @{ Name='Service_A_2';  Unit='h';  Encoding='UInt32';         Calc='UInt32/3600' }
  '3009.07' = @{ Name='Service_B_1';  Unit='h';  Encoding='UInt32';         Calc='UInt32/3600' }
  '3009.12' = @{ Name='Service_B_2';  Unit='h';  Encoding='UInt32';         Calc='UInt32/3600' }

  # status code (also present in this question)
  '3001.08' = @{ Name='Machine Status'; Unit='';  Encoding='UInt32'; Calc='UInt32' }
}

# --- helpers
function To-Int16Signed {
  param([Parameter(Mandatory)][UInt16]$U16)
  if ($U16 -ge 0x8000) { return [int]($U16 - 0x10000) } else { return [int]$U16 }
}

function Apply-Calc {
  param(
    [string]$calc,
    [uint32]$u32,
    [uint16]$hi,
    [uint16]$lo
  )
  switch -regex ($calc) {
    '^\s*HiU16/(\d+)\s*$'  { return [double]$hi / [double]$Matches[1] }
    '^\s*LoU16/(\d+)\s*$'  { return [double]$lo / [double]$Matches[1] }
    '^\s*HiU16\*(\d+)\s*$' { return [double]$hi * [double]$Matches[1] }
    '^\s*LoU16\*(\d+)\s*$' { return [double]$lo * [double]$Matches[1] }
    '^\s*HiU16\s*$'        { return [int]$hi }
    '^\s*LoU16\s*$'        { return [int]$lo }
    '^\s*UInt32/(\d+)\s*$' { return [double]$u32 / [double]$Matches[1] }
    '^\s*UInt32\*(\d+)\s*$'{ return [double]$u32 * [double]$Matches[1] }
    '^\s*UInt32\s*$'       { return [uint32]$u32 }
    '^\s*HiU16/LoU16\s*$'  { return ("{0}/{1}" -f $hi, $lo) }
    default                { return $null }
  }
}

# --- robust parser: strict 8-char blocks, safe X handling, alignment checks
function Parse-Values([string[]]$keys, [string]$answer, [hashtable]$meta) {
  $rows = New-Object System.Collections.Generic.List[object]
  $pos = 0
  $blockIndex = 0

  while ($pos -lt $answer.Length) {
    $hex8 = $answer.Substring($pos, [Math]::Min(8, $answer.Length - $pos))
    if ($hex8 -match '^[Xx]+$') {
      $rows.Add([pscustomobject]@{ Key="UNMAPPED.$blockIndex"; Name=''; Raw=$hex8; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=''; Calc=''; Value=$null; Unit=''; Int32=$null; HiI16=$null; LoI16=$null })
      $pos += $hex8.Length
      $blockIndex++
      continue
    }

    if ($hex8.Length -lt 8) { break }

    try {
      $u32 = [Convert]::ToUInt32($hex8, 16)
      $i32 = [BitConverter]::ToInt32(([BitConverter]::GetBytes($u32)),0)
      $hi  = [Convert]::ToUInt16($hex8.Substring(0,4), 16)
      $lo  = [Convert]::ToUInt16($hex8.Substring(4,4), 16)
      $hiI = To-Int16Signed $hi
      $loI = To-Int16Signed $lo

      # pick key if available, else synthesize
      $k = if ($blockIndex -lt $keys.Count) { $keys[$blockIndex] } else { "UNMAPPED.$blockIndex" }
      $m = $meta[$k]; if (-not $m) { $m = @{ Name=''; Unit=''; Encoding=''; Calc='' } }

      $val = Apply-Calc -calc $m.Calc -u32 $u32 -hi $hi -lo $lo
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw=$hex8; UInt32=$u32; LoU16=$lo; HiU16=$hi; Encoding=$m.Encoding; Calc=$m.Calc; Value=$val; Unit=$m.Unit; Int32=$i32; HiI16=$hiI; LoI16=$loI
      })
    } catch {
      $rows.Add([pscustomobject]@{ Key="UNMAPPED.$blockIndex"; Name=''; Raw=$hex8; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=''; Calc=''; Value=$null; Unit=''; Int32=$null; HiI16=$null; LoI16=$null })
    }

    $pos += 8
    $blockIndex++
  }

  return $rows
}



# --- discovery helpers: probe which keys actually return data on the target host
function Test-KeyBatch {
  param(
    [string[]]$Keys,
    [string]$Host,
    [int]$TimeoutSec = 5
  )
  $q = Build-QuestionHexFromKeys $Keys
  $ans = Get-Answer -TargetHost $Host -qHex $q -timeout $TimeoutSec
  $ans = ($ans -replace '\s','').ToUpper()
  $ok  = New-Object System.Collections.Generic.List[string]
  for ($i=0; $i -lt $Keys.Count; $i++) {
    $hex8 = if ($ans.Length -ge ($i+1)*8) { $ans.Substring($i*8, 8) } else { '' }
    if ($hex8 -match '^[0-9A-F]{8}$' -and $hex8 -notmatch '^X{8}$') { $ok.Add($Keys[$i]) }
  }
  ,@($ok.ToArray())
}

function Discover-WorkingKeys {
  param(
    [string[]]$AllKeys,
    [string]$Host,
    [int]$BatchSize = 32,
    [int]$TimeoutSec = 5
  )
  $good = New-Object System.Collections.Generic.List[string]
  for ($i=0; $i -lt $AllKeys.Count; $i += $BatchSize) {
    $j = [math]::Min($i+$BatchSize-1, $AllKeys.Count-1)
    $chunk = $AllKeys[$i..$j]
    $res = Test-KeyBatch -Keys $chunk -Host $Host -TimeoutSec $TimeoutSec
    $good.AddRange($res)
  }
  $qhex = Build-QuestionHexFromKeys $good
  Write-Host "Working keys: $($good.Count)/$($AllKeys.Count)"
  Write-Host "`nPaste this into `$QuestionHex:"
  Write-Host $qhex
  return ,@($good.ToArray())
}

# === main run ===
try {
  $keys = Expand-KeysFromQuestion $QuestionHex

  if ($Discover.IsPresent) {
    Write-Host "=== Discover mode ==="
    $working = Discover-WorkingKeys -AllKeys $keys -Host $ControllerHost -BatchSize $BatchSize -TimeoutSec $TimeoutSec
    return
  }

  $answer = Get-Answer -TargetHost $ControllerHost -qHex $QuestionHex -timeout $TimeoutSec

  "Question:"
  $QuestionHex
  ""
  "Answer:"
  $answer
  ""

  $values = Parse-Values -keys $keys -answer $answer -meta $Meta

  # VSD buckets → % of total running seconds (3007.01)
  $vsdKeys = @('3007.05','3007.06','3007.07','3007.08','3007.09')
  $totRow  = $values | Where-Object { $_.Key -eq '3007.01' }
  $totSec  = $totRow.UInt32
  if ($totSec -gt 0) {
    foreach ($k in $vsdKeys) {
      $row = $values | Where-Object { $_.Key -eq $k }
      if ($row -and $row.UInt32) {
        $pct = [math]::Round(($row.UInt32 / $totSec) * 100, 0)
        $row.Value    = $pct
        $row.Unit     = '%'
        $row.Encoding = 'UInt32 seconds (bucket)'
        $row.Calc     = 'UInt32 / 3007.01 × 100'
      }
    }
  }

  "`n=== All Keys (Value + Meta + raw codecs) ==="
  $values | Sort-Object Key | Format-Table -Property Key,Name,Raw,UInt32,LoU16,HiU16,Encoding,Calc,Value,Unit -AutoSize

} catch {
  Write-Error $_
}
