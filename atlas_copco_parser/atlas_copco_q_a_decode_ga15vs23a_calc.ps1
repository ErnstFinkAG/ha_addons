param(
  [string]$ControllerHost = '10.60.23.12',
  [int]$TimeoutSec = 5
)

# === QUESTION (paste your hex; whitespace OK) ===
$QuestionHex = @'
30020130022430022630022730022a30026630032130032230032e30032f30033030070130070330070430070530070630070730070830070930070b30070c30070d30070e30070f30071730071830071b30072530072630072730074330074c30074d30075430075530075630075730210130210530210a30220130220a30051f30052030052130052730052830052930052a300e03300e04300e05300e2a300ef3310e23310e27310e2b310e3b31130131130331130431130531130731130831130931130a31130b31130c31130d31130e31130f31131031131131131231131331131431131531131631131731131831131931131a31131b31131c31131d31131e31131f31132031132131132231132331132431132531132631132731132831132931132a31132b31132c31132d31132e31132f31133031133131133231133331133431133531133631133731133831133931133a31133b31133c31133d31133e31133f31134031134131134231134331134431134531134631134731134831134931134a31134b31134c31134d31134e31134f31135031135131135231135331135431135531135631135731135831135931135a31135b31135c31135d31135e31135f31136031136131136231136331136431136531136631136731140131140231140331140431140531140631140731140831140931140a31140b31140c31140d31140e31140f311410311411311412300901300906300911300907300912300909300914300108
'@ -replace '\s',''

