<!DOCTYPE html>
<html>
<head>
<title>Rate Limit</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body onload="initTableCss()">
<form method="post" action="rateLimit.cgi">
<table class="detailsAreaContainer">
<tr>
<td><table class="tableStyle">
<tr>
<script>tbhdrTable('Rate Control Setting','rateLimit')</script>
</tr>
<tr><td class="topTitleBottomBar" colspan="2"></td></tr>
<tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" id="tbl2" style='width:728px;'>
<tr><td class="def_TH spacer4Percent def_center"><input type="checkbox" name="checkALL" rownumber="" value="notchecked" onclick="checkAllCheckedRows('portID')" /></td>
    <td class="def_TH">Port</td><td class="def_TH">Ingress Rate</td><td class="def_TH">Egress Rate</td></tr>
<tr id="g_1_1" exclusive="">
<td class="def_TH def_center"></td>
<td class="def_TH" sel="text"></td>
<td class="def_TH" sel="select"><select name="IngressRate" disabled>
<option value="0">-</option>
<option value="1">No Limit</option>
<option value="2">512 Kbit/s</option>
<option value="3">1 Mbit/s</option>
<option value="4">2 Mbit/s</option>
<option value="5">4 Mbit/s</option>
<option value="6">8 Mbit/s</option>
<option value="7">16 Mbit/s</option>
<option value="8">32 Mbit/s</option>
<option value="9">64 Mbit/s</option>
<option value="10">128 Mbit/s</option>
<option value="11">256 Mbit/s</option>
<option value="12">512 Mbit/s</option>
</select>
</td>
<td class="def_TH" sel="select"><select name="EgressRate" disabled>
<option value="0">-</option>
<option value="1">No Limit</option>
<option value="2">512 Kbit/s</option>
<option value="3">1 Mbit/s</option>
<option value="4">2 Mbit/s</option>
<option value="5">4 Mbit/s</option>
<option value="6">8 Mbit/s</option>
<option value="7">16 Mbit/s</option>
<option value="8">32 Mbit/s</option>
<option value="9">64 Mbit/s</option>
<option value="10">128 Mbit/s</option>
<option value="11">256 Mbit/s</option>
<option value="12">512 Mbit/s</option>
</select>
</td>
</tr>
<tr class="portID"><td class="def firstCol def_center" sel="select"><input class="checkbox" type="checkbox" name="port1" rownumber="" value="checked" onclick="checkBoxOnclick();"></td>
<td class="def" sel="text">1
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<tr class="portID"><td class="def firstCol def_center" sel="select"><input class="checkbox" type="checkbox" name="port2" rownumber="" value="checked" onclick="checkBoxOnclick();"></td>
<td class="def" sel="text">2
<input type="hidden" value="2">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<tr class="portID"><td class="def firstCol def_center" sel="select"><input class="checkbox" type="checkbox" name="port3" rownumber="" value="checked" onclick="checkBoxOnclick();"></td>
<td class="def" sel="text">3
<input type="hidden" value="3">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<tr class="portID"><td class="def firstCol def_center" sel="select"><input class="checkbox" type="checkbox" name="port4" rownumber="" value="checked" onclick="checkBoxOnclick();"></td>
<td class="def" sel="text">4
<input type="hidden" value="4">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<tr class="portID"><td class="def firstCol def_center" sel="select"><input class="checkbox" type="checkbox" name="port5" rownumber="" value="checked" onclick="checkBoxOnclick();"></td>
<td class="def" sel="text">5
<input type="hidden" value="5">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<td class="def" sel="select">No Limit
<input type="hidden" value="1">
</td>
<input type=hidden name='hash' id='hash' value="12345">
</tr>
</table>
</td></tr>
</table>
</td></tr>
</form>
<script>
var str = CreateButtons('button','Cancel','javaScript:void(0)','btn_Cancel','off');
str += CreateButtons('button','Apply','javaScript:void(0)','btn_Apply','off');
PaintButtons(str);
</script>
</body>
</html>
