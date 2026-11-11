# Этап 6: realtime-кернел LF и проверка архитектуры

- Дата: 11 ноября 2026
- Статус: DSP-кернел реализован и проверен на выбранных measured-fit golden-точках; карта CPS/Boost/Atten и гейт этапа 6 остаются открыты.
- Назначение: реализовать причинный JUCE-независимый фильтровый kernel, который принимает устойчивую шестисекционную SOS-модель.

## Реализовано

- `dsp/PultecLf.h`: преобразование root-параметров offline-fit в шесть biquad; стерео Direct Form II Transposed с раздельным состоянием каналов; проверка устойчивости знаменателей; сглаживание модели и EQ In за 20 ms; Output Trim −12…+12 dB с 20 ms сглаживанием.
- `tests/PultecLfTests.cpp`: обработка выбранных flat и CPS 60 / Boost 6 моделей, стереосимметрия, finite output при смене модели, отклонение неустойчивой модели, dry endpoint EQ In и Output Trim.
- `tests/golden/PultecLfRuntimeGolden.h` и генератор `measurements/scripts/export_pultec_lf_runtime_golden.py`: reference samples на пяти частотах из measured sweep и модели из capped six-section fit.
- `CMakeLists.txt`: отдельная цель `AltairEqPultecLfTests` и регистрация в CTest.
- `docs/ARCHITECTURE.md`: границы DSP-кернела и текущие пробелы.

## Исследованные альтернативы

Из-за скачков SOS-решений проверены три формы параметрической интерполяции @44,1 kHz. Прямое линейное смешивание коэффициентов SOS прошло 19/72 контрольных узлов. PCHIP-пересчёт последовательно продолженных SOS-корней прошёл 37/72. Общие полюса с отдельным FIR-числителем прошли 18/120 целевых конфигураций после подбора, медианные общие полюса без оптимизации — 0/120. Ни один вариант не принимается как карта управления.

## Проверки

- Сгенерирован golden header из fit JSON и измеренных sweep CSV.
- CMake configure и Release build выполнены Visual Studio 2022 / MSVC 19.44. Для конфигурации задан `CMAKE_TRY_COMPILE_CONFIGURATION=Release` и `CMAKE_MSVC_DEBUG_INFORMATION_FORMAT=Embedded` из-за ошибки линковщика MSPDB в первоначальной Debug-probe конфигурации.
- CTest: **2/2 PASS** (`AltairEqDspTests`, `AltairEqPultecLfTests`). Реaltime golden-компонент проверяет 2 measured-fit модели × 5 частот при 44,1 kHz.
- Исследовательские диагностические скрипты: `probe_pultec_lf_sos_coefficient_morph.py`, `probe_pultec_lf_root_pchip.py`, `probe_pultec_lf_shared_poles.py`; итоговые JSON рядом с прочими результатами в `measurements/results/pultec_lf/`.

## Ограничения и следующий шаг

- Параметры пользователя пока не преобразуются в модель; VST3-оболочка не подключена. Kernel принимает готовый массив SOS от вызывающей стороны.
- Golden-проверка ограничена 44,1 kHz и двумя выбранными кривыми; общий допуск SPEC на полном control-space не заявляется.
- Измерение кликов, host automation, совместного Boost/Atten, 48/96 kHz, VST3/DAW и listening quality не проводилось.
- Следующий шаг — разработать и проверить карту CPS/Boost/Atten, которая сможет создавать устойчивые причинные SOS-модели по всей утверждённой области; если измерительной сетки недостаточно, дополнить её независимыми контрольными точками до внедрения карты.
