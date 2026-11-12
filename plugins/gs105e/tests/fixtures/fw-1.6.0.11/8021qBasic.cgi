<!DOCTYPE html>
<html>
<head>
<title>Basic 802.1Q VLAN Status</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<meta name="format-detection" content="telephone=no,email=no,address=no">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>
<body onload="initRadioCtrlPage('basicVlan'); initErrMsg('802.1Q');">
<form method="post" action="8021qBasic.cgi">
<table class="detailsAreaContainer">
<tr>
<td><table class="tableStyle">
<tr>
<script>tbhdrTable('Basic 802.1Q VLAN Status','basic8021qVlanStatus')</script>
</tr>
<tr><td class="topTitleBottomBar" colspan="2"></td></tr>
<tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" id="tbl1" style='width:728px;'> 
<tr>
<td class='def firstCol' nowrap=''>Basic 802.1Q VLAN Status</td>
<td class='def firstCol' nowrap=''><input class='radioStyle' type='radio' value='Disable' name='status' checked/><span>Disable</span></td>
<td class='def firstCol' nowrap=''><input class='radioStyle' type='radio' value='Enable' name='status' /><span>Enable</span></td>
</tr>
</table>
</td></tr>
</table>
</td></tr>
<input type=hidden name='hash' id='hash' value="12345">
<input type=hidden name='err_msg' id='err_msg' value='' disabled>
</form>
<script>
var str = CreateButtons('button','Cancel','javaScript:void(0)','btn_Cancel','off');
str += CreateButtons('button','Apply','javaScript:void(0)','btn_Apply','off');
PaintButtons(str);
</script>
</body>
</html>
