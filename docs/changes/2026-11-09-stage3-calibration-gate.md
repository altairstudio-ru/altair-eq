# Этап 3: гейт калибровки закрыт

Дата: 9 ноября 2026. Статус: реализовано и проверено фактическими прогонами.
Этап 3 завершён; этап 4 (полная сетка) передан другому ИИ и здесь не выполняется.

## Назначение

Закрыть гейт этапа 3 (`docs/WORK_PLAN_PULTEC_MVP.md`): transparent null,
известный фильтр против аналитики, повторяемость, измерение задержки. До этого
в дереве были только диагностика активации UADx и REAPER-setup без рендера и
аналитического сравнения; формальный гейт не был закрыт.

## Затронутые файлы

- `tools/calfilter/CMakeLists.txt`, `tools/calfilter/Main.cpp` — калибровочный
  VST3: один RBJ peaking biquad (f0 = 1000 Hz, +6 dB, Q = 1.0), zero-latency,
  stereo, без параметров и редактора. Собран Release тем же пином JUCE
  (`ALTAIR_JUCE_SOURCE_DIR`, 8.0.15). Артефакт:
  `build-tools/calfilter/calfilter_artefacts/Release/VST3/AltaiR CalFilter.vst3`.
- `measurements/scripts/gen_signals.py` — генератор сигналов по спецификациям
  сетки; 57 stereo 32-bit float WAV (44.1/48/96 kHz).
- `measurements/scripts/analyze.py` — анализатор: `null`, `latency`
  (кросс-корреляция), `transfer` (FFT-отношение / Wiener-деконволюция sweep,
  компенсация задержки, АЧХ/фаза/group delay, независимая аналитика RBJ и гейт).
- `measurements/requirements.txt` — numpy==2.4.6, scipy==1.17.1.
- `measurements/results/signals_manifest.json` — SHA-256 и параметры 57 сигналов.
- `docs/MEASUREMENT_PROTOCOL.md` — процедура, паспорт, допуски (зафиксированы
  до прогонов).
- `measurements/results/calibration/stage3-*.json|.csv` — результаты ниже.
  Рендеры `measurements/renders/calibration/stage3-*.wav` локальные (gitignored).

## Решение и альтернативы

Известный фильтр — собственный `calfilter`, а не ReaEQ из плана. Причины:
ReaPlugs — VST2, хост поддерживает только VST3; REAPER в sandbox не стартует
(ошибка 623); подготовленный REAPER-setup имеет особенности (gain API принимает
линейный множитель → +15.6 dB вместо 6 dB; входной WAV не создан; формат
24-bit). Собственный RBJ-фильтр точно воспроизводим, аналитика реализована
независимо в Python по тем же формулам Cookbook, и проверяется та же цепочка
рендер→анализ, что пойдёт в этап 4. REAPER остаётся перекрёстной проверкой.

Допуски зафиксированы ДО прогонов: АЧХ ≤ 0.05 dB, фаза ≤ 1.0°, 20 Hz–18 kHz,
оба пути анализа (импульс и sweep); transparent и повтор — бит-в-бит.

## Фактические проверки (44.1 kHz)

- Transparent null: bit_identical=True, difference peak 0, stereo difference 0.
- Повтор calfilter (новый процесс): bit_identical=True, peak 0.
- Задержка calfilter (кросс-корреляция): 0 сэмплов, пиковый сдвиг 0.
- Impulse transfer против RBJ: max|err| = 4.59e-7 dB, 7.57e-7°, PASS
  (89901 bin в полосе). На 1 kHz измерено +6.0000002 dB.
- Sweep transfer против RBJ: max|err| = 2.21e-6 dB, 1.40e-5°, PASS
  (314651 bin). Оба пути анализа согласованы с аналитикой до float-точности.
- UADx Pultec flat impulse (вне sandbox, `--require-latency=86`): latency 86
  сэмплов = 1.9501 ms, кросс-корреляция и пиковый сдвиг совпадают (86),
  stereo difference 0. Защита по задержке прошла, WAV записан.

Артефакты: `stage3-transparent-null.json`, `stage3-calfilter-repeat.json`,
`stage3-calfilter-latency.json`, `stage3-calfilter-impulse-transfer.json|.csv`,
`stage3-calfilter-sweep-transfer.json|.csv`, `stage3-pultec-flat-latency.json`.

## Ограничения и следующий шаг

Задержка UADx 86 сэмплов подтверждена только на 44.1 kHz; для 48/96 kHz
измерить до рендеров сетки. Калибровка проверяет линейный измерительный тракт;
нелинейность UADx (уровневая зависимость, THD/IMD) — предмет этапа 4, не этапа 3.
Субъективное качество, DAW-совместимость и модель Pultec не подтверждались.

Следующий шаг — этап 4 (другой ИИ): полная сетка 355 заданий
(`measurements/grid/pultec_lf_grid.json`) на готовом стенде. База готова:
renderer `vst3render`, анализатор `analyze.py`, сигналы с манифестом, протокол,
паспорт эталона, дамп параметров. DSP продукта не изменён; миграция не нужна.
Откат этапа 3: убрать `tools/calfilter`, `gen_signals.py`, `analyze.py`,
`requirements.txt`, протокол и calibration-артефакты.