<!DOCTYPE html>
<head>
<title>IGMP Snooping</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
<link rel="stylesheet" type="text/css" href="/style.css?a1.6.0.11">
<script src="/frame.js?a1.6.0.11" type="text/javascript"></script>
<script src="/function.js?a1.6.0.11" type="text/javascript"></script>
<script language="JavaScript">
function statusDisableOnClick()
{
    document.forms[0].elements.VLAN_ID_ENABLED.disabled = true;
    document.forms[0].elements.VLAN_ID_ENABLED.value = "";
    document.forms[0].elements.ROUTER_PORT.disabled = true;
    document.forms[0].elements.ROUTER_PORT.options[0].selected = true;
}
function statusEnableOnClick()
{
    var elts = document.getElementById("inputVLANID");
    if (elts)
    {
        if (elts.innerHTML == null)
        {
            document.forms[0].elements.VLAN_ID_ENABLED.disabled = true;
            document.forms[0].elements.VLAN_ID_ENABLED.value = "";
        }
        else
        {
            document.forms[0].elements.VLAN_ID_ENABLED.disabled = false;
        }
    }
    document.forms[0].elements.ROUTER_PORT.disabled = false;
}
</script>
</head>
<body onload="initErrMsg('IGMP Snooping Configuration');">
<form method="post" action="/igmp.cgi">
<table class="detailsAreaContainer">
 <tr>
  <td><table class="tableStyle">
   <tr>
   <script>tbhdrTable('IGMP Snooping Configuration','igmpSnoopingConf')</script>
   </tr>
   <tr><td class="topTitleBottomBar" colspan='2'></td></tr>
   <tr><td class="paddingTableBody" colspan='2'><table class="tableStyle" style="width:728px;">
 <tr>
  <td class="spacer50Percent padding14Top">IGMP Snooping Status</td>
  <td class="spacer30Percent" align="center" nowrap>
   <input class="radioStyle" type="radio" value='0' name="status" onclick="enableImage();statusDisableOnClick();" />Disable
  </td>  <td align="center" nowrap>
   <input class="radioStyle" type="radio" value='1' name="status" onclick="enableImage();statusEnableOnClick();" checked/>Enable
 </tr>
 <tr>
  <td class="padding14Top">VLAN ID Enabled for IGMP Snooping</td>
  <td align="center" nowrap>
<input type="text" name="VLAN_ID_ENABLED" size="10" value="" disabled/>
  </td>
 </tr>
 <tr>
  <td class="padding14Top">Validate IGMPv3 IP Header</td>
  <td align="center" nowrap>
   <input class="radioStyle" type="radio" value='0' name="IP_HEADER" onclick="enableImage();" checked/>Disable
  </td>
  <td  align="center" nowrap>
   <input class="radioStyle" type="radio" value='1' name="IP_HEADER" onclick="enableImage();" />Enable
  </td>
 </tr>
 <tr>
  <td class="padding14Top">Block Unknown Multicast Address</td>
  <td align="center" nowrap>
   <input class="radioStyle" type="radio" value='0' name="BLOCK_UN_MUL_ADDR" onclick="enableImage();" checked/>Disable
  </td>
  <td align="center" nowrap>
   <input class="radioStyle" type="radio" value='1' name="BLOCK_UN_MUL_ADDR" onclick="enableImage();" />Enable
  </td>
 </tr>
 <tr>
  <td class="padding14Top">IGMP Snooping Static Router Port</td>
  <td align="center" nowrap>
   <select name="ROUTER_PORT" onchange="enableImage();" >
    <option value='0' ></option>
    <option value='1'>1</option>
    <option value='2'>2</option>
    <option value='3'>3</option>
    <option value='4'>4</option>
    <option value='5'>5</option>
    <option value='any'>Any</option>
   </select>
  </td>
 </tr>
<input type=hidden name='hash' id='hash' value="12345">
<input type=hidden name='err_msg' id='err_msg' value='' disabled>
</table>
</td>
</tr>
</table>
</form>
<script>
var str = CreateButtons('button','Cancel','cancelForm()','btn_Cancel','off');
str += CreateButtons('button','Apply','submitForm()','btn_Apply','off');
PaintButtons(str);
</script>
</body>
</html>
