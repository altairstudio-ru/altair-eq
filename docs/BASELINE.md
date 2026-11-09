# Baseline AltaiR EQ — 8 ноября 2026

Назначение: воспроизводимая отправная точка перед работами по Pultec EQP-1A LF MVP (`docs/WORK_PLAN_PULTEC_MVP.md`, этап 1). Всё ниже — фактические проверки этого дня, не декларации.

## Git

- HEAD: `be08f0e` «Bootstrap AltaiR EQ with shared DSP, tests and project handoff» (master).
- Создана рабочая ветка `pultec-lf-mvp`. Коммитов в этой задаче не выполнялось: коммит только по явной команде пользователя.
- Незакоммиченные изменения прошлой сессии в рабочем дереве: M `AGENTS.md`, M `HANDOFF.md`, M `PLAN.md`, M `README.md`; не отслеживаются `docs/DOCUMENTATION_POLICY.md`, `docs/RESEARCH_EQ_MARKET.md`, `docs/STAGED_PLAN.md`, `docs/changes/`, `eq_reaper_project/`, `outputs/`, `work/`.

## Сборка и тесты (фактический прогон 08.11.2026)

- Конфигурация: `cmake -S . -B build -G "Visual Studio 17 2022" -A x64` (CMake 4.4.4, C++17).
- Сборка: `cmake --build build --config Release` — успешно, MSBuild 17.14.60, артефакт `build/Release/AltairEqDspTests.exe`.
- Тесты: `ctest --test-dir build -C Release --output-on-failure`:

  ```
  1/1 Test #1: AltairEqDspTests .................   Passed    0.04 sec
  100% tests passed out of 1
  ```

- Покрытие (`tests/SourceEqTests.cpp`): синус-прогон трёх полос на 44.1/48/96 kHz (+6 dB на 35/1000/16000 Hz), стереосимметрия, сухой проход после bypass-ramp, битовая прозрачность при flat.

## Окружение

- Python 3.11.9; numpy 2.4.6; scipy 1.17.1 — для будущего измерительного стенда (этап 3).
- JUCE (внешняя зависимость, read-only): `K:/AltaiR Studio/Projects/AltaiR Mix Studio/external/JUCE`, коммит `91ad83ae34a81e0833b1a2b0866f54846370ae53`, дата 2026-07-21, «JUCE version 8.0.15». Совпадает с заявленным в README. Родительский проект не изменён.

## Состояние кода

- `dsp/SourceEq.h` — прежний технический прототип (3 фиксированные полосы: Low Shelf 150 Hz, Bell 1 kHz, High Shelf 6 kHz, gain ±6 dB), НЕ модель Pultec. Pultec-DSP нет.
- `integration/Module.h` — копия контракта Mix Studio; SerialRack принимает только zero-latency/zero-tail модули.
- `CMakeLists.txt` — единственная цель `AltairEqDspTests`; JUCE/VST3-оболочки нет.
- `eq_reaper_project/eq_reaper_project.rpp` — пустая заготовка REAPER 7.85 (win64, 44.1 kHz), без треков и FX.
- Измерительной инфраструктуры нет. Подготовлен (не проверен запуском) `measurements/scripts/dump_fx_params.lua` — проверка в REAPER на этапе 2 с пользователем.
- Референс-экземпляр: **UADx Pultec EQP-1A EQ, VST3, v1.2.16, REAPER 7.85** — подтверждён скриншотом пользователя (`docs/changes/2026-11-08-pultec-reference.md`); аудиоизмерений не выполнялось.

## Открытые вопросы

1. Гранулярность и закон ручек Boost/Atten, точный набор CPS — до дампа параметров (этап 2) и сверки с мануалом UA.
2. Наличие выходного Gain/makeup у UADx-экземпляра.
3. Задержка/oversampling UADx — измерять, не доверять только API-репорту.
4. Нелинейность (окраска) тракта плагина — решается данными этапа 4.
5. Action ID офлайн-рендера и форматные настройки REAPER 7.85 — проверить локально на этапе 3.
6. Лицензионный вариант JUCE — отложен до дистрибуции.