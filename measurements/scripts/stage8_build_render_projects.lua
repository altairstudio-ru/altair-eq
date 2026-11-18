-- Stage 8: build side-by-side render projects (one RPP per plugin/config).
-- Dedicated instance only. Each project: one source track with the signal item,
-- one FX instance, master render settings 32-bit float, dither/resample off.
-- Args come from a JSON job file written by check_stage8_render.py.
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
assert(root, "Cannot locate project root")
local dir = root .. "/build/stage8/render"
local log = assert(io.open(dir .. "/build-log.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end

local function readfile(path)
  local f = assert(io.open(path, "rb")); local s = f:read("*a"); f:close(); return s
end
-- minimal JSON array-of-objects parser for the job file (flat string/number values)
local function parsejobs(s)
  local jobs = {}
  for obj in s:gmatch("%b{}") do
    local j = {}
    for k, v in obj:gmatch('"([%w_]+)"%s*:%s*"([^"]*)"') do j[k] = v end
    for k, v in obj:gmatch('"([%w_]+)"%s*:%s*([%-%d%.]+)') do j[k] = tonumber(v) end
    jobs[#jobs + 1] = j
  end
  return jobs
end

local ok, err = pcall(function()
  local jobs = parsejobs(readfile(dir .. "/jobs.json"))
  say("jobs=" .. #jobs)
  for _, j in ipairs(jobs) do
    reaper.Main_OnCommand(40859, 0) -- new project tab
    reaper.GetSetProjectInfo(0, "PROJECT_SRATE", j.srate, true)
    reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
    reaper.InsertTrackAtIndex(0, false)
    local track = reaper.GetTrack(0, 0)
    reaper.InsertMedia(j.input, 0)
    local item = reaper.GetTrackMediaItem(track, 0)
    reaper.SetMediaItemLength(item, j.duration, false)
    reaper.SetMediaItemPosition(item, 0, false)
    local fx
    if j.plugin == "altair" then
      fx = reaper.TrackFX_AddByName(track, "AltaiR EQ LF", false, -1)
      assert(fx >= 0, "AltaiR load failed")
      reaper.TrackFX_SetParamNormalized(track, fx, 0, j.cps_norm)
      reaper.TrackFX_SetParamNormalized(track, fx, 1, j.boost / 10)
      reaper.TrackFX_SetParamNormalized(track, fx, 2, j.atten / 10)
      reaper.TrackFX_SetParamNormalized(track, fx, 3, 1)
      reaper.TrackFX_SetParamNormalized(track, fx, 4, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 5, 0)
    else
      fx = reaper.TrackFX_AddByName(track, "UADx Pultec EQP-1A", false, -1)
      assert(fx >= 0, "UADx load failed")
      reaper.TrackFX_SetParamNormalized(track, fx, 0, j.cps_norm)
      reaper.TrackFX_SetParamNormalized(track, fx, 1, j.boost / 10)
      reaper.TrackFX_SetParamNormalized(track, fx, 2, j.atten / 10)
      reaper.TrackFX_SetParamNormalized(track, fx, 8, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 9, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 10, 0.5)
      reaper.TrackFX_SetParamNormalized(track, fx, 11, 0)
    end
    for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
      local _, pname = reaper.TrackFX_GetParamName(track, fx, p, "")
      local _, ptext = reaper.TrackFX_GetFormattedParamValue(track, fx, p, "")
      say(j.id .. " param " .. p .. " " .. pname .. " = " .. ptext)
    end
    reaper.GetSetProjectInfo(0, "RENDER_SRATE", j.srate, true)
    reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 2, true)
    reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)
    reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true)
    reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", 0, true)
    reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", j.duration, true)
    reaper.GetSetProjectInfo(0, "RENDER_DITHER", 0, true)
    reaper.GetSetProjectInfo(0, "RENDER_TAILFLAG", 0, true)
    reaper.GetSetProjectInfo(0, "RENDER_RESAMPLE", 0, true)
    reaper.GetSetProjectInfo_String(0, "RENDER_FILE", root .. "/measurements/renders/stage8", true)
    reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", j.id, true)
    local path = dir .. "/" .. j.id .. ".rpp"
    reaper.Main_SaveProjectEx(0, path, 0)
    say("saved " .. path)
  end
end)
if ok then say("BUILD SUCCESS") else say("BUILD FAIL " .. tostring(err)) end
log:close()
reaper.Main_OnCommand(40004, 0)