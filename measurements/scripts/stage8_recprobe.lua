-- Stage 8: verify realtime track-output recording with muted master.
-- WASAPI shared; record the FX track output while playing and seeking.
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
local dir = root .. "/build/stage8/recprobe"
local log = assert(io.open(dir .. "/result.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local ok, err = pcall(function()
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 44100, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir, true)
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 0)
  reaper.InsertTrackAtIndex(0, false)
  local track = reaper.GetTrack(0, 0)
  reaper.InsertMedia(root .. "/measurements/signals/impulse-44100.wav", 0)
  reaper.SetEditCurPos(0, false, false)
  local fx = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
  assert(fx >= 0, "AltaiR load")
  reaper.TrackFX_SetParamNormalized(track, fx, 0, 2 / 3)
  reaper.TrackFX_SetParamNormalized(track, fx, 1, 0.7)
  reaper.TrackFX_SetParamNormalized(track, fx, 2, 0.3)
  say("recmode default=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECMODE"))
  reaper.SetMediaTrackInfo_Value(track, "I_RECMODE", 1) -- output stereo
  reaper.SetMediaTrackInfo_Value(track, "I_RECARM", 1)
  say("recmode=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECMODE")
    .. " recarm=" .. reaper.GetMediaTrackInfo_Value(track, "I_RECARM"))
end)
if not ok then say("ERROR " .. tostring(err)) end
local t0 = reaper.time_precise()
local phase = 0
local function poll()
  local dt = reaper.time_precise() - t0
  if phase == 0 and dt > 0.5 then
    phase = 1
    reaper.SetEditCurPos(0, false, false)
    reaper.Main_OnCommand(1013, 0) -- record
    say(string.format("record issued state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
  elseif phase == 1 and dt > 2.5 then
    phase = 2
    reaper.SetEditCurPos(1.0, false, true) -- seek while playing/recording
    say(string.format("seek to 1.0 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
  elseif phase == 2 and dt > 4.0 then
    phase = 3
    reaper.Main_OnCommand(1016, 0) -- stop
    reaper.SetMediaTrackInfo_Value(reaper.GetTrack(0, 0), "I_RECARM", 0)
    local track = reaper.GetTrack(0, 0)
    say("items after rec=" .. reaper.CountTrackMediaItems(track))
    for i = 0, reaper.CountTrackMediaItems(track) - 1 do
      local item = reaper.GetTrackMediaItem(track, i)
      local take = reaper.GetActiveTake(item)
      if take then
        local src = reaper.GetMediaItemTake_Source(take)
        local _, fn = reaper.GetMediaSourceFileName(src, "")
        say("item " .. i .. " pos=" .. reaper.GetMediaItemInfo_Value(item, "D_POSITION")
          .. " len=" .. reaper.GetMediaItemInfo_Value(item, "D_LENGTH") .. " file=" .. fn)
      end
    end
    reaper.Main_SaveProjectEx(0, dir .. "/scratch.rpp", 0)
    say("DONE")
    log:close()
    reaper.Main_OnCommand(40004, 0)
  end
  if phase < 3 then reaper.defer(poll) end
end
reaper.defer(poll)