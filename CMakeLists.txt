cmake_minimum_required(VERSION 3.22)
project(AltairEQ VERSION 0.1.3 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
enable_testing()
add_executable(AltairEqDspTests tests/SourceEqTests.cpp)
target_include_directories(AltairEqDspTests PRIVATE dsp)
add_test(NAME AltairEqDspTests COMMAND AltairEqDspTests)
add_executable(AltairEqPultecLfTests tests/PultecLfTests.cpp)
target_include_directories(AltairEqPultecLfTests PRIVATE dsp tests/golden)
add_test(NAME AltairEqPultecLfTests COMMAND AltairEqPultecLfTests)
add_executable(AltairEqFrozenLfTests tests/FrozenLfTests.cpp)
target_include_directories(AltairEqFrozenLfTests PRIVATE dsp tests/golden)
add_test(NAME AltairEqFrozenLfTests COMMAND AltairEqFrozenLfTests)
add_executable(AltairEqFrozenImpulse tests/FrozenLfImpulse.cpp)
target_include_directories(AltairEqFrozenImpulse PRIVATE dsp)

set(ALTAIR_JUCE_SOURCE_DIR "" CACHE PATH "Local JUCE source directory for the VST3 build")
set(ALTAIR_VST3_RELEASE_OUTPUT_DIR "" CACHE PATH
    "Optional Release VST3 binary output directory; useful when the default bundle is in use")
if(ALTAIR_JUCE_SOURCE_DIR)
    enable_language(C)
    add_subdirectory("${ALTAIR_JUCE_SOURCE_DIR}" juce EXCLUDE_FROM_ALL)
    juce_add_plugin(AltairEqLF
        VERSION ${PROJECT_VERSION}
        COMPANY_NAME "AltaiR Studio"
        BUNDLE_ID "studio.altair.eq.lf"
        PLUGIN_MANUFACTURER_CODE Altr
        PLUGIN_CODE AeLf
        FORMATS VST3
        PRODUCT_NAME "AltaiR EQ LF"
        COPY_PLUGIN_AFTER_BUILD FALSE
        IS_SYNTH FALSE
        NEEDS_MIDI_INPUT FALSE
        NEEDS_MIDI_OUTPUT FALSE
        IS_MIDI_EFFECT FALSE
        EDITOR_WANTS_KEYBOARD_FOCUS FALSE)
    target_sources(AltairEqLF PRIVATE plugin/Processor.cpp plugin/Editor.cpp)
    if(ALTAIR_VST3_RELEASE_OUTPUT_DIR)
        set_target_properties(AltairEqLF_VST3 PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY_RELEASE "${ALTAIR_VST3_RELEASE_OUTPUT_DIR}"
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${ALTAIR_VST3_RELEASE_OUTPUT_DIR}")
    endif()
    target_include_directories(AltairEqLF PRIVATE dsp)
    target_compile_definitions(AltairEqLF PUBLIC JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0)
    target_link_libraries(AltairEqLF PRIVATE juce::juce_audio_processors)
    if(MSVC)
        target_compile_options(AltairEqLF PRIVATE /bigobj)
    endif()
endif()
