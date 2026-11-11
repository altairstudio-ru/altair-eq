cmake_minimum_required(VERSION 3.22)
project(AltairCalFilter VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED ALTAIR_JUCE_SOURCE_DIR)
    message(FATAL_ERROR "Set ALTAIR_JUCE_SOURCE_DIR to the read-only JUCE checkout")
endif()
add_subdirectory("${ALTAIR_JUCE_SOURCE_DIR}" JUCE EXCLUDE_FROM_ALL)

juce_add_plugin(calfilter
    PRODUCT_NAME "AltaiR CalFilter"
    COMPANY_NAME "AltaiR Studio"
    BUNDLE_ID com.AltaiRStudio.calfilter
    PLUGIN_MANUFACTURER_CODE AltR
    PLUGIN_CODE CalF
    FORMATS VST3
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS FALSE
    COPY_PLUGIN_AFTER_BUILD FALSE
    VST3_CATEGORIES Fx EQ)

target_sources(calfilter PRIVATE Main.cpp)

target_compile_definitions(calfilter PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_MODAL_LOOPS_PERMITTED=0)

target_link_libraries(calfilter PRIVATE
    juce::juce_audio_processors
    juce::juce_audio_utils
    juce::juce_recommended_config_flags)