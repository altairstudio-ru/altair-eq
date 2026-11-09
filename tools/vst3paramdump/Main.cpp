// AltaiR EQ — headless VST3 parameter dump (stage 2, docs/WORK_PLAN_PULTEC_MVP.md).
// Loads a .vst3 directly (no DAW, no audio device, no UI) and writes a JSON passport
// fragment: parameter ranges, steps, discreteness, formatted values, quantization probe,
// latency. Successful init of a licensed UADx plugin is itself evidence of an active license.
//
// usage: vst3paramdump <plugin.vst3> [out.json]

#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_events/juce_events.h>

#include <cmath>
#include <iostream>
#include <memory>

using namespace juce;

static var parameterToVar (AudioProcessorParameter* p, int index)
{
    auto* ranged = dynamic_cast<RangedAudioParameter*> (p);
    auto* obj = new DynamicObject();
    obj->setProperty ("index", index);
    obj->setProperty ("id", ranged != nullptr ? ranged->getParameterID() : String());
    obj->setProperty ("name", p->getName (128));
    obj->setProperty ("label", p->getLabel());
    obj->setProperty ("default_value", p->getDefaultValue());
    obj->setProperty ("current_value", p->getValue());
    obj->setProperty ("num_steps", p->getNumSteps());
    obj->setProperty ("is_discrete", p->isDiscrete());
    obj->setProperty ("is_boolean", p->isBoolean());
    obj->setProperty ("is_meta", p->isMetaParameter());
    obj->setProperty ("is_automatable", p->isAutomatable());
    obj->setProperty ("current_text", p->getCurrentValueAsText());
    obj->setProperty ("default_text", p->getText (p->getDefaultValue(), 64));

    if (ranged != nullptr)
    {
        const auto range = ranged->getNormalisableRange();
        obj->setProperty ("range_start", range.start);
        obj->setProperty ("range_end", range.end);
        obj->setProperty ("range_interval", range.interval);
    }

    var valueStrings;
    for (const auto& s : p->getAllValueStrings())
        valueStrings.append (s);
    obj->setProperty ("value_strings", valueStrings);

    // Quantization probe: walk a fine normalized grid, record distinct formatted texts.
    // Hosted VST3 parameters echo the set normalized value on read-back, so the step law
    // is only visible in the formatted text domain.
    const float original = p->getValue();
    Array<var> quantized;
    String lastText;
    bool haveLast = false;
    for (int i = 0; i <= 1000; ++i)
    {
        p->setValue (static_cast<float> (i) / 1000.0f);
        const float q = p->getValue();
        const String t = p->getText (q, 64);
        if (! haveLast || t != lastText)
        {
            auto* stepObj = new DynamicObject();
            stepObj->setProperty ("probe_index", i);
            stepObj->setProperty ("normalized", q);
            stepObj->setProperty ("text", t);
            quantized.add (var (stepObj));
            lastText = t;
            haveLast = true;
        }
    }
    p->setValue (original);
    if (p->isDiscrete() || quantized.size() <= 40)
    {
        obj->setProperty ("quantized_steps", quantized);
    }
    else
    {
        // Continuous knob: storing all 1001 probe read-backs would bloat the passport.
        auto* qobj = new DynamicObject();
        qobj->setProperty ("continuous", true);
        qobj->setProperty ("distinct_on_probe_grid", quantized.size());
        var sample;
        for (int i = 0; i < quantized.size(); ++i)
            if (i < 3 || i >= quantized.size() - 3)
                sample.append (quantized.getReference (i));
        qobj->setProperty ("sample", sample);
        obj->setProperty ("quantized_steps", var (qobj));
    }

    return var (obj);
}

int main (int argc, char* argv[])
{
    ScopedJuceInitialiser_GUI initializer;

    if (argc < 2)
    {
        std::cerr << "usage: vst3paramdump <plugin.vst3> [out.json]" << std::endl;
        return 2;
    }

    const File pluginFile (String::fromUTF8 (argv[1]));
    File outFile (argc > 2 ? String::fromUTF8 (argv[2]) : String ("vst3_dump.json"));

    AudioPluginFormatManager formats;
    formats.addFormat (new VST3PluginFormat());

    OwnedArray<PluginDescription> descs;
    for (auto* format : formats.getFormats())
    {
        if (format->canScanForPlugins()
            && format->fileMightContainThisPluginType (pluginFile.getFullPathName()))
        {
            format->findAllTypesForFile (descs, pluginFile.getFullPathName());
        }
    }

    if (descs.size() == 0)
    {
        std::cerr << "no plugin descriptions found for: " << pluginFile.getFullPathName().toStdString() << std::endl;
        return 3;
    }

    auto* root = new DynamicObject();
    root->setProperty ("schema", "altair-eq.vst3-dump/1");
    root->setProperty ("created_utc", Time::getCurrentTime().toISO8601 (true));
    root->setProperty ("tool", "vst3paramdump: headless JUCE host, no DAW, no audio device");
    root->setProperty ("plugin_file", pluginFile.getFullPathName());
    root->setProperty ("sample_rate_hz", 44100.0);
    root->setProperty ("block_size", 512);

    var plugins;
    int okCount = 0;
    for (auto* desc : descs)
    {
        auto* pobj = new DynamicObject();
        pobj->setProperty ("name", desc->name);
        pobj->setProperty ("manufacturer", desc->manufacturerName);
        pobj->setProperty ("category", desc->category);
        pobj->setProperty ("plugin_format", desc->pluginFormatName);
        pobj->setProperty ("unique_id", desc->uniqueId);
        pobj->setProperty ("version_string", desc->version);

        String message;
        std::unique_ptr<AudioProcessor> proc = formats.createPluginInstance (*desc, 44100.0, 512, message);
        if (proc == nullptr)
        {
            pobj->setProperty ("init_ok", false);
            pobj->setProperty ("init_error", message);
            plugins.append (var (pobj));
            continue;
        }

        ++okCount;
        pobj->setProperty ("init_ok", true);
        pobj->setProperty ("processor_name", proc->getName());
        pobj->setProperty ("latency_samples", static_cast<int> (proc->getLatencySamples()));
        pobj->setProperty ("parameter_count", proc->getParameters().size());

        var params;
        int paramIndex = 0;
        for (auto* p : proc->getParameters())
            params.append (parameterToVar (p, paramIndex++));
        pobj->setProperty ("parameters", params);

        plugins.append (var (pobj));
    }
    root->setProperty ("plugins", plugins);

    const String json = JSON::toString (var (root), false);
    if (! outFile.replaceWithText (json, false, false, "\n"))
    {
        std::cerr << "failed to write: " << outFile.getFullPathName().toStdString() << std::endl;
        return 4;
    }

    std::cout << "dump written: " << outFile.getFullPathName().toStdString() << std::endl;
    std::cout << "descriptions: " << descs.size() << ", init ok: " << okCount << std::endl;
    return okCount > 0 ? 0 : 5;
}
