# AltaiR EQ

Самостоятельный программный эквалайзер AltaiR: будущий VST3 и общее DSP-ядро для AltaiR Mix Studio.

Сейчас перенесён только прототип DSP, исследовательские требования и контекст. Готового самостоятельного VST3 в этом проекте ещё нет. Основной Mix Studio продолжает развиваться отдельно.

Начать с `HANDOFF.md`, затем `PLAN.md` и `docs/RESEARCH_REQUIREMENTS.md`.

## Проверка исходного DSP

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Тесты не требуют JUCE. Для будущей VST3-оболочки в Mix Studio уже есть JUCE 8.0.15, commit 91ad83ae34a81e0833b1a2b0866f54846370ae53. Его можно читать/подключать как внешнюю зависимость, не изменяя родительский проект. Перед распространением определить лицензионный вариант.
