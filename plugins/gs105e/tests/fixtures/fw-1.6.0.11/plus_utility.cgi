<!DOCTYPE html>
<html>
<head>
<title>Plus Utility Management</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script  src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script  src="/function.js?a1.6.0.11" type="text/javascript"></script>
</head>

<body>
<form method="post" action="plus_utility.cgi">
<table class="detailsAreaContainer">
<tr>
<td><table class="tableStyle">
<tr>
<script>tbhdrTable('Switch Management Mode','plusUtility')</script>
</tr>
<tr><td class="topTitleBottomBar" colspan="2"></td></tr>
     <tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" style="width:728px;">
      <tr>
       <td class="def firstCol" width="350">Switch Management Mode</td>
       <td class="def firstCol" nowrap=""><input class="radioStyle" type="radio" value="1" name="plusUtility" onclick="enableImage();" checked/><span>Web browser only</span></td>
       <td class="def firstCol" nowrap=""><input class="radioStyle" type="radio" value="0" name="plusUtility" onclick="enableImage();" /><span>Web browser and Plus Utility</span></td>
      </tr>
<input type=hidden name='hash' id='hash' value="12345">
      </table>
      <p style="margin-top:15px; margin-bottom:20px;padding-left:7px;">
      Note: If you choose the web browser only, you will no longer be able to manage the switch using the Plus Utility.
      </p>
     </td></tr>
     <tr><td class="paddingTableBody" colspan="2"><table class="tableStyle" style="width:728px;">
      <tr>
       <td class="def firstCol" width="350">File Transfer via Plus Utility (TFTP)</td>
       <td class="def firstCol" nowrap=""><input class="radioStyle" type="radio" value="1" name="tftpflag" onclick="enableImage();" checked/><span>Disable</span></td>
       <td class="def firstCol" nowrap=""><input class="radioStyle" type="radio" value="0" name="tftpflag" onclick="enableImage();" /><span>Enable</span></td>
      </tr>
      </table>
     </td></tr>
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
