# Сборка первого VST3 на Windows x64

С 16 ноября 2026 рабочая установка для REAPER одна: `C:\Program Files\Common Files\VST3\AltaiR EQ LF.vst3`. При обновлении заменять этот пакет и проверять его загрузку по системному пути. Каталоги `build` предназначены для сборки и автономных тестов. Из списка сканирования REAPER удалены оба проектных пути (`stage7/AltairEqLF_artefacts/Release/VST3` и `stage7-a4-output`), запись настроек проверена повторным чтением.

Из корня проекта в PowerShell, с Visual Studio 2022 и локальным JUCE.

```powershell
cmake -S . -B build/stage7 -G "Visual Studio 17 2022" -A x64 -T host=x64 "-DALTAIR_JUCE_SOURCE_DIR=K:/AltaiR Studio/Projects/AltaiR Mix Studio/external/JUCE"
cmake --build build/stage7 --target AltairEqLF_VST3 --config Release --parallel 4
```

Пакет находится в `build/stage7/AltairEqLF_artefacts/Release/VST3/AltaiR EQ LF.vst3`. Для сквозной проверки нужны собранные ранее `build-tools/vst3render_artefacts/Release/vst3render.exe`, `build/stage6/Release/AltairEqFrozenImpulse.exe`, Python, NumPy и SciPy.

```powershell
python measurements/scripts/check_stage7_vst3.py
```

Сценарий сравнивает два канала с отдельным экземпляром DSP при 60 CPS, Boost 7 и Atten 3. Разная амплитуда и полярность входов позволяют обнаружить подмену одного канала другим. Хост требует задержку 0 сэмплов.
