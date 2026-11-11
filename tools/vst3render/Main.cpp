// Offline stereo WAV renderer. No audio device or editor is opened.
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <iostream>
#include <cmath>
#include <thread>
using namespace juce;

int main (int argc, char** argv)
{
    ScopedJuceInitialiser_GUI init;
    if (argc < 4) { std::cerr << "usage: vst3render <plugin.vst3|transparent> <input.wav> <output.wav> [index=normalized ...] [--realtime] [--require-latency=N]\n"; return 2; }
    int requiredLatency = -1;
    for (int i = 4; i < argc; ++i)
    {
        const String arg (argv[i]);
        if (arg.startsWith ("--require-latency="))
        {
            const auto text = arg.fromFirstOccurrenceOf ("=", false, false);
            if (text.isEmpty() || !text.containsOnly ("0123456789")) return 6;
            requiredLatency = text.getIntValue();
        }
    }
    AudioFormatManager audio; audio.registerBasicFormats();
    std::unique_ptr<AudioFormatReader> reader (audio.createReaderFor (File (String::fromUTF8 (argv[2]))));
    if (!reader || reader->lengthInSamples <= 0 || reader->lengthInSamples > 100000000 || reader->numChannels != 2) return 3;
    const int block = 512;
    AudioPluginFormatManager formats; formats.addFormat (new VST3PluginFormat());
    std::unique_ptr<AudioPluginInstance> processor;
    PluginDescription description;
    if (String (argv[1]) != "transparent")
    {
        OwnedArray<PluginDescription> descriptions;
        formats.getFormats()[0]->findAllTypesForFile (descriptions, String::fromUTF8 (argv[1]));
        if (descriptions.size() != 1) return 4;
        description = *descriptions[0]; String error;
        processor = formats.createPluginInstance (description, reader->sampleRate, block, error);
        if (!processor) { std::cerr << error << '\n'; return 5; }
        processor->enableAllBuses();
        if (processor->getTotalNumInputChannels() != 2 || processor->getTotalNumOutputChannels() != 2) return 13;
        processor->setRateAndBufferSizeDetails (reader->sampleRate, block);
        bool realtime = false;
        for (int i = 4; i < argc; ++i) if (String (argv[i]) == "--realtime") realtime = true;
        processor->setNonRealtime (!realtime);
        for (int i = 4; i < argc; ++i)
        {
            const String arg (argv[i]);
            if (arg == "--realtime") continue;
            if (arg.startsWith ("--require-latency=")) continue;
            const auto indexText = arg.upToFirstOccurrenceOf ("=", false, false);
            const auto valueText = arg.fromFirstOccurrenceOf ("=", false, false);
            const bool formattedDb = indexText.endsWithIgnoreCase ("db");
            const auto pureIndex = formattedDb ? indexText.dropLastCharacters (2) : indexText;
            if (!arg.containsChar ('=') || pureIndex.isEmpty() || !pureIndex.containsOnly ("0123456789") || valueText.isEmpty() || !valueText.containsOnly ("0123456789.eE+-")) return 6;
            const int index = pureIndex.getIntValue(); const float value = valueText.getFloatValue();
            if (index < 0 || index >= processor->getParameters().size() || !std::isfinite (value)) return 6;
            auto* parameter = processor->getParameters()[index];
            if (formattedDb)
            {
                if (value < -12.0f || value > 12.0f) return 6;
                float bestNorm = 0.0f, bestError = 1.0e6f;
                for (int probe = 1; probe <= 10000; ++probe)
                {
                    const float normalized = static_cast<float> (probe) / 10000.0f;
                    const auto formatted = parameter->getText (normalized, 64);
                    if (formatted.containsIgnoreCase ("OFF")) continue;
                    const float displayed = formatted.getDoubleValue();
                    const float error = std::abs (displayed - value);
                    if (error < bestError) { bestError = error; bestNorm = normalized; }
                }
                if (bestError > 0.051f) return 6;
                parameter->setValueNotifyingHost (bestNorm);
            }
            else
            {
                if (value < 0 || value > 1) return 6;
                parameter->setValueNotifyingHost (value);
            }
        }
        processor->releaseResources();
        processor->prepareToPlay (reader->sampleRate, block);
        std::cerr << "prepared, latency=" << processor->getLatencySamples() << std::endl;
        if (requiredLatency >= 0 && processor->getLatencySamples() != requiredLatency)
        {
            std::cerr << "latency gate failed; no measurement written\n";
            processor->releaseResources();
            return 14;
        }
    }
    else if (argc != 4) return 6;
    File output (String::fromUTF8 (argv[3]));
    if (output.existsAsFile()) { std::cerr << "output exists\n"; return 7; }
    output.getParentDirectory().createDirectory();
    auto stream = output.createOutputStream(); WavAudioFormat wav;
    std::unique_ptr<AudioFormatWriter> writer (wav.createWriterFor (stream.get(), reader->sampleRate, 2, 32, {}, 0));
    if (!writer) return 8;
    stream.release();
    int renderError = 0;
    auto render = [&]() -> int
    {
    AudioBuffer<float> buffer (2, block); MidiBuffer midi;
    // One second of silence allows parameter smoothing and startup to settle.
    if (processor) for (int n = 0; n < static_cast<int> (std::ceil (reader->sampleRate / block)); ++n)
    { buffer.clear(); midi.clear(); processor->processBlock (buffer, midi); }
    for (int64 position = 0; position < reader->lengthInSamples; position += block)
    {
        const int count = static_cast<int> (jmin (int64 (block), reader->lengthInSamples - position));
        buffer.clear();
        if (!reader->read (&buffer, 0, count, position, true, true)) return 9;
        if (processor) { midi.clear(); processor->processBlock (buffer, midi); }
        for (int c = 0; c < 2; ++c) for (int n = 0; n < count; ++n)
            if (!std::isfinite (buffer.getSample (c, n))) return 10;
        if (!writer->writeFromAudioSampleBuffer (buffer, 0, count)) return 11;
    }
    return 0;
    };
    // VST3 processing belongs on an audio thread; keep the host message loop alive.
    std::thread audioThread ([&]
    {
        Thread::sleep (1000);
        renderError = render();
        MessageManager::callAsync ([] { MessageManager::getInstance()->stopDispatchLoop(); });
    });
    MessageManager::getInstance()->runDispatchLoop();
    audioThread.join();
    if (renderError != 0) return renderError;
    writer.reset();
    auto* report = new DynamicObject();
    report->setProperty ("schema", "altair-eq.render/1");
    report->setProperty ("created_utc", Time::getCurrentTime().toISO8601 (true));
    report->setProperty ("plugin_file", String::fromUTF8 (argv[1]));
    report->setProperty ("plugin_version", description.version);
    report->setProperty ("sample_rate_hz", reader->sampleRate);
    report->setProperty ("block_size", block);
    report->setProperty ("samples", reader->lengthInSamples);
    report->setProperty ("latency_samples_reported", processor ? processor->getLatencySamples() : 0);
    report->setProperty ("latency_compensated", false);
    report->setProperty ("non_realtime", processor ? processor->isNonRealtime() : false);
    report->setProperty ("required_latency_samples", requiredLatency);
    var parameters;
    if (processor) for (auto* p : processor->getParameters())
    { auto* item = new DynamicObject(); item->setProperty ("index", p->getParameterIndex()); item->setProperty ("name", p->getName (128)); item->setProperty ("normalized", p->getValue()); item->setProperty ("text", p->getCurrentValueAsText()); parameters.append (var (item)); }
    report->setProperty ("parameters", parameters);
    const File input (String::fromUTF8 (argv[2]));
    report->setProperty ("input_file", input.getFullPathName());
    report->setProperty ("output_file", output.getFullPathName());
    if (processor) processor->releaseResources();
    if (!output.withFileExtension (".json").replaceWithText (JSON::toString (var (report)))) return 12;
    std::cout << "rendered: " << output.getFullPathName() << '\n';
    return 0;
}
