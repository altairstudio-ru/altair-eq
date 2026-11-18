-- Stage 8 transport/seek/reset/bypass validation with realtime output capture.
-- Dedicated instance, WASAPI shared (device rate), muted master, track-output
-- recording. Reads job.json from the instance config directory.
-- job: {plugin="altair"|"uadx", instances=N, signal=<abs wav>, mode="transport"|"load"}
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
assert(root, "Cannot locate project root")
local _, cfgpath = reaper.get_action_context()
-- config dir is passed via job.json location: use REAPER resource path
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/result.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
local function readfile(path)
  local f = assert(io.open(path, "rb")); local s = f:read("*a"); f:close(); return s
end
local job = {}
local okj, jtxt = pcall(readfile, dir .. "/job.json")
if okj then
  for k, v in jtxt:gmatch('"([%w_]+)"%s*:%s*"([^"]*)"') do job[k] = v end
  for k, v in jtxt:gmatch('"([%w_]+)"%s*:%s*([%-%d%.]+)') do job[k] = tonumber(v) end
end
local plugin = job.plugin or "altair"
local instances = job.instances or 1
local mode = job.mode or "transport"
say("job plugin=" .. plugin .. " instances=" .. instances .. " mode=" .. mode)
for _, k in ipairs({"MODE", "SRATE", "BSIZE", "BPS", "IDENT_OUT"}) do
  local _, v = reaper.GetAudioDeviceInfo(k, "")
  say("device " .. k .. "=" .. tostring(v))
end

