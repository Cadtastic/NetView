// The ECP cheat sheet's data (docs/superpowers/reference/roku-ecp-cheat-sheet.html), content verbatim.
// RECIPES entries that read one XML field carry read: [path, tag]; the others carry m and p.
export const READ = [
  { m: "GET", p: "/", d: "UPnP device description. A quick check that the TV answers on 8060." },
  { m: "GET", p: "/query/device-info", d: "Model, software version, network, power-mode, uptime, and the ECP setting (ecp-setting-mode).", ok: true },
  { m: "GET", p: "/query/active-app", d: "The app on screen, plus the screensaver if one is running.", ok: true },
  { m: "GET", p: "/query/apps", d: "Installed channels with their IDs and versions. This is where appId values come from.", blocked: true },
  { m: "GET", p: "/query/icon/{appId}", ex: "/query/icon/2285", d: "A channel's icon image, saved to a file.", out: "icon.png" },
  { m: "GET", p: "/query/media-player", d: "Player state (play, pause, buffer, close) with position and duration in milliseconds.", blocked: true },
  { m: "GET", p: "/query/tv-channels", d: "Antenna channel list from the last channel scan.", tv: true },
  { m: "GET", p: "/query/tv-active-channel", d: "Current antenna channel, signal strength and program info.", tv: true },
];

export const CONTROL = [
  { m: "POST", p: "/keypress/{key}", ex: "/keypress/Home", d: "Press and release a remote button. Key names are listed below.", blocked: true },
  { m: "POST", p: "/keydown/{key}", ex: "/keydown/Right", d: "Hold a button down, for fast scrolling or hold-to-seek." },
  { m: "POST", p: "/keyup/{key}", ex: "/keyup/Right", d: "Release a held button. Always pair with keydown." },
  { m: "POST", p: "/launch/{appId}", ex: "/launch/12", d: "Open a channel, or bring it to the front if it is already running." },
  { m: "POST", p: "/launch/{appId}?contentId={id}&mediaType={type}", ex: "/launch/12?contentId=80057281&mediaType=series", d: "Deep link into a title. mediaType is movie, episode, season, series, shortFormVideo, tvSpecial or live. Each channel defines its own contentId format." },
  { m: "POST", p: "/launch/tvinput.{input}", ex: "/launch/tvinput.hdmi1", d: "Switch input: tvinput.hdmi1 to hdmi4, tvinput.dtv for the antenna tuner, tvinput.cvbs for AV.", tv: true },
  { m: "POST", p: "/install/{appId}", ex: "/install/12", d: "Open the channel store page for an app that isn't installed yet." },
  { m: "POST", p: "/search/browse?keyword={text}", ex: "/search/browse?keyword=star%20trek", d: "Open Roku search with results. Optional: &type=movie, tv-show, person, channel or game; &provider-id={appId}; &launch=true to play the first match." },
  { m: "POST", p: "/input?{name}={value}", ex: "/input?cmd=refresh", d: "Send parameters to the running channel. Only does something if that channel listens for it." },
];

export const KEYS = [
  { g: "Navigation", k: ["Home", "Back", "Up", "Down", "Left", "Right", "Select", "Info", "InstantReplay", "Search"] },
  { g: "Playback", k: ["Play", "Rev", "Fwd"], n: "Play toggles play and pause." },
  { g: "Volume", k: ["VolumeUp", "VolumeDown", "VolumeMute"], n: "TV speakers, or a soundbar over HDMI-CEC." },
  { g: "Power", k: ["PowerOff", "PowerOn", "Power"], tv: true, n: "Power toggles. PowerOn works from standby." },
  { g: "Inputs", k: ["InputTuner", "InputHDMI1", "InputHDMI2", "InputHDMI3", "InputHDMI4", "InputAV1"], tv: true },
  { g: "Antenna channels", k: ["ChannelUp", "ChannelDown"], tv: true },
  { g: "Text entry", k: ["Backspace", "Enter", "Lit_a"], n: "Lit_ plus one URL-encoded character types it. Use the text box below for whole words." },
  { g: "Other", k: ["FindRemote"], n: "Makes a compatible remote beep. Check find-remote-is-possible in device-info." },
];

export const APPS = [
  ["Netflix", "12"], ["YouTube", "837"], ["Prime Video", "13"], ["Hulu", "2285"], ["Disney+", "291097"],
  ["Max", "61322"], ["Peacock", "593099"], ["Paramount+", "31440"], ["Apple TV", "551012"],
  ["The Roku Channel", "151908"], ["Tubi", "41468"], ["Pluto TV", "74519"], ["Plex", "13535"], ["Spotify", "22297"],
  ["Antenna TV (input)", "tvinput.dtv"], ["HDMI 1 (input)", "tvinput.hdmi1"],
];

export const RECIPES = [
  { t: "Is the TV on?", read: ["/query/device-info", "power-mode"] },
  { t: "What's on screen?", read: ["/query/active-app", "app"] },
  { t: "Turn the TV off", m: "POST", p: "/keypress/PowerOff" },
  { t: "Turn the TV on", m: "POST", p: "/keypress/PowerOn" },
  { t: "Switch to HDMI 1", m: "POST", p: "/keypress/InputHDMI1" },
  { t: "Open YouTube", m: "POST", p: "/launch/837" },
  { t: "Check the Network access mode", read: ["/query/device-info", "ecp-setting-mode"] },
  { t: "Mute", m: "POST", p: "/keypress/VolumeMute" },
];

export const ACCESS_MODES = [
  { name: "Default", reads: ["yes", "Allowed"], posts: ["yes", "Allowed"], who: "Devices with private LAN addresses (192.168.x, 10.x, 172.16–31.x)" },
  { name: "Permissive", reads: ["yes", "Allowed"], posts: ["yes", "Allowed"], who: "Any address, including public and some VPN ranges. Avoid it." },
  { name: "Limited", reads: ["part", "Partial: device-info and active-app work; apps and media-player return 403"], posts: ["no", "Blocked (403)"], who: "LAN devices" },
  { name: "Disabled", reads: ["no", "Blocked"], posts: ["no", "Blocked"], who: "Nobody. The Roku mobile app's remote stops working too." },
];

export const RESPONSES = [
  ["200", "Done.", "Commands return an empty body, so success looks like nothing happened in the terminal."],
  ["403", "Refused by the Network access setting.", "Limited or Disabled mode, or the request came from outside the private LAN while on Default."],
  ["404", "Wrong method or unknown path.", "Usually a GET sent to a POST endpoint, such as typing a keypress URL into a browser. Also an unknown app ID."],
  ["none", "Timeout or connection refused.", "ECP is Disabled, the TV changed IP address, or it is fully powered down rather than in standby."],
];
