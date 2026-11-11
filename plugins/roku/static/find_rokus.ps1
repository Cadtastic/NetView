# Finds Roku devices on this network and prints them as JSON (also copied to the clipboard).
Add-Type -AssemblyName System.Net.Http
$found = [ordered]@{}
# 1. Start checking port 8060 on every address in this computer's /24.
$me = @((Get-NetIPConfiguration | Where-Object IPv4DefaultGateway | Select-Object -First 1).IPv4Address.IPAddress)[0]
$net = $me -replace '\.\d+$', ''
$http = New-Object Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(3)
$jobs = 1..254 | ForEach-Object { $a = "$net.$_"; [pscustomobject]@{ ip = $a; task = $http.GetAsync(('http://{0}:8060/query/device-info' -f $a)) } }
# 2. Meanwhile, ask Rokus to announce themselves over SSDP (finds them outside this /24 too).
$u = New-Object Net.Sockets.UdpClient
$u.Client.ReceiveTimeout = 2000
$msg = "M-SEARCH * HTTP/1.1`r`nHost: 239.255.255.250:1900`r`nMan: `"ssdp:discover`"`r`nMX: 2`r`nST: roku:ecp`r`n`r`n"
$b = [Text.Encoding]::ASCII.GetBytes($msg)
[void]$u.Send($b, $b.Length, '239.255.255.250', 1900)
$ep = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
try { while ($true) { $r = [Text.Encoding]::ASCII.GetString($u.Receive([ref]$ep)); if ($r -match 'LOCATION:\s*http://([\d.]+):8060') { $found[$Matches[1]] = $true } } } catch {} finally { $u.Close() }
try { [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]$jobs.task) } catch {}
$jobs | Where-Object { $_.task.Status -eq 'RanToCompletion' } | ForEach-Object { $found[$_.ip] = $true }
# 3. Read each device's details.
function Get-Field($d, $n) { $v = $d.$n; if ($v -is [string]) { $v } else { '' } }
$tvs = foreach ($a in $found.Keys) {
  try {
    $d = ([xml](Invoke-WebRequest "http://$($a):8060/query/device-info" -TimeoutSec 3 -UseBasicParsing).Content).'device-info'
    $name = 'user-device-name', 'friendly-device-name', 'default-device-name' | ForEach-Object { Get-Field $d $_ } | Where-Object { $_ } | Select-Object -First 1
    [pscustomobject]@{ ip = $a; name = $name; model = Get-Field $d 'model-name'; location = Get-Field $d 'user-device-location'; tv = ((Get-Field $d 'is-tv') -eq 'true'); mode = Get-Field $d 'ecp-setting-mode'; power = Get-Field $d 'power-mode' }
  } catch {}
}
$json = ConvertTo-Json -InputObject @($tvs) -Compress
$json
try { $json | Set-Clipboard -ErrorAction Stop; Write-Host 'Copied to the clipboard.' -ForegroundColor Green } catch {}
