<html>
<head>
<title>System Information</title>
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body>
<form method="get" action="info.cgi">
<table class="detailsAreaContainer">

<tr>
<td><table class="tableStyle" style='width:728px;'>
<tr>
<script>tbhdrTable('Switch Status','systemInformation')</script>
 </tr><tr><td class="topTitleBottomBar" colspan='2'></td></tr>
<tr><td class="paddingsubSectionBodyNone" colspan='2'><table class="tableStyle" id="tbl2">
  <tr>
    <td class="font11" width='300'>MAC Address</td>
    <td class="font11" align="center" nowrap>02:00:00:00:00:01</td>
  </tr>
  <tr>
    <td class="font11 padding14Top">IP Address</td>
    <td class="font11 margin25Left" align="center" nowrap>192.0.2.1</td>
  </tr>
  <tr>
    <td class="font11 padding14Top">Netmask</td>
    <td class="font11 margin25Left" align="center" nowrap>255.255.255.0</td>
  </tr>
  <tr>
    <td class="font11 padding14Top">Gateway</td>
    <td class="font11 margin25Left" align="center" nowrap>192.0.2.2</td>
  </tr>
  <tr>
    <td class="font11 padding14Top">Firmware Version</td>
    <td class="font11 margin25Left" align="center" nowrap>V1.6.0.11</td>
  </tr>
</table>
</td>
</tr>
</table>
</td></tr>
</table>
</form>
<script>
var str = CreateButtons('button','Refresh','submitForm()','btn_Refresh','on');
PaintButtons(str);
</script>
</body>
</html>
