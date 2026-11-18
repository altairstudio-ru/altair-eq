-- Stage 8 probe. Dedicated REAPER instance only (-cfgfile, -new).
-- Verifies dummy audio engine, transport commands, master output recording,
-- plugin availability and parameter maps. Writes build/stage8/probe/result.txt.
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
assert(root, "Cannot locate project root")
local dir = root .. "/build/stage8/probe"
local log = assert(io.open(dir .. "/result.txt", "w"))
local function say(msg) log:write(msg .. "\n") log:flush() end
local function check(value, message)
  if value then say("PASS " .. message) else say("FAIL " .. message) end
  return value
end

say("REAPER " .. reaper.GetAppVersion())

-- API availability
for _, name in ipairs({"GetAudioDeviceInfo", "GetSetAudioDeviceInfo", "GetPlayState",
    "GetPlayPosition", "GetSetProjectInfo", "GetSetProjectInfo_String",
    "SetMediaTrackInfo_Value", "GetMasterTrack", "TrackFX_GetPerformanceMeter",
    "GetToggleCommandState", "EnumPlugins", "APIExists"}) do
  say("API " .. name .. " = " .. tostring(reaper.APIExists(name)))
end

-- Command names (verify locally, never hardcode from memory)
for _, id in ipairs({1007, 1008, 1013, 1016, 40044, 40045, 40073, 40317,
    41823, 40099, 40859, 40004, 40026, 40297, 40621, 40622, 40623, 40624,
    40012, 40013, 40014, 40015, 40016, 40017, 40018, 40019, 40020}) do
  local name = reaper.kbd_getTextFromCmd(id, 0)
  say("CMD " .. id .. " = " .. tostring(name))
end

-- Actual audio device state
for _, key in ipairs({"MODE", "SRATE", "BSIZE", "IDENT_IN", "IDENT_OUT", "BPS"}) do
  local ok, val = reaper.GetAudioDeviceInfo(key)
  say("AUDIO " .. key .. " = " .. tostring(ok) .. " " .. tostring(val))
end

local ok, err = pcall(function()
  check(reaper.CountTracks(0) == 0, "empty dedicated project")
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 44100, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir, true)
  reaper.InsertTrackAtIndex(0, false)
  local track = reaper.GetTrack(0, 0)
  local altair = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
  check(altair >= 0, "load AltaiR EQ LF")
  local uadx = reaper.TrackFX_AddByName(track, "UADx Pultec EQP-1A", false, -1)
  check(uadx >= 0, "load UADx Pultec EQP-1A")
  for _, fx in ipairs({altair, uadx}) do
    if fx >= 0 then
      local _, fxname = reaper.TrackFX_GetFXName(track, fx, "")
      say("FX " .. fxname .. " latency=" .. reaper.TrackFX_GetLatency(track, fx))
      for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
        local _, pname = reaper.TrackFX_GetParamName(track, fx, p, "")
        local _, ptext = reaper.TrackFX_GetFormattedParamValue(track, fx, p, "")
        say(string.format("PARAM %d %s = %s (norm %.6f)", p, pname, ptext,
          reaper.TrackFX_GetParamNormalized(track, fx, p)))
      end
    end
  end
  -- Master output recording capability
  local master = reaper.GetMasterTrack(0)
  local prev = reaper.GetMediaTrackInfo_Value(master, "I_RECMODE")
  say("master I_RECMODE default = " .. prev)
  reaper.SetMediaTrackInfo_Value(master, "I_RECMODE", 1)
  reaper.SetMediaTrackInfo_Value(master, "I_RECARM", 1)
  say("master I_RECMODE now = " .. reaper.GetMediaTrackInfo_Value(master, "I_RECMODE")
    .. " I_RECARM = " .. reaper.GetMediaTrackInfo_Value(master, "I_RECARM"))
  reaper.SetMediaTrackInfo_Value(master, "I_RECARM", 0)
end)
if not ok then say("ERROR " .. tostring(err)) end

-- Dummy audio engine: does the transport actually advance?
reaper.Main_OnCommand(1007, 0) -- play
local t0 = reaper.time_precise()
local p0 = reaper.GetPlayPosition()
local function poll()
  if reaper.time_precise() - t0 < 1.0 then
    reaper.defer(poll)
  else
    local p1 = reaper.GetPlayPosition()
    say(string.format("transport play state=%d pos %.4f -> %.4f (advanced %.4f s)",
      reaper.GetPlayState(), p0, p1, p1 - p0))
    check(p1 - p0 > 0.5, "dummy audio transport advances")
    reaper.Main_OnCommand(1016, 0) -- stop
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0) -- quit dedicated instance
  end
end
reaper.defer(poll)