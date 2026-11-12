<!DOCTYPE html>
<html>
<head>
<title>Qos Global Configuration</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body onload="initTableCss();initRadioCtrlPage('qos');">
<form method="post" action="qos.cgi">
 <table class="detailsAreaContainer">
  <tr>
   <td>
    <table class="tableStyle">
     <tr><script>tbhdrTable('Quality of Service','QosGlobalConfQos')</script></tr>
     <tr><td class="topTitleBottomBar" colspan="2"></td></tr>
     <tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" style="width:728px;">
      <td class="def firstCol" width="350px">QoS Mode</td>
      <td class="def firstCol" width="150px" nowrap=""><input class="radioStyle" type="radio" value="Disable" name="status"/><span>Port-Based</span></td>
      <td class="def firstCol" width="150px" nowrap=""><input class="radioStyle" type="radio" value="Enable" name="status" checked/><span>802.1p/DSCP-based</span></td>
      </table></td>
     </tr>
<input type=hidden name='hash' id='hash' value="12345">
    </table>
   </td>
  </tr>
 </table>
</form>
<script>
var str = CreateButtons('button','Cancel','javaScript:void(0)','btn_Cancel','off');
str += CreateButtons('button','Apply','javaScript:void(0)','btn_Apply','off');
PaintButtons(str);
</script>
</body>
</html>
