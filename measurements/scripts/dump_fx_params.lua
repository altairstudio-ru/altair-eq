-- AltaiR EQ — дамп параметров FX для паспорта эталона (этап 2, docs/WORK_PLAN_PULTEC_MVP.md).
-- Только чтение: проект, треки и настройки плагинов НЕ изменяются.
--
-- Запуск:
--   1. Открыть копию eq_reaper_project/eq_reaper_project.rpp
--      (рабочую сессию REAPER «Разработка VST» не использовать и не изменять).
--   2. Вставить UADx Pultec EQP-1A EQ на тестовый трек и выбрать этот трек.
--   3. Actions -> Show action list -> New action -> Load ReaScript... -> этот файл -> Run.
--
-- Результат: measurements/passports/fx_dump_<дата-время>.json
-- (если каталог passports рядом со скриптом не определяется, файл кладётся
--  в каталог проекта; итоговый путь показывается в сообщении).

local function json_escape(s)
  s = s:gsub('[%c\\"]', function(c)
    local map = {
      ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b', ['\f'] = '\\f',
      ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t',
    }
    return map[c] or string.format('\\u%04x', string.byte(c))
  end)
  return s
end

local function is_array(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n == #t
end

local function json_encode(value, indent)
  indent = indent or 0
  local pad = string.rep('  ', indent)
  local inner_pad = string.rep('  ', indent + 1)
  local t = type(value)
  if t == 'nil' then
    return 'null'
  elseif t == 'boolean' then
    return tostring(value)
  elseif t == 'number' then
    if value ~= value or value == math.huge or value == -math.huge then
      return 'null'
    end
    if value == math.floor(value) and math.abs(value) < 1e15 then
      return string.format('%d', value)
    end
    return string.format('%.10g', value)
  elseif t == 'string' then
    return '"' .. json_escape(value) .. '"'
  elseif t == 'table' then
    local parts = {}
    if is_array(value) then
      for _, item in ipairs(value) do
        parts[#parts + 1] = inner_pad .. json_encode(item, indent + 1)
      end
      if #parts == 0 then return '[]' end
      return '[\n' .. table.concat(parts, ',\n') .. '\n' .. pad .. ']'
    else
      local keys = {}
      for k in pairs(value) do keys[#keys + 1] = tostring(k) end
      table.sort(keys)
      for _, k in ipairs(keys) do
        parts[#parts + 1] = inner_pad .. '"' .. json_escape(k) .. '": '
          .. json_encode(value[k], indent + 1)
      end
      if #parts == 0 then return '{}' end
      return '{\n' .. table.concat(parts, ',\n') .. '\n' .. pad .. '}'
    end
  end
  return 'null'
end

-- Именованный config-параметр плагина (ident/version), если поддерживается хостом.
local function named_parm(track, fx, name)
  local ok, retval, value = pcall(reaper.TrackFX_GetNamedConfigParm, track, fx, name)
  if ok and retval and type(value) == 'string' and value ~= '' then
    return value
  end
  return nil
end

local function track_index_of(track)
  for i = 0, reaper.CountTracks(0) - 1 do
    if reaper.GetTrack(0, i) == track then return i end
  end
  return -1
end

local function collect_track(track, track_index)
  local ok_name, track_name = reaper.GetTrackName(track)
  local fx_count = reaper.TrackFX_GetCount(track)
  local fx_list = {}
  for fx = 0, fx_count - 1 do
    local ok_fxname, fx_name = reaper.TrackFX_GetFXName(track, fx, '')
    local param_count = reaper.TrackFX_GetNumParams(track, fx)
    local params = {}
    for p = 0, param_count - 1 do
      local ok_pname, p_name = reaper.TrackFX_GetParamName(track, fx, p, '')
      local value, min_value, max_value = reaper.TrackFX_GetParam(track, fx, p)
      local normalized = reaper.TrackFX_GetParamNormalized(track, fx, p)
      local step, small_step, large_step = reaper.TrackFX_GetParamStep(track, fx, p)
      local ok_f, formatted = reaper.TrackFX_FormatParamValue(track, fx, p, value, '')
      local ok_fmin, formatted_min = reaper.TrackFX_FormatParamValue(track, fx, p, min_value, '')
      local ok_fmax, formatted_max = reaper.TrackFX_FormatParamValue(track, fx, p, max_value, '')
      params[#params + 1] = {
        index = p,
        name = (ok_pname and p_name) or '',
        value = value,
        min = min_value,
        max = max_value,
        normalized = normalized,
        step = step,
        small_step = small_step,
        large_step = large_step,
        formatted = (ok_f and formatted) or '',
        formatted_min = (ok_fmin and formatted_min) or '',
        formatted_max = (ok_fmax and formatted_max) or '',
      }
    end
    fx_list[#fx_list + 1] = {
      index = fx,
      name = (ok_fxname and fx_name) or '',
      enabled = reaper.TrackFX_GetEnabled(track, fx),
      ident = named_parm(track, fx, 'ident'),
      version_parm = named_parm(track, fx, 'version'),
      parameter_count = param_count,
      parameters = params,
    }
  end
  return {
    track_index = track_index,
    track_name = (ok_name and track_name) or '',
    fx_count = fx_count,
    fx = fx_list,
  }
end

-- Выбор треков: выбранные пользователем, иначе первый трек с FX.
local tracks = {}
local selected = reaper.CountSelectedTracks(0)
if selected > 0 then
  for i = 0, selected - 1 do
    tracks[#tracks + 1] = reaper.GetSelectedTrack(0, i)
  end
else
  for i = 0, reaper.CountTracks(0) - 1 do
    local t = reaper.GetTrack(0, i)
    if reaper.TrackFX_GetCount(t) > 0 then
      tracks[#tracks + 1] = t
      break
    end
  end
end

if #tracks == 0 then
  reaper.ShowMessageBox(
    'Не найдено треков с FX. Вставьте UADx Pultec EQP-1A EQ на тестовый трек, '
      .. 'выберите трек и запустите скрипт снова.',
    'AltaiR EQ: дамп параметров FX', 0)
  return
end

local dump = {
  schema = 'altair-eq.fx-dump/1',
  created_utc = os.date('!%Y-%m-%dT%H:%M:%SZ'),
  purpose = 'Паспорт эталона: UADx Pultec EQP-1A EQ v1.2.16 (этап 2 WORK_PLAN_PULTEC_MVP)',
  host = {
    app = 'REAPER',
    version = reaper.GetAppVersion(),
    os = reaper.GetOS(),
  },
  project = {
    sample_rate = reaper.GetSetProjectInfo(0, 'PROJECT_SRATE', 0, false),
    path = reaper.GetProjectPath(''),
  },
  tracks = {},
  notes = {
    'Скрипт только читает состояние: проект и настройки плагинов не изменялись.',
    'value/min/max - сырые значения API; normalized - [0,1].',
    'step > 0 означает дискретный параметр; для непрерывного step == 0.',
    'version_parm может отсутствовать: версию подтверждать по UI плагина (v1.2.16).',
  },
}

for _, t in ipairs(tracks) do
  dump.tracks[#dump.tracks + 1] = collect_track(t, track_index_of(t))
end

local timestamp = os.date('%Y-%m-%d_%H-%M-%S')
local json_text = json_encode(dump) .. '\n'

local function write_to(path)
  local f = io.open(path, 'wb')
  if not f then return false end
  f:write(json_text)
  f:close()
  return true
end

-- Приоритет: ../passports/ рядом со скриптом (measurements/scripts -> measurements/passports).
local out_file = nil
local ok_ctx, _is_new, script_path = pcall(reaper.get_action_context)
if ok_ctx and type(script_path) == 'string' and script_path ~= '' then
  local dir = script_path:match('^(.*[/\\])')
  if dir then
    local sep = dir:sub(-1)
    local passports_dir = dir .. '..' .. sep .. 'passports'
    reaper.RecursiveCreateDirectory(passports_dir, 0)
    out_file = passports_dir .. sep .. 'fx_dump_' .. timestamp .. '.json'
  end
end

local written = false
if out_file then
  written = write_to(out_file)
end
if not written then
  out_file = reaper.GetProjectPath('') .. '/fx_dump_' .. timestamp .. '.json'
  written = write_to(out_file)
end

if written then
  reaper.ShowMessageBox(
    'Дамп записан:\n' .. out_file
      .. '\n\nЕсли файл лежит вне проекта AltaiR EQ, скопируйте его в measurements/passports/.',
    'AltaiR EQ: дамп параметров FX', 0)
else
  reaper.ShowMessageBox(
    'Не удалось записать файл дампа. Проверьте права на каталог проекта.',
    'AltaiR EQ: дамп параметров FX', 0)
end