-- Dedicated REAPER instance only, launched with -cfgfile and -new.
local _, script = reaper.get_action_context()
local root = script:match("^(.*)[/\\]measurements[/\\]scripts[/\\]")
assert(root, "Cannot locate project")
local dir = root .. "/build/stage7/reaper-validation"
local log = assert(io.open(dir .. "/result.txt", "w"))
local function check(value, message)
  assert(value, message)
  log:write("PASS " .. message .. "\n")
  log:flush()
end
local ok, err = pcall(function()
  check(reaper.CountTracks(0) == 0, "dedicated empty project")
  reaper.InsertTrackAtIndex(0, false)
  local track = reaper.GetTrack(0, 0)
  local fx = reaper.TrackFX_AddByName(track, "VST3: AltaiR EQ LF (AltaiR Studio)", false, -1)
  check(fx >= 0, "load AltaiR EQ LF")
  local values = {1, 0.73, 0.29, 0, 0.65, 0}
  for i, value in ipairs(values) do
    reaper.TrackFX_SetParamNormalized(track, fx, i - 1, value)
  end
  local expected = {}
  for i = 0, 5 do expected[i] = reaper.TrackFX_GetParamNormalized(track, fx, i) end
  local env = reaper.GetFXEnvelope(track, fx, 1, true)
  check(env ~= nil, "create Boost automation envelope")
  reaper.InsertEnvelopePoint(env, 0, 0.2, 0, 0, false, true)
  reaper.InsertEnvelopePoint(env, 1, 0.8, 0, 0, false, true)
  reaper.Envelope_SortPoints(env)
  local path = dir .. "/state-roundtrip.rpp"
  reaper.Main_SaveProjectEx(0, path, 0)
  check(reaper.file_exists(path), "save dedicated RPP")
  reaper.Main_OnCommand(40859, 0) -- new project tab
  reaper.Main_openProject(path)
  check(reaper.CountTracks(0) == 1, "reopen saved RPP")
  track = reaper.GetTrack(0, 0)
  check(reaper.TrackFX_GetCount(track) == 1, "restore FX instance")
  for i = 0, 5 do
    check(math.abs(reaper.TrackFX_GetParamNormalized(track, 0, i) - expected[i]) < 1e-6,
      "restore parameter " .. i)
  end
  env = reaper.GetFXEnvelope(track, 0, 1, false)
  check(env ~= nil and reaper.CountEnvelopePoints(env) == 2, "restore automation envelope")
  for i, value in ipairs({0.2, 0.8}) do
    local found, _, restored = reaper.GetEnvelopePoint(env, i - 1)
    check(found and math.abs(restored - value) < 1e-6, "restore automation point " .. i)
  end
end)
if ok then log:write("SUCCESS\n") else log:write("FAIL " .. tostring(err) .. "\n") end
log:close()
reaper.Main_OnCommand(40004, 0) -- quit dedicated instance
