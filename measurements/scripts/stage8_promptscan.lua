-- Stage 8: find the recorded-files save prompt toggle action.
local dir = reaper.GetResourcePath()
local log = assert(io.open(dir .. "/promptscan.txt", "w"))
for id = 1, 65000 do
  local name = reaper.kbd_getTextFromCmd(id, 0)
  if name and name:lower():find("prompt") then
    log:write(id .. " | state=" .. reaper.GetToggleCommandState(id) .. " | " .. name .. "\n")
  end
end
log:write("SCAN DONE\n")
log:close()
reaper.Main_OnCommand(40004, 0)