# Проверки VST3 0.1.3

17 ноября 2026. Этап 7 завершён после проверки сохранённой сессии REAPER и аудиорендера в моно. Гейт pluginval и сквозное совпадение с DSP пройдены.

Официальный pluginval 1.0.4 загружен из GitHub Tracktion/pluginval, Windows release. Установленный системный VST3 прошёл уровень строгости 10, seed 17421, частоты 44100/48000/96000, блоки 32/64/128/512. GUI-тесты включены. Восстановление состояния, автоматизация, редактор во время обработки, потокобезопасность параметров, обработка без releaseResources и fuzz завершились SUCCESS. Внешний Steinberg validator пропущен, его путь не задан. Проверки шин перечислили Mono и Stereo, основной аудиотест использовал стерео.

Полный лог сохранён в `measurements/results/stage7/pluginval-v013-level10.txt`.

```powershell
build/pluginval/pluginval.exe --strictness-level 10 --sample-rates 44100,48000,96000 --block-sizes 32,64,128,512 --random-seed 17421 --output-dir build/stage7/validation --validate "C:/Program Files/Common Files/VST3/AltaiR EQ LF.vst3"
python measurements/scripts/check_stage7_bypass.py
python measurements/scripts/check_stage7_vst3.py
ctest --test-dir build/stage6 -C Release --output-on-failure
```

На установленном пакете bypass и EQ Out дали точное совпадение с входом. Output Trim +6 дБ при EQ Out дал максимальную ошибку 4,98e−8 единицы амплитуды. Новый скрипт `check_stage7_bypass.py` использует 48 кГц и импульс из проекта.

Собранный VST3 повторно совпал с автономным DSP на трёх частотах, максимальные ошибки 4,65e−9 / 7,43e−9 / 5,22e−8. Release CTest 3/3.

Отдельный REAPER запущен с изолированным cfgfile в build/stage7/reaper-validation. Скрипт measurements/scripts/check_stage7_reaper.lua создал трек с установленным плагином, задал шесть параметров и две точки автоматизации Boost, сохранил RPP и открыл его заново. Восстановление каждого параметра и каждой точки прошло с допуском 1e−6. Протокол и тестовый RPP сохранены в measurements/results/stage7/reaper-state-roundtrip.txt и state-roundtrip.rpp. Пользовательские проекты не использовались.

Измерительный хост дополнен флагом --mono, который запрашивает одноканальные вход и выход у VST3. measurements/scripts/check_stage7_mono.py проверил установленный пакет на 44100/48000/96000 Гц, 60 CPS, Boost 7, Atten 3. Выходной WAV одноканальный. Максимальные ошибки относительно автономного DSP составили 4,65e−9 / 7,43e−9 / 5,22e−8 при допуске 1e−7. Задержка 0. Стереопроверка повторена после изменения хоста, PASS.

Следующий этап — 8, валидация в DAW и прослушивание. Оценка слышимости переходов и полноценная проверка транспорта REAPER относятся к следующему этапу.