local track, rectrack, fxlist = nil, nil, {}
local ok, err = pcall(function()
  -- запрос сохранения записанных файлов отключён ключом promptendrec=0 в reaper.ini
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 96000, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", dir .. "/rec", true)
  reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOLUME", 0)
  -- два трека: src (айтем+FX, не armed) -> send -> rec (armed, запись выхода).
  -- armed-трек мониторит вход и НЕ играет свои айтемы, поэтому запись выхода
  -- того же трека, где лежит сигнал, невозможна (проверено recprobe1-3).
  reaper.InsertTrackAtIndex(0, false)
  track = reaper.GetTrack(0, 0)
  reaper.SetOnlyTrackSelected(track)
  reaper.InsertMedia(job.signal, 0)
  reaper.SetEditCurPos(0, false, false)
  for i = 1, instances do
    local fx
    if plugin == "altair" then
      fx = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
      assert(fx >= 0, "AltaiR load failed")
      reaper.TrackFX_SetParamNormalized(track, fx, 0, 2 / 3)
      reaper.TrackFX_SetParamNormalized(track, fx, 1, 0.7)
      reaper.TrackFX_SetParamNormalized(track, fx, 2, 0.3)
      reaper.TrackFX_SetParamNormalized(track, fx, 3, 1)
      reaper.TrackFX_SetParamNormalized(track, fx, 4, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 5, 0)
    else
      fx = reaper.TrackFX_AddByName(track, "UADx Pultec EQP-1A", false, -1)
      assert(fx >= 0, "UADx load failed")
      reaper.TrackFX_SetParamNormalized(track, fx, 0, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 1, 0.7)
      reaper.TrackFX_SetParamNormalized(track, fx, 2, 0.3)
      reaper.TrackFX_SetParamNormalized(track, fx, 8, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 9, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 10, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 11, 0)
    end
    fxlist[#fxlist + 1] = fx
  end
  say("fx count=" .. reaper.TrackFX_GetCount(track))
  if mode == "transport" then
    reaper.InsertTrackAtIndex(1, false)
    rectrack = reaper.GetTrack(0, 1)
    reaper.SetMediaTrackInfo_Value(track, "B_MAINSEND", 0)
    local send = reaper.CreateTrackSend(track, rectrack)
    say("send=" .. tostring(send))
    reaper.SetMediaTrackInfo_Value(rectrack, "I_RECMODE", 1) -- запись выхода
    reaper.SetMediaTrackInfo_Value(rectrack, "I_RECARM", 1)
  end
end)
if not ok then say("SETUP ERROR " .. tostring(err)) end

local function setbypass(on)
  for _, fx in ipairs(fxlist) do
    if plugin == "altair" then
      reaper.TrackFX_SetParamNormalized(track, fx, 5, on and 1 or 0)
    else
      reaper.TrackFX_SetEnabled(track, fx, not on)
    end
  end
end

-- после stop записанный выход попадает на rec-трек айтемом; глушим его, чтобы
-- следующий play не воспроизводил запись (удаление айтема уничтожает файл)
local function muterecitems()
  if not rectrack then return end
  for i = 0, reaper.CountTrackMediaItems(rectrack) - 1 do
    reaper.SetMediaItemInfo_Value(reaper.GetTrackMediaItem(rectrack, i), "B_MUTE", 1)
  end
end

local function dumpparams(tag)
  for i, fx in ipairs(fxlist) do
    local line = tag .. " fx" .. i
    for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
      line = line .. string.format(" %d=%.4f", p, reaper.TrackFX_GetParamNormalized(track, fx, p))
    end
    line = line .. " enabled=" .. tostring(reaper.TrackFX_GetEnabled(track, fx))
    say(line)
  end
end

local t0 = reaper.time_precise()
local ev = 0
local function poll()
  local dt = reaper.time_precise() - t0
  if mode == "load" then
    if ev == 0 and dt > 0.5 then
      ev = 1
      reaper.SetEditCurPos(0, false, false)
      reaper.Main_OnCommand(1007, 0)
      say("load playback started")
    elseif ev == 1 and dt > 24 then
      ev = 2
      reaper.Main_OnCommand(1016, 0)
      dumpparams("after-load")
      reaper.Main_SaveProjectEx(0, dir .. "/scratch.rpp", 0)
      say("DONE")
      log:close()
      reaper.Main_OnCommand(40004, 0)
    elseif ev == 1 and reaper.GetPlayPosition() > 11.5 then
      reaper.SetEditCurPos(0, false, true)
    end
  else
    -- seek во время записи НЕ работает (SetEditCurPos seekplay игнорируется
    -- в record-состоянии, проверено: запись шла линейно). Поэтому каждый
    -- material-переход делается через stop -> seek -> record+play: отдельный
    -- записанный burst со стартом из известной позиции. bypass/pause — внутри
    -- burst (смена параметра и пауза при записи работают).
    if ev == 0 and dt > 0.5 then
      ev = 1
      reaper.SetEditCurPos(0, false, false)
      reaper.Main_OnCommand(1013, 0) -- burst1 mat0
      say(string.format("E1 rec burst1 mat0 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 1 and dt > 3.0 then
      ev = 2
      reaper.Main_OnCommand(1016, 0) -- stop burst1
      muterecitems()
      reaper.SetEditCurPos(6.0, false, false) -- seek WHILE STOPPED
      reaper.Main_OnCommand(1013, 0) -- burst2 mat6
      say(string.format("E2 stop+seek6+rec burst2 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 2 and dt > 5.0 then
      ev = 3
      reaper.Main_OnCommand(1016, 0) -- stop burst2
      muterecitems()
      reaper.SetEditCurPos(2.0, false, false)
      reaper.Main_OnCommand(1013, 0) -- burst3 mat2
      say(string.format("E3 stop+seek2+rec burst3 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 3 and dt > 7.0 then
      ev = 4
      reaper.Main_OnCommand(1016, 0) -- stop burst3
      muterecitems()
      reaper.SetEditCurPos(0, false, false) -- reset
      reaper.Main_OnCommand(1013, 0) -- burst4 mat0
      say(string.format("E4 stop+seek0+rec burst4 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 4 and dt > 9.0 then
      ev = 5
      setbypass(true) -- внутри burst4 (mat~2)
      say(string.format("E5 bypass on state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 5 and dt > 10.5 then
      ev = 6
      setbypass(false) -- внутри burst4 (mat~3.5)
      say(string.format("E6 bypass off state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 6 and dt > 11.0 then
      ev = 7
      reaper.Main_OnCommand(1016, 0) -- stop burst4
      muterecitems()
      reaper.SetEditCurPos(0, false, false) -- reset
      reaper.Main_OnCommand(1013, 0) -- burst5 mat0
      say(string.format("E7 stop+seek0+rec burst5 state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 7 and dt > 13.0 then
      ev = 8
      reaper.Main_OnCommand(1008, 0) -- pause внутри burst5 (mat~2)
      say(string.format("E8 pause state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 8 and dt > 14.0 then
      ev = 9
      reaper.Main_OnCommand(1008, 0) -- resume burst5
      say(string.format("E9 resume state=%d pos=%.3f", reaper.GetPlayState(), reaper.GetPlayPosition()))
    elseif ev == 9 and dt > 16.0 then
      ev = 10
      reaper.Main_OnCommand(1016, 0) -- stop
      muterecitems()
      if rectrack then reaper.SetMediaTrackInfo_Value(rectrack, "I_RECARM", 0) end
      dumpparams("after-transport")
      say("items src=" .. reaper.CountTrackMediaItems(track)
          .. " rec=" .. (rectrack and reaper.CountTrackMediaItems(rectrack) or 0))
      reaper.Main_SaveProjectEx(0, dir .. "/scratch.rpp", 0)
      say("DONE")
      log:close()
      reaper.Main_OnCommand(40004, 0)
    end
  end
  if ev < 10 then reaper.defer(poll) end
end
reaper.defer(poll)