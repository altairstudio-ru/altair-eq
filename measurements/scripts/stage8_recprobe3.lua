-- Stage 8: verify realtime audio flow via track peak meters + record mode 2.
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/recprobe3.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local track
local ok, err = pcall(function()
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 96000, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir .. "/rec3", true)
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 1)
  reaper.InsertTrackAtIndex(0, false)
  track = reaper.GetTrack(0, 0)
  reaper.InsertMedia(dir .. "/../../../measurements/signals/stage8-music-96000.wav", 0)
  reaper.SetEditCurPos(0, false, false)
  local fx = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
  reaper.TrackFX_SetParamNormalized(track, fx, 0, 2 / 3)
  reaper.TrackFX_SetParamNormalized(track, fx, 1, 0.7)
  reaper.TrackFX_SetParamNormalized(track, fx, 2, 0.3)
  reaper.TrackFX_SetParamNormalized(track, fx, 3, 1)
  reaper.SetMediaTrackInfo_Value(track, "I_RECMODE", 2)
  reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
  say("APIExists Track_GetPeakInfo=" .. tostring(reaper.APIExists("Track_GetPeakInfo")))
  say("recmode=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECMODE"))
end)
if not ok then say("SETUP ERROR " .. tostring(err)) end
local t0 = reaper.time_precise()
local ev = 0
local function peaks(tag)
  local okp, p0 = pcall(reaper.Track_GetPeakInfo, track, 0)
  local okm, m0 = pcall(reaper.Track_GetPeakInfo, reaper.GetMasterTrack(0), 0)
  say(tag .. " trackpeak=" .. tostring(okp and p0) .. " masterpeak=" .. tostring(okm and m0))
end
local function poll()
  local dt = reaper.time_precise() - t0
  if ev == 0 and dt > 0.5 then
    ev = 1
    reaper.Main_OnCommand(1013, 0)
    say(string.format("rec start state=%d", reaper.GetPlayState()))
  elseif ev >= 1 and ev <= 6 and dt > 0.5 + ev * 0.5 then
    peaks(string.format("poll%d pos=%.2f", ev, reaper.GetPlayPosition()))
    ev = ev + 1
  elseif ev == 7 and dt > 4.5 then
    ev = 8
    reaper.Main_OnCommand(1016, 0)
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0)
  end
  if ev < 8 then reaper.defer(poll) end
end
reaper.defer(poll)