function Expand-KeysFromQuestion([string]$qHex) {
  $keys = New-Object System.Collections.Generic.List[string]
  for ($i = 0; $i -lt $qHex.Length; $i += 6) {
    $idx = $qHex.Substring($i, 4).ToUpper()
    $si  = $qHex.Substring($i + 4, 2).ToUpper()
    $keys.Add("$idx.$si")
  }
  $keys
}

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
  '3002.01' = @{ Name='Controller Temperature';            Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }
  '3002.24' = @{ Name='Compressor Outlet';                 Unit='bar abs'; Encoding='HiU16';          Calc='HiU16/1000' }
  '3002.26' = @{ Name='Ambient Temperature';               Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }
  '3002.27' = @{ Name='Relative Humidity';                 Unit='%';       Encoding='HiU16';          Calc='HiU16' }
  '3002.2A' = @{ Name='Element Outlet';                    Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }
  '3002.66' = @{ Name='Aftercooler drain PCB Temperature'; Unit='°C';      Encoding='HiU16';          Calc='HiU16/10' }

  '3003.21' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.22' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.2E' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.2F' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }
  '3003.30' = @{ Name='?'; Unit='?'; Encoding='?'; Calc='?' }

  '3007.01' = @{ Name='Running Hours';                     Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.03' = @{ Name='Motor Starts';                      Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.04' = @{ Name='Load Relay';                        Unit='count';   Encoding='UInt32';         Calc='UInt32' }

  # VSD buckets (we convert to % after parsing using 3007.01 total seconds)
  '3007.05' = @{ Name='VSD 1-20% RPM';                     Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.06' = @{ Name='VSD 20-40% RPM';                    Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.07' = @{ Name='VSD 40-60% RPM';                    Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.08' = @{ Name='VSD 60-80% RPM';                    Unit='%';       Encoding='UInt32';         Calc='UInt32' }
  '3007.09' = @{ Name='VSD 80-100% RPM';                   Unit='%';       Encoding='UInt32';         Calc='UInt32' }

  '3007.0B' = @{ Name='Fan Starts'; Unit='count'; Encoding='UInt32'; Calc='UInt32' }
  '3007.0C' = @{ Name='Accumulated Volume'; Unit='m3'; Encoding='UInt32'; Calc='UInt32*1000' }
  '3007.0D' = @{ Name='Module Hours';                      Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.0E' = @{ Name='Emergency Stops';                   Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.0F' = @{ Name='Direct Stops';                      Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.17' = @{ Name='Recirculation Starts';              Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.18' = @{ Name='Recirculation Failures';            Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.1B' = @{ Name='Low Load Hours';                    Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.25' = @{ Name='Available Hours';                   Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.26' = @{ Name='Unavailable Hours';                 Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.27' = @{ Name='Emergency Stop Hours';              Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.43' = @{ Name='Display Hours';                     Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.4C' = @{ Name='Boostflow Hours';                   Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.4D' = @{ Name='Boostflow Activations';             Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.54' = @{ Name='Emergency Stops During Running';    Unit='count';   Encoding='UInt32';         Calc='UInt32' }
  '3007.55' = @{ Name='Drain 1 Operation Time';            Unit='h';       Encoding='UInt32 seconds'; Calc='UInt32/3600' }
  '3007.56' = @{ Name='Drain 1 number of switching actions'; Unit='count'; Encoding='UInt32';         Calc='UInt32' }
  '3007.57' = @{ Name='Drain 1 number of manual drainings';  Unit='count'; Encoding='UInt32';         Calc='UInt32' }

  # 3021.01 split into two outputs
  '3021.01-Hi' = @{ Name='Motor RPM (actual)';    Unit='RPM'; Encoding='HiU16'; Calc='HiU16' }
  '3021.01-Lo' = @{ Name='Motor RPM (requested)'; Unit='RPM'; Encoding='LoU16'; Calc='LoU16' }

  '3021.05' = @{ Name='Flow';           Unit='%';  Encoding='LoU16'; Calc='LoU16' }
  '3021.0A' = @{ Name='Motor Ampere';   Unit='A';  Encoding='HiU16'; Calc='HiU16' }

  '3022.01' = @{ Name='FAN RPM';        Unit='RPM'; Encoding='HiU16'; Calc='HiU16' }
  '3022.0A' = @{ Name='FAN Ampere';     Unit='A';   Encoding='HiU16'; Calc='HiU16' }

  '3005.1F' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.20' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.21' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.27' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.28' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.29' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3005.2A' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }

  '300E.03' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.04' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.05' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.2A' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '300E.F3' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }

  '310E.23' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '310E.27' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '310E.2B' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '310E.3B' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }

  '3113.01' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3113.03' = @{ Name='?'; Unit='?'; Encoding='U16 pair'; Calc='?' }
  '3113.04' = @{ Name='?'; Unit='?'; Encoding='LoU16';    Calc='LoU16' }

  # 3113.05..3113.46 generic
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

  '3113.47' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.48' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.49' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4A' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4B' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4C' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4D' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4E' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.4F' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.50' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.51' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.52' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.53' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.54' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.55' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.56' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.57' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.58' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.59' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5A' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5B' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5C' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5D' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5E' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.5F' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.60' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.61' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }
  '3113.62' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }

  '3113.63' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.64' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.65' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3113.66' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }

  '3113.67' = @{ Name='?'; Unit='?'; Encoding='X'; Calc='X' }

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

  '3009.01' = @{ Name='?'; Unit='?'; Encoding='UInt32'; Calc='UInt32' }
  '3009.06' = @{ Name='Service_A_1'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3009.11' = @{ Name='Service_A_2'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3009.07' = @{ Name='Service_B_1'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3009.12' = @{ Name='Service_B_2'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3009.09' = @{ Name='Service_D_1'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }
  '3009.14' = @{ Name='Service_D_2'; Unit='h'; Encoding='UInt32'; Calc='UInt32/3600' }

  '3001.08' = @{ Name='Machine Status'; Unit='';  Encoding='UInt32'; Calc='UInt32' } # status code
}

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
    '^\s*HiU16/(\d+)\s*$' { return [double]$hi / [double]$Matches[1] }
    '^\s*LoU16/(\d+)\s*$' { return [double]$lo / [double]$Matches[1] }
    '^\s*HiU16\*(\d+)\s*$'{ return [double]$hi * [double]$Matches[1] }
    '^\s*LoU16\*(\d+)\s*$'{ return [double]$lo * [double]$Matches[1] }
    '^\s*HiU16\s*$'       { return [int]$hi }
    '^\s*LoU16\s*$'       { return [int]$lo }
    '^\s*UInt32/(\d+)\s*$'{ return [double]$u32 / [double]$Matches[1] }
    '^\s*UInt32\*(\d+)\s*$'{ return [double]$u32 * [double]$Matches[1] }
    '^\s*UInt32\s*$'      { return [uint32]$u32 }
    '^\s*HiU16/LoU16\s*$' { return ("{0}/{1}" -f $hi, $lo) }
    default               { return $null }
  }
}

function Parse-Values([string[]]$keys, [string]$answer, [hashtable]$meta) {
  $pos = 0
  $rows = New-Object System.Collections.Generic.List[object]
  foreach ($k in $keys) {
    # Get meta with safe defaults
    $m = $meta[$k]
    if (-not $m) { $m = @{ Name=''; Unit=''; Encoding=''; Calc='' } }

    # Exhausted or X handling
    if ($pos -ge $answer.Length) {
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw=$null; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=$m.Encoding; Calc=$m.Calc; Value=$null; Unit=$m.Unit; Int32=$null; HiI16=$null; LoI16=$null
      })
      continue
    }
    if ($answer[$pos] -eq 'X') {
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw='X'; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=$m.Encoding; Calc=$m.Calc; Value=$null; Unit=$m.Unit; Int32=$null; HiI16=$null; LoI16=$null
      })
      $pos += 1
      continue
    }

    $hex8 = $answer.Substring($pos, [Math]::Min(8, $answer.Length - $pos))
    if ($hex8.Length -lt 8) {
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw=$hex8; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=$m.Encoding; Calc=$m.Calc; Value=$null; Unit=$m.Unit; Int32=$null; HiI16=$null; LoI16=$null
      })
      $pos += $hex8.Length
      continue
    }

    try {
      $u32 = [Convert]::ToUInt32($hex8, 16)
      $i32 = [BitConverter]::ToInt32(([BitConverter]::GetBytes($u32)),0)
      $hi  = [Convert]::ToUInt16($hex8.Substring(0,4), 16)
      $lo  = [Convert]::ToUInt16($hex8.Substring(4,4), 16)
      $hiI = To-Int16Signed $hi
      $loI = To-Int16Signed $lo

      # Fan-out if key is split (e.g., 3021.01 -> 3021.01-Hi / 3021.01-Lo)
      if ($SplitKeys.ContainsKey($k)) {
        foreach ($aliasKey in $SplitKeys[$k]) {
          $m2 = $meta[$aliasKey]; if (-not $m2) { $m2 = @{ Name=''; Unit=''; Encoding=''; Calc='' } }
          $val2 = Apply-Calc -calc $m2.Calc -u32 $u32 -hi $hi -lo $lo
          $rows.Add([pscustomobject]@{
            Key=$aliasKey; Name=$m2.Name; Raw=$hex8; UInt32=$u32; LoU16=$lo; HiU16=$hi; Encoding=$m2.Encoding; Calc=$m2.Calc; Value=$val2; Unit=$m2.Unit; Int32=$i32; HiI16=$hiI; LoI16=$loI
          })
        }
        $pos += 8
        continue
      }

      $val = Apply-Calc -calc $m.Calc -u32 $u32 -hi $hi -lo $lo
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw=$hex8; UInt32=$u32; LoU16=$lo; HiU16=$hi; Encoding=$m.Encoding; Calc=$m.Calc; Value=$val; Unit=$m.Unit; Int32=$i32; HiI16=$hiI; LoI16=$loI
      })
    } catch {
      $rows.Add([pscustomobject]@{
        Key=$k; Name=$m.Name; Raw=$hex8; UInt32=$null; LoU16=$null; HiU16=$null; Encoding=$m.Encoding; Calc=$m.Calc; Value=$null; Unit=$m.Unit; Int32=$null; HiI16=$null; LoI16=$null
      })
    }

    $pos += 8
  }
  $rows
}


# === run ===
$keys   = Expand-KeysFromQuestion $QuestionHex
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
    if ($row) {
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
