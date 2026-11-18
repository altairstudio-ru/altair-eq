-- Stage 8: audio device diagnostics in the session config directory.
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/devprobe.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local ok, err = pcall(function()
  for _, k in ipairs({"MODE", "SRATE", "BSIZE", "BPS", "IDENT_OUT", "IDENT_IN"}) do
    local _, v = reaper.GetAudioDeviceInfo(k, "")
    say(k .. "=" .. tostring(v))
  end
  say("APIExists GetAudioDeviceInfo=" .. tostring(reaper.APIExists("GetAudioDeviceInfo")))
  local x = reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false)
  say("PROJECT_SRATE=" .. x)
  reaper.InsertTrackAtIndex(0, false)
  local tr = reaper.GetTrack(0, 0)
  reaper.InsertMedia(dir .. "/../../../measurements/signals/stage8-music-96000.wav", 0)
  reaper.SetEditCurPos(0, false, false)
end)
if not ok then say("SETUP ERROR " .. tostring(err)) end
local t0 = reaper.time_precise()
local ev = 0
local function poll()
  local dt = reaper.time_precise() - t0
  if ev == 0 and dt > 0.5 then
    ev = 1
    reaper.Main_OnCommand(1007, 0)
    say(string.format("play issued state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
  elseif ev >= 1 and ev <= 6 and dt > 0.5 + ev * 0.5 then
    say(string.format("poll%d state=%d pos=%.3f", ev, reaper.GetPlayState(), reaper.GetPlayPosition()))
    ev = ev + 1
  elseif ev == 7 and dt > 4.0 then
    for _, k in ipairs({"MODE", "SRATE", "BSIZE", "IDENT_OUT"}) do
      local _, v = reaper.GetAudioDeviceInfo(k, "")
      say("late " .. k .. "=" .. tostring(v))
    end
    reaper.Main_OnCommand(1016, 0)
    reaper.Main_SaveProjectEx(0, dir .. "/scratch.rpp", 0)
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0)
    ev = 8
  end
  if ev < 8 then reaper.defer(poll) end
end
reaper.defer(poll)