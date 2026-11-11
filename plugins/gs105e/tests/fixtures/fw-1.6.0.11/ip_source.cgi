<!DOCTYPE html>
<html>
<head>
<title>Access Control</title>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<meta name="format-detection" content="telephone=no,email=no,address=no">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body onload="initTableCss();initErrMsg('Access Control');">
<form method="post" action="ip_source.cgi">
 <table class="detailsAreaContainer">
  <tr>
   <td>
    <table class="tableStyle">
     <tr><script>tbhdrTable('Access Control','ipSource')</script></tr>
     <tr><td class="topTitleBottomBar" colspan='2'></td></tr>
<tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" id="tbl2" style='width:728px;'>
<tr><td class="def_TH def_center"></td>
<td class="def_TH">Source IP Address</td>
<td class="def_TH">Mask</td></tr>
<tr id="g_1_1" exclusive="">
<td class="def_TH spacer4Percent def_center"><input type="checkbox" name="checkALL" rownumber="" value="notchecked" onclick="checkAllCheckedRows('index')" /></td>
<td class="def_TH" sel="input"><input type="text" name="IPADDRESS" maxlength="32" style="padding: 0px; height: 17px" onfocus="enableIPAuthMgrButtons()" onkeypress="enableIPAuthMgrButtons()" onmousedown="enableIPAuthMgrButtons()" /></td>
<td class="def_TH" sel="input"><input type="text" name="NETMASK" maxlength="32" style="padding: 0px; height: 17px" onfocus="enableIPAuthMgrButtons()" onkeypress="enableIPAuthMgrButtons()" onmousedown="enableIPAuthMgrButtons()"></td>
</tr>
<input type=hidden name='err_msg' id='err_msg' value='' disabled>
</table>
</td>
</tr>
</table>
<input type=hidden name='hash' id='hash' value="12345">
<input name="ACTION" id="ACTION" value="" type="hidden">
</form>
<script>
var str = CreateButtons('button','Add','javaScript:void(0)','btn_Add','off');
str += CreateButtons('button','Delete','javaScript:void(0)','btn_Delete','off');
str += CreateButtons('button','Cancel','javaScript:void(0)','btn_Cancel','off');
PaintButtons(str);
</script>
</body>
</html>
