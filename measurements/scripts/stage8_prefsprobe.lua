-- Stage 8: open audio device preferences and stay alive for UI automation.
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/prefsprobe.txt", "w"))
local function say(m) log:write(m .. "\n") log:flush() end
say("opened")
local t0 = reaper.time_precise()
local opened = false
local function poll()
  local dt = reaper.time_precise() - t0
  if not opened and dt > 1.0 then
    opened = true
    reaper.Main_OnCommand(40099, 0) -- prefs: audio device
    say("prefs command issued")
  end
  local f = io.open(dir .. "/quit.txt", "rb")
  if f then
    f:close()
    say("quit marker seen")
    log:close()
    reaper.Main_OnCommand(40004, 0)
    return
  end
  reaper.defer(poll)
end
reaper.defer(poll)