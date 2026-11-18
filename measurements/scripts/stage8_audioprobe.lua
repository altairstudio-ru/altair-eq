-- Stage 8 audio-mode probe. Dedicated instance; logs device + transport, quits.
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
local dir = root .. "/build/stage8/audioprobe"
local log = assert(io.open(dir .. "/result.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
for _, key in ipairs({"MODE", "SRATE", "BSIZE", "IDENT_OUT"}) do
  local ok, val = reaper.GetAudioDeviceInfo(key)
  say("AUDIO " .. key .. " = " .. tostring(val))
end
for _, name in ipairs({"TrackFX_GetLatency", "GetTrackFXLatency", "TrackFX_GetIOSize"}) do
  say("API " .. name .. " = " .. tostring(reaper.APIExists(name)))
end
local ok, err = pcall(function()
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 0)
  reaper.InsertTrackAtIndex(0, false)
  local track = reaper.GetTrack(0, 0)
  reaper.InsertMedia(root .. "/measurements/signals/impulse-44100.wav", 0)
  reaper.SetEditCurPos(0, false, false)
  say("items=" .. reaper.CountTrackMediaItems(track) .. " len=" .. reaper.GetProjectLength(0))
end)
if not ok then say("ERROR " .. tostring(err)) end
local t0 = reaper.time_precise()
local p0 = 0
local started = false
local function poll()
  local dt = reaper.time_precise() - t0
  if not started and dt > 0.5 then
    started = true
    reaper.SetEditCurPos(0, false, false)
    reaper.Main_OnCommand(1007, 0)
    p0 = reaper.GetPlayPosition()
    say(string.format("play issued at %.2f s, state=%d pos=%.4f", dt, reaper.GetPlayState(), p0))
  end
  if dt < 3.0 then reaper.defer(poll) else
    local p1 = reaper.GetPlayPosition()
    say(string.format("state=%d pos %.4f -> %.4f advanced=%.4f", reaper.GetPlayState(), p0, p1, p1 - p0))
    reaper.Main_OnCommand(1016, 0)
    reaper.Main_SaveProjectEx(0, dir .. "/scratch.rpp", 0)
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0)
  end
end
reaper.defer(poll)