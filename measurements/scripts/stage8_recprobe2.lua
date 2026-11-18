-- Stage 8: minimal output-recording probe (master NOT muted).
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/recprobe2.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local track
local ok, err = pcall(function()
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 96000, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir .. "/rec2", true)
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 1)
  reaper.InsertTrackAtIndex(0, false)
  track = reaper.GetTrack(0, 0)
  reaper.InsertMedia(dir .. "/../../../measurements/signals/stage8-music-96000.wav", 0)
  reaper.SetEditCurPos(0, false, false)
  local fx = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
  say("fx=" .. fx)
  reaper.TrackFX_SetParamNormalized(track, fx, 0, 2 / 3)
  reaper.TrackFX_SetParamNormalized(track, fx, 1, 0.7)
  reaper.TrackFX_SetParamNormalized(track, fx, 2, 0.3)
  reaper.TrackFX_SetParamNormalized(track, fx, 3, 1)
  reaper.SetMediaTrackInfo_Value(track, "I_RECMODE", 1)
  reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
  say("recmode=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECMODE")
      .. " recarm=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECARM"))
end)
if not ok then say("SETUP ERROR " .. tostring(err)) end
local t0 = reaper.time_precise()
local ev = 0
local function poll()
  local dt = reaper.time_precise() - t0
  if ev == 0 and dt > 0.5 then
    ev = 1
    reaper.Main_OnCommand(1013, 0)
    say(string.format("rec start state=%d", reaper.GetPlayState()))
  elseif ev == 1 and dt > 4.0 then
    ev = 2
    reaper.Main_OnCommand(1016, 0)
    say(string.format("stop state=%d recarm=%d", reaper.GetPlayState(),
        reaper.GetMediaTrackInfo_Value(track, "I_RECARM")))
    reaper.Main_SaveProjectEx(0, dir .. "/scratch2.rpp", 0)
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0)
  end
  if ev < 2 then reaper.defer(poll) end
end
reaper.defer(poll)