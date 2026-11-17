#include <juce_audio_processors/juce_audio_processors.h>
#include "FrozenLfBank.h"
#include "Editor.h"

namespace {
using State = juce::AudioProcessorValueTreeState;

State::ParameterLayout parameters()
{
    using ID = juce::ParameterID;
    State::ParameterLayout layout;
    layout.add(std::make_unique<juce::AudioParameterChoice>(ID{"lfFrequency", 1}, "LF Frequency",
        juce::StringArray{"20", "30", "60", "100"}, 1));
    auto control = [&](const char* id, const char* name, float low, float high, float step, int digits) {
        auto format = juce::AudioParameterFloatAttributes().withStringFromValueFunction(
            [digits](float value, int) { return juce::String(value, digits); });
        layout.add(std::make_unique<juce::AudioParameterFloat>(ID{id, 1}, name,
            juce::NormalisableRange<float>{low, high, step}, 0.f, format));
    };
    control("lfBoost", "LF Boost", 0, 10, 0, 2);
    control("lfAtten", "LF Attenuation", 0, 10, 0, 2);
    layout.add(std::make_unique<juce::AudioParameterBool>(ID{"eqIn", 1}, "EQ In", true));
    control("outputTrim", "Output Trim (dB)", -12, 12, 0.1f, 1);
    layout.add(std::make_unique<juce::AudioParameterBool>(ID{"bypass", 1}, "Bypass", false));
    return layout;
}

class Processor final : public juce::AudioProcessor {
    State state{*this, nullptr, "AltairEqLF", parameters()};
    std::atomic<float>* frequency = state.getRawParameterValue("lfFrequency");
    std::atomic<float>* boost = state.getRawParameterValue("lfBoost");
    std::atomic<float>* atten = state.getRawParameterValue("lfAtten");
    std::atomic<float>* enabled = state.getRawParameterValue("eqIn");
    std::atomic<float>* trim = state.getRawParameterValue("outputTrim");
    std::atomic<float>* bypass = state.getRawParameterValue("bypass");
    altair::lf::FrozenLfBank bank;
    bool ready = false;
    int lastCps = -1;
    float lastBoost = -1, lastAtten = -1;

    void render(juce::AudioBuffer<float>& buffer, bool dry)
    {
        if (!ready || buffer.getNumChannels() == 0) return;
        constexpr int frequencies[] = {20, 30, 60, 100};
        const int cps = frequencies[juce::jlimit(0, 3, juce::roundToInt(frequency->load()))];
        const float b = boost->load(), a = atten->load();
        if (cps != lastCps || b != lastBoost || a != lastAtten) {
            bank.setControls(cps, b, a);
            lastCps = cps;
            lastBoost = b;
            lastAtten = a;
        }
        bank.setEnabled(enabled->load() >= 0.5f);
        bank.setTrimDb(trim->load());
        auto* left = buffer.getWritePointer(0);
        auto* right = buffer.getNumChannels() == 2 ? buffer.getWritePointer(1) : nullptr;
        for (int i = 0; i < buffer.getNumSamples(); ++i) {
            double l = left[i], r = right ? right[i] : 0.0;
            bank.process(l, r, dry);
            left[i] = static_cast<float>(l);
            if (right) right[i] = static_cast<float>(r);
        }
    }
public:
    Processor() : AudioProcessor(BusesProperties().withInput("Input", juce::AudioChannelSet::stereo(), true)
                                                  .withOutput("Output", juce::AudioChannelSet::stereo(), true)) {}
    const juce::String getName() const override { return "AltaiR EQ LF"; }
    bool isBusesLayoutSupported(const BusesLayout& layout) const override {
        auto out = layout.getMainOutputChannelSet();
        return out == layout.getMainInputChannelSet()
            && (out == juce::AudioChannelSet::mono() || out == juce::AudioChannelSet::stereo());
    }
    void prepareToPlay(double rate, int) override {
        ready = (rate == 44100 || rate == 48000 || rate == 96000) && bank.prepare(static_cast<int>(rate));
        lastCps = -1;
    }
    void releaseResources() override { ready = false; }
    void reset() override { if (ready) prepareToPlay(getSampleRate(), getBlockSize()); }
    void processBlock(juce::AudioBuffer<float>& b, juce::MidiBuffer&) override { render(b, bypass->load() >= 0.5f); }
    void processBlockBypassed(juce::AudioBuffer<float>& b, juce::MidiBuffer&) override { render(b, true); }
    juce::AudioProcessorParameter* getBypassParameter() const override { return state.getParameter("bypass"); }
    bool hasEditor() const override { return true; }
    juce::AudioProcessorEditor* createEditor() override { return new RackEditor(*this, state); }
    void getStateInformation(juce::MemoryBlock& out) override {
        auto tree = state.copyState();
        tree.setProperty("version", 1, nullptr);
        if (auto xml = tree.createXml()) copyXmlToBinary(*xml, out);
    }
    void setStateInformation(const void* bytes, int size) override {
        if (auto xml = getXmlFromBinary(bytes, size)) {
            auto tree = juce::ValueTree::fromXml(*xml);
            if (tree.hasType("AltairEqLF") && int(tree.getProperty("version", 0)) == 1)
                state.replaceState(tree);
        }
    }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.5; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return {}; }
    void changeProgramName(int, const juce::String&) override {}
};
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new Processor(); }
