cmake_minimum_required(VERSION 3.22)
project(AltairEqTools VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(ALTAIR_JUCE_SOURCE_DIR "" CACHE PATH "Path to JUCE source tree (read-only external dependency)")
if(NOT ALTAIR_JUCE_SOURCE_DIR)
  message(FATAL_ERROR "Pass -DALTAIR_JUCE_SOURCE_DIR=<path to JUCE>, e.g. the external/JUCE of AltaiR Mix Studio")
endif()

add_subdirectory(${ALTAIR_JUCE_SOURCE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/juce EXCLUDE_FROM_ALL)

juce_add_console_app(vst3paramdump PRODUCT_NAME "vst3paramdump")

target_sources(vst3paramdump PRIVATE Main.cpp)

target_compile_definitions(vst3paramdump PRIVATE
    JUCE_PLUGINHOST_VST3=1
    JUCE_PLUGINHOST_VST=0
    JUCE_PLUGINHOST_AU=0
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(vst3paramdump PRIVATE
    juce::juce_audio_processors
    juce::juce_events
    juce::juce_recommended_config_flags)

juce_add_console_app(vst3render PRODUCT_NAME "vst3render")
target_sources(vst3render PRIVATE ../vst3render/Main.cpp)
target_compile_definitions(vst3render PRIVATE JUCE_MODAL_LOOPS_PERMITTED=1 JUCE_PLUGINHOST_VST3=1 JUCE_PLUGINHOST_VST=0 JUCE_PLUGINHOST_AU=0 JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(vst3render PRIVATE juce::juce_audio_processors juce::juce_audio_formats juce::juce_events juce::juce_recommended_config_flags)
