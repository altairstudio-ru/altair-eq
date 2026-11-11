// Calibration VST3: one RBJ peaking biquad, f0=1000 Hz, +6 dB, Q=1.0, zero latency.
#include <juce_audio_processors/juce_audio_processors.h>
#include <array>
#include <cmath>

class CalFilterProcessor : public juce::AudioProcessor
{
public:
    CalFilterProcessor()
        : AudioProcessor (BusesProperties()
              .withInput ("Input", juce::AudioChannelSet::stereo(), true)
              .withOutput ("Output", juce::AudioChannelSet::stereo(), true)) {}

    const juce::String getName() const override { return "AltaiR CalFilter"; }
    double getTailLengthSeconds() const override { return 0.0; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool hasEditor() const override { return false; }
    juce::AudioProcessorEditor* createEditor() override { return nullptr; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}
    void getStateInformation (juce::MemoryBlock&) override {}
    void setStateInformation (const void*, int) override {}

    void prepareToPlay (double sampleRate, int) override
    {
        // RBJ Audio EQ Cookbook, peakingEQ; Q = 1 -> alpha = sin(w0)/2.
        const double A = std::pow (10.0, 6.0 / 40.0);
        const double w0 = 2.0 * juce::MathConstants<double>::pi * 1000.0 / sampleRate;
        const double alpha = std::sin (w0) / 2.0;
        const double cw = std::cos (w0);
        const double a0 = 1.0 + alpha / A;
        b0 = (1.0 + alpha * A) / a0;
        b1 = (-2.0 * cw) / a0;
        b2 = (1.0 - alpha * A) / a0;
        a1 = (-2.0 * cw) / a0;
        a2 = (1.0 - alpha / A) / a0;
        reset();
    }

    void releaseResources() override { reset(); }

    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) override
    {
        for (int ch = 0; ch < juce::jmin (2, buffer.getNumChannels()); ++ch)
        {
            auto* x = buffer.getWritePointer (ch);
            auto& s = state[(size_t) ch];
            for (int n = 0; n < buffer.getNumSamples(); ++n)
            {
                const double in = x[n];
                const double out = b0 * in + b1 * s.x1 + b2 * s.x2 - a1 * s.y1 - a2 * s.y2;
                s.x2 = s.x1; s.x1 = in;
                s.y2 = s.y1; s.y1 = out;
                x[n] = static_cast<float> (out);
            }
        }
    }

private:
    struct BiquadState { double x1 = 0, x2 = 0, y1 = 0, y2 = 0; };
    void reset() { for (auto& s : state) s = {}; }
    std::array<BiquadState, 2> state;
    double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CalFilterProcessor)
};

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new CalFilterProcessor(); }