-- Stage 8: two-track output recording probe (src -> rec send, master muted).
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/recprobe4.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local src, rec
local ok, err = pcall(function()
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 96000, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir .. "/rec4", true)
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 0)
  reaper.InsertTrackAtIndex(0, false)
  src = reaper.GetTrack(0, 0)
  reaper.InsertTrackAtIndex(1, false)
  rec = reaper.GetTrack(0, 1)
  reaper.SetOnlyTrackSelected(src)
  reaper.InsertMedia(dir .. "/../../../measurements/signals/stage8-music-96000.wav", 0)
  -- InsertMedia кладёт айтем на выделенный трек; убеждаемся что на src
  say("src items=" .. reaper.CountTrackMediaItems(src) .. " rec items=" .. reaper.CountTrackMediaItems(rec))
  reaper.SetEditCurPos(0, false, false)
  local fx = reaper.TrackFX_AddByName(src, "AltaiR EQ LF", false, -1)
  reaper.TrackFX_SetParamNormalized(src, fx, 0, 2 / 3)
  reaper.TrackFX_SetParamNormalized(src, fx, 1, 0.7)
  reaper.TrackFX_SetParamNormalized(src, fx, 2, 0.3)
  reaper.TrackFX_SetParamNormalized(src, fx, 3, 1)
  reaper.SetMediaTrackInfo_Value(src, "B_MAINSEND", 0)
  local send = reaper.CreateTrackSend(src, rec)
  say("send=" .. send)
  reaper.SetMediaTrackInfo_Value(rec, "I_RECMODE", 1)
  reaper.SetMediaTrackInfo_Value(rec, "I_RECARM", 1)
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
  elseif ev >= 1 and ev <= 6 and dt > 0.5 + ev * 0.5 then
    local _, p = pcall(reaper.Track_GetPeakInfo, rec, 0)
    local _, ps = pcall(reaper.Track_GetPeakInfo, src, 0)
    say(string.format("poll%d pos=%.2f recpeak=%.5f srcpeak=%.5f", ev,
        reaper.GetPlayPosition(), p or -1, ps or -1))
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