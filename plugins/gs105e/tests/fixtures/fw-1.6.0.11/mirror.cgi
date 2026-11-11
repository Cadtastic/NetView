<!DOCTYPE html>
<html>
<head>
<title>Port Mirroring</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body onload="initMemberAndMirror('Mirroring'); initErrMsg();">
<form method="post" action="mirror.cgi">
<table class="detailsAreaContainer">
<tr>
<td><table class="tableStyle">
<tr>
<script>tbhdrTable('Port Mirroring Configuration','portMirroring')</script>
</tr>
<tr><td class="topTitleBottomBar" colspan="2"></td></tr>
<tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" id="tbl1" style="width:728px;">
<tr class="trBgColor"><td class='border_bottom'><div class="right_th"><label>Mirroring</label>
<select id='mirroring' name="mirroring">
<option value="0">Enable</option>
<option value="1" selected>Disable</option></select>
<label>Destination Port</label>
<select id='DestiPort' name="select"><option value="0">&nbsp;</option>
    <option value='1'>1</option>
    <option value='2'>2</option>
    <option value='3'>3</option>
    <option value='4'>4</option>
    <option value='5'>5</option>
</select></div></td></tr>
<tr class="trBgColor"><td><span class="left_th">Source Port</span></td></tr>
<tr class="">
  <td class="borderRight textCenter" id="unit1" style="padding-top:10px">
  	<span class="ports">Ports</span>
  	<div class="portMember margin"><span class="portword font12">1</span><div class="panels"><div class="portImage"></div></div></div>
  	<div class="portMember margin"><span class="portword font12">2</span><div class="panels"><div class="portImage"></div></div></div>
  	<div class="portMember margin"><span class="portword font12">3</span><div class="panels"><div class="portImage"></div></div></div>
  	<div class="portMember margin"><span class="portword font12">4</span><div class="panels"><div class="portImage"></div></div></div>
  	<div class="portMember"><span class="portword font12">5</span><div class="panels"><div class="portImage"></div></div></div>
  </td>
  </tr>
<input type=hidden name='hash' id='hash' value="12345">
</table>
</td></tr>
</table>
</td></tr>
</table>
</td></tr>
<input name="hiddenMem" id="hiddenMem" size="2700" maxlength="2699" value="00000" type="hidden">
<input type=hidden name='err_msg' id='err_msg' value='' disabled>
</form>
<script>
var str = CreateButtons('button','Cancel','javaScript:void(0)','btn_Cancel','off');
str += CreateButtons('button','Apply','javaScript:void(0)','btn_Apply','off');
PaintButtons(str);
</script>
</body>
</html>
