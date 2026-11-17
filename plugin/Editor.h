#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

class RackLookAndFeel final : public juce::LookAndFeel_V4
{
public:
    void drawRotarySlider(juce::Graphics&, int, int, int, int, float, float, float,
                          juce::Slider&) override;
    void drawToggleButton(juce::Graphics&, juce::ToggleButton&, bool, bool) override;
};

class RackEditor final : public juce::AudioProcessorEditor
{
public:
    using State = juce::AudioProcessorValueTreeState;

    RackEditor(juce::AudioProcessor&, State&);
    ~RackEditor() override;

    void paint(juce::Graphics&) override;
    void resized() override;

private:
    RackLookAndFeel rackLook;
    juce::Slider frequency, boost, atten, trim;
    juce::ToggleButton eqIn { "EQ IN" };
    std::unique_ptr<State::SliderAttachment> frequencyAttachment, boostAttachment,
        attenAttachment, trimAttachment;
    std::unique_ptr<State::ButtonAttachment> eqInAttachment;

    void configureSlider(juce::Slider&, juce::Colour, const juce::String&);
    void drawScrew(juce::Graphics&, juce::Point<float>) const;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(RackEditor)
};
