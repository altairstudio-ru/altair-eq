#include "Editor.h"

namespace
{
const juce::Colour rack { 0xff242932 };
const juce::Colour face { 0xff292e37 };
const juce::Colour dark { 0xff111419 };
const juce::Colour label { 0xffc5cbd4 };
const juce::Colour secondary { 0xff8c95a1 };
const juce::Colour boostAccent { 0xffe3a857 };
const juce::Colour attenAccent { 0xff6fb3d2 };
const juce::Colour trimAccent { 0xffa7aeb8 };

void addArc(juce::Path& path, juce::Point<float> centre, float radius,
            float start, float end)
{
    constexpr int segments = 72;
    for (int i = 0; i <= segments; ++i)
    {
        const auto t = start + (end - start) * static_cast<float>(i) / segments;
        const juce::Point<float> p { centre.x + radius * std::cos(t),
                                     centre.y + radius * std::sin(t) };
        if (i == 0) path.startNewSubPath(p);
        else path.lineTo(p);
    }
}

juce::String formatFrequency(float index)
{
    constexpr int frequencies[] { 20, 30, 60, 100 };
    const auto i = juce::jlimit(0, 3, juce::roundToInt(index));
    return juce::String(frequencies[i]) + " Hz";
}

float parseFrequency(const juce::String& text)
{
    constexpr int frequencies[] { 20, 30, 60, 100 };
    const auto value = text.retainCharacters("0123456789").getIntValue();
    for (int i = 0; i < 4; ++i)
        if (value == frequencies[i]) return static_cast<float>(i);
    return static_cast<float>(juce::jlimit(0, 3, value));
}
}

void RackLookAndFeel::drawRotarySlider(juce::Graphics& g, int x, int y, int width, int height,
                                       float sliderPos, float startAngle, float endAngle,
                                       juce::Slider& slider)
{
    const auto bounds = juce::Rectangle<float>(static_cast<float>(x), static_cast<float>(y),
                                               static_cast<float>(width), static_cast<float>(height));
    const auto diameter = juce::jmin((bounds.getWidth() - 12.0f) * 0.52f, bounds.getHeight() - 18.0f);
    const auto radius = juce::jmax(10.0f, diameter * 0.5f - 5.0f);
    const auto centre = bounds.getCentre().withY(bounds.getY() + radius + 12.0f);
    const auto accent = slider.findColour(juce::Slider::rotarySliderFillColourId);
    const auto track = slider.findColour(juce::Slider::rotarySliderOutlineColourId);
    const auto valueAngle = startAngle + sliderPos * (endAngle - startAngle);

    // Machined scale and restrained value arc.
    juce::Path scale;
    addArc(scale, centre, radius + 7.0f, startAngle, endAngle);
    g.setColour(track.withAlpha(0.65f));
    g.strokePath(scale, juce::PathStrokeType(2.0f, juce::PathStrokeType::curved,
                                             juce::PathStrokeType::rounded));
    juce::Path active;
    addArc(active, centre, radius + 7.0f, startAngle, valueAngle);
    g.setColour(accent);
    g.strokePath(active, juce::PathStrokeType(3.0f, juce::PathStrokeType::curved,
                                              juce::PathStrokeType::rounded));

    const int tickCount = slider.getRange().getLength() <= 3.0 ? 4 : 11;
    for (int i = 0; i < tickCount; ++i)
    {
        const auto p = tickCount == 1 ? 0.0f : static_cast<float>(i) / (tickCount - 1);
        const auto a = startAngle + p * (endAngle - startAngle);
        const auto outer = centre + juce::Point<float>(std::cos(a), std::sin(a)) * (radius + 12.0f);
        const auto inner = centre + juce::Point<float>(std::cos(a), std::sin(a)) *
            (radius + (i % 5 == 0 || tickCount == 4 ? 4.0f : 7.0f));
        g.setColour(i % 5 == 0 || tickCount == 4 ? label.withAlpha(0.8f) : secondary.withAlpha(0.55f));
        g.drawLine(inner.x, inner.y, outer.x, outer.y,
                   i % 5 == 0 || tickCount == 4 ? 1.5f : 1.0f);
    }

    // Recessed dial, rolled metal edge, and a raised pointer cap.
    g.setColour(label);
    g.setFont(juce::Font(11.0f, juce::Font::bold));
    auto drawLimit = [&](float angle, const juce::String& text, bool left) {
        const auto tip = centre + juce::Point<float>(std::cos(angle), std::sin(angle)) * (radius + 12.0f);
        const int edge = juce::roundToInt(tip.x);
        g.drawText(text, left ? edge - 33 : edge + 2, juce::roundToInt(tip.y) - 5, 31, 14,
                   left ? juce::Justification::centredRight : juce::Justification::centredLeft);
    };
    const bool frequencyScale = tickCount == 4;
    drawLimit(startAngle, frequencyScale ? "20" : juce::String(int(slider.getMinimum())), true);
    drawLimit(endAngle, frequencyScale ? "100" : slider.getMinimum() < 0 ? "+12" : "10", false);

    const auto dial = juce::Rectangle<float>(centre.x - radius, centre.y - radius,
                                             radius * 2.0f, radius * 2.0f);
    g.setColour(juce::Colours::black.withAlpha(0.60f));
    g.fillEllipse(dial.expanded(4.0f));
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff59616d), dial.getX(), dial.getY(),
                                            juce::Colour(0xff171a20), dial.getRight(), dial.getBottom(), false));
    g.fillEllipse(dial.expanded(2.0f));
    g.setColour(juce::Colour(0xff0f1116));
    g.fillEllipse(dial);
    auto inner = dial.reduced(4.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff343a44), inner.getX(), inner.getY(),
                                            juce::Colour(0xff20242c), inner.getRight(), inner.getBottom(), false));
    g.fillEllipse(inner);
    g.setColour(juce::Colours::white.withAlpha(0.08f));
    g.drawEllipse(inner.reduced(2.0f), 1.0f);

    const auto pointerStart = centre + juce::Point<float>(std::cos(valueAngle), std::sin(valueAngle)) * (radius * 0.24f);
    const auto pointerEnd = centre + juce::Point<float>(std::cos(valueAngle), std::sin(valueAngle)) * (radius * 0.77f);
    g.setColour(juce::Colours::black.withAlpha(0.5f));
    g.drawLine(pointerStart.x + 1.2f, pointerStart.y + 1.2f,
               pointerEnd.x + 1.2f, pointerEnd.y + 1.2f, 5.0f);
    g.setColour(accent.brighter(0.15f));
    g.drawLine(pointerStart.x, pointerStart.y, pointerEnd.x, pointerEnd.y, 3.0f);
    g.setColour(juce::Colours::white.withAlpha(0.35f));
    g.fillEllipse(centre.x - 3.0f, centre.y - 3.0f, 6.0f, 6.0f);
}

void RackLookAndFeel::drawToggleButton(juce::Graphics& g, juce::ToggleButton& button,
                                       bool, bool)
{
    auto b = button.getLocalBounds().toFloat().reduced(3.0f);
    const auto on = button.getToggleState();
    auto bezel = b.withTrimmedTop(13.0f).withTrimmedBottom(2.0f);
    g.setColour(juce::Colours::black.withAlpha(0.55f));
    g.fillRoundedRectangle(bezel.translated(1.0f, 2.0f), 6.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff090b0f), bezel.getX(), bezel.getY(),
                                            juce::Colour(0xff1b1f26), bezel.getRight(), bezel.getBottom(), false));
    g.fillRoundedRectangle(bezel, 6.0f);
    g.setColour(juce::Colour(0xff4a515d));
    g.drawRoundedRectangle(bezel, 6.0f, 1.0f);

    const auto slot = bezel.withSizeKeepingCentre(54.0f, 24.0f);
    g.setColour(juce::Colour(0xff07090c));
    g.fillRoundedRectangle(slot, 5.0f);
    g.setColour(juce::Colours::white.withAlpha(0.06f));
    g.drawRoundedRectangle(slot, 5.0f, 1.0f);

    const auto led = juce::Rectangle<float>(b.getCentreX() - 4.0f, b.getY() + 1.0f, 8.0f, 8.0f);
    g.setColour(on ? juce::Colour(0xff79c267).withAlpha(0.26f) : juce::Colour(0xff080a0d));
    g.fillEllipse(led.expanded(on ? 4.0f : 1.0f));
    g.setColour(on ? juce::Colour(0xff79c267) : juce::Colour(0xff454b55));
    g.fillEllipse(led);
    if (on)
    {
        g.setColour(juce::Colour(0xffd1f5c5));
        g.fillEllipse(led.reduced(3.0f).translated(-1.0f, -1.0f));
    }

    const juce::Point<float> pivot { slot.getCentreX(), slot.getCentreY() };
    const juce::Point<float> tip { pivot.x + (on ? -19.0f : 19.0f),
                                   pivot.y + (on ? -5.0f : 5.0f) };
    g.setColour(juce::Colours::black.withAlpha(0.7f));
    g.drawLine(pivot.x + 1.5f, pivot.y + 2.0f, tip.x + 1.5f, tip.y + 2.0f, 7.0f);
    g.setColour(juce::Colour(0xff343a43));
    g.drawLine(pivot.x, pivot.y, tip.x, tip.y, 6.0f);
    g.setColour(juce::Colour(0xffc9d0d8));
    g.drawLine(pivot.x - 1.0f, pivot.y - 1.0f, tip.x - 1.0f, tip.y - 1.0f, 3.5f);
    g.setColour(juce::Colour(0xff858d98));
    g.fillEllipse(pivot.x - 6.0f, pivot.y - 6.0f, 12.0f, 12.0f);
    g.setColour(juce::Colour(0xffd8dde3));
    g.fillEllipse(pivot.x - 3.5f, pivot.y - 3.5f, 7.0f, 7.0f);
    auto cap = juce::Rectangle<float>(tip.x - 4.5f, tip.y - 4.5f, 9.0f, 9.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xffeef1f4), cap.getX(), cap.getY(),
                                            juce::Colour(0xff69717d), cap.getRight(), cap.getBottom(), false));
    g.fillEllipse(cap);

    g.setFont(juce::Font(10.0f, juce::Font::bold));
    g.setColour(on ? label : secondary);
    g.drawFittedText("ON", 0, 0, 25, 13, juce::Justification::centred, 1);
    g.setColour(on ? secondary : label);
    g.drawFittedText("OFF", button.getWidth() - 28, 0, 28, 13,
                     juce::Justification::centred, 1);
}

RackEditor::RackEditor(juce::AudioProcessor& processor, State& state)
    : juce::AudioProcessorEditor(processor)
{
    setSize(960, 300);
    setResizable(false, false);
    setLookAndFeel(&rackLook);

    configureSlider(frequency, juce::Colour(0xffd8dde5), "Low-frequency turnover: 20, 30, 60, or 100 CPS");
    frequency.setRange(0.0, 3.0, 1.0);
    frequency.setDoubleClickReturnValue(true, 1.0);
    frequency.textFromValueFunction = [](double value) { return formatFrequency(static_cast<float>(value)); };
    frequency.valueFromTextFunction = [](const juce::String& value) { return parseFrequency(value); };

    configureSlider(boost, boostAccent, "LF Boost, 0 to 10");
    boost.setRange(0.0, 10.0, 0.0);
    boost.setDoubleClickReturnValue(true, 0.0);
    boost.textFromValueFunction = [](double v) { return juce::String(v, 2); };
    boost.valueFromTextFunction = [](const juce::String& s) { return s.getDoubleValue(); };

    configureSlider(atten, attenAccent, "LF Attenuation, 0 to 10");
    atten.setRange(0.0, 10.0, 0.0);
    atten.setDoubleClickReturnValue(true, 0.0);
    atten.textFromValueFunction = [](double v) { return juce::String(v, 2); };
    atten.valueFromTextFunction = [](const juce::String& s) { return s.getDoubleValue(); };

    configureSlider(trim, trimAccent, "Output Trim, minus 12 to plus 12 decibels");
    trim.setRange(-12.0, 12.0, 0.1);
    trim.setDoubleClickReturnValue(true, 0.0);
    trim.textFromValueFunction = [](double v) {
        return juce::String(v >= 0.0 ? "+" : "") + juce::String(v, 1) + " dB";
    };
    trim.valueFromTextFunction = [](const juce::String& s) { return s.retainCharacters("0123456789+-. ,").getDoubleValue(); };

    eqIn.setName("EQ In");
    eqIn.setTitle("EQ In");
    eqIn.setDescription("Enables the LF equalizer section. This is not host bypass.");
    eqIn.setTooltip("EQ In controls the equalizer section. Host bypass is separate.");

    addAndMakeVisible(frequency);
    addAndMakeVisible(boost);
    addAndMakeVisible(atten);
    addAndMakeVisible(trim);
    addAndMakeVisible(eqIn);

    frequencyAttachment = std::make_unique<State::SliderAttachment>(state, "lfFrequency", frequency);
    boostAttachment = std::make_unique<State::SliderAttachment>(state, "lfBoost", boost);
    attenAttachment = std::make_unique<State::SliderAttachment>(state, "lfAtten", atten);
    trimAttachment = std::make_unique<State::SliderAttachment>(state, "outputTrim", trim);
    eqInAttachment = std::make_unique<State::ButtonAttachment>(state, "eqIn", eqIn);
}

RackEditor::~RackEditor()
{
    setLookAndFeel(nullptr);
    frequency.setLookAndFeel(nullptr);
    boost.setLookAndFeel(nullptr);
    atten.setLookAndFeel(nullptr);
    trim.setLookAndFeel(nullptr);
    eqIn.setLookAndFeel(nullptr);
}

void RackEditor::configureSlider(juce::Slider& slider, juce::Colour accent, const juce::String& description)
{
    slider.setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag);
    slider.setTextBoxStyle(juce::Slider::TextBoxBelow, false, 104, 32);
    slider.setRotaryParameters(juce::MathConstants<float>::pi * 0.75f,
                               juce::MathConstants<float>::pi * 2.25f, true);
    slider.setLookAndFeel(&rackLook);
    slider.setColour(juce::Slider::rotarySliderFillColourId, accent);
    slider.setColour(juce::Slider::rotarySliderOutlineColourId, juce::Colour(0xff414853));
    slider.setColour(juce::Slider::textBoxBackgroundColourId, juce::Colour(0xff101216));
    slider.setColour(juce::Slider::textBoxOutlineColourId, juce::Colour(0xff090b0e));
    slider.setColour(juce::Slider::textBoxTextColourId, juce::Colour(0xffeceef1));
    slider.setColour(juce::Slider::textBoxHighlightColourId, juce::Colour(0xff3b4655));
    slider.setTextBoxIsEditable(true);
    slider.setTitle(description);
    slider.setDescription(description);
    slider.setTooltip(description);
}

void RackEditor::drawScrew(juce::Graphics& g, juce::Point<float> p) const
{
    g.setColour(juce::Colours::black.withAlpha(0.45f));
    g.fillEllipse(p.x - 7.0f, p.y - 7.0f, 14.0f, 14.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff717986), p.x - 4.0f, p.y - 5.0f,
                                            juce::Colour(0xff242932), p.x + 5.0f, p.y + 5.0f, true));
    g.fillEllipse(p.x - 5.5f, p.y - 5.5f, 11.0f, 11.0f);
    g.setColour(juce::Colour(0xff171a20));
    g.drawLine(p.x - 2.7f, p.y + 2.7f, p.x + 2.7f, p.y - 2.7f, 1.2f);
    g.drawLine(p.x - 2.7f, p.y - 2.7f, p.x + 2.7f, p.y + 2.7f, 1.2f);
}

void RackEditor::paint(juce::Graphics& g)
{
    g.fillAll(juce::Colour(0xff0c0e12));
    auto plate = juce::Rectangle<float>(28.0f, 14.0f, 904.0f, 272.0f);
    g.setColour(juce::Colours::black.withAlpha(0.7f));
    g.fillRoundedRectangle(plate.translated(0.0f, 3.0f), 8.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff303640), plate.getX(), plate.getY(),
                                            juce::Colour(0xff20242b), plate.getRight(), plate.getBottom(), false));
    g.fillRoundedRectangle(plate, 8.0f);
    g.setColour(juce::Colour(0xff090b0f));
    g.drawRoundedRectangle(plate, 8.0f, 1.0f);
    g.setColour(juce::Colours::white.withAlpha(0.07f));
    g.drawHorizontalLine(17, 38.0f, 922.0f);

    // Rack ears, retaining the A4 faceplate without unapproved A/B/COPY/RESET controls.
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff272c34), 20.0f, 40.0f,
                                            juce::Colour(0xff171a20), 40.0f, 275.0f, false));
    g.fillRoundedRectangle(14.0f, 22.0f, 24.0f, 256.0f, 4.0f);
    g.fillRoundedRectangle(922.0f, 22.0f, 24.0f, 256.0f, 4.0f);
    drawScrew(g, { 25.0f, 48.0f }); drawScrew(g, { 25.0f, 252.0f });
    drawScrew(g, { 935.0f, 48.0f }); drawScrew(g, { 935.0f, 252.0f });
    drawScrew(g, { 44.0f, 31.0f }); drawScrew(g, { 916.0f, 31.0f });
    drawScrew(g, { 44.0f, 269.0f }); drawScrew(g, { 916.0f, 269.0f });

    // Raised nameplate and engraved header.
    auto badge = juce::Rectangle<float>(70.0f, 25.0f, 112.0f, 30.0f);
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff414853), badge.getX(), badge.getY(),
                                            juce::Colour(0xff242932), badge.getRight(), badge.getBottom(), false));
    g.fillRoundedRectangle(badge, 4.0f);
    g.setColour(juce::Colour(0xff0d1014)); g.drawRoundedRectangle(badge, 4.0f, 1.0f);
    g.setColour(juce::Colour(0xfff0f2f5)); g.setFont(juce::Font(14.0f, juce::Font::bold));
    g.drawFittedText("AltaiR EQ", badge.toNearestInt(), juce::Justification::centred, 1);
    auto chip = juce::Rectangle<float>(190.0f, 31.0f, 48.0f, 19.0f);
    g.setColour(juce::Colour(0xff15181e)); g.fillRoundedRectangle(chip, 3.0f);
    g.setColour(juce::Colour(0xffaab4c2)); g.setFont(juce::Font(9.0f, juce::Font::bold));
    g.drawFittedText("v" JucePlugin_VersionString, chip.toNearestInt(), juce::Justification::centred, 1);
    g.setColour(juce::Colour(0xff9ba3af)); g.setFont(juce::Font(10.0f, juce::Font::plain));
    g.drawText("LOW-FREQUENCY SECTION", 270, 30, 300, 18, juce::Justification::centredLeft);
    g.setColour(juce::Colour(0xff111419)); g.drawHorizontalLine(67, 38.0f, 932.0f);
    g.setColour(juce::Colours::white.withAlpha(0.06f)); g.drawHorizontalLine(68, 38.0f, 932.0f);

    constexpr int separators[] { 236, 442, 648, 800 };
    for (auto x : separators)
    {
        g.setColour(juce::Colours::black.withAlpha(0.35f)); g.drawVerticalLine(x, 74.0f, 223.0f);
        g.setColour(juce::Colours::white.withAlpha(0.06f)); g.drawVerticalLine(x + 1, 74.0f, 223.0f);
    }

    const auto heading = [&](const juce::String& text, int x, int w, juce::Colour colour)
    {
        g.setColour(colour); g.setFont(juce::Font(11.0f, juce::Font::bold));
        g.drawFittedText(text, x, 70, w, 18, juce::Justification::centred, 1);
    };
    heading("LF FREQUENCY | Hz", 48, 178, label);
    heading("BOOST", 238, 202, boostAccent);
    heading("ATTENUATION", 444, 202, attenAccent);
    heading("OUTPUT TRIM", 650, 146, trimAccent);
    heading("EQ IN", 802, 112, label);

    g.setColour(secondary); g.setFont(juce::Font(9.0f, juce::Font::plain));
    g.drawFittedText("20 | 30 | 60 | 100 Hz", 48, 211, 178, 14, juce::Justification::centred, 1);
    g.drawFittedText("SCALE 0-10", 238, 211, 202, 14, juce::Justification::centred, 1);
    g.drawFittedText("SCALE 0-10", 444, 211, 202, 14, juce::Justification::centred, 1);
    g.drawFittedText("RANGE -12 TO +12 dB", 650, 211, 146, 14, juce::Justification::centred, 1);
    g.drawFittedText("NOT HOST BYPASS", 802, 211, 112, 14, juce::Justification::centred, 1);

    auto footer = juce::Rectangle<float>(61.0f, 231.0f, 838.0f, 42.0f);
    g.setColour(dark); g.fillRoundedRectangle(footer, 5.0f);
    g.setColour(juce::Colour(0xff373d47)); g.drawRoundedRectangle(footer, 5.0f, 1.0f);
    g.setColour(secondary); g.setFont(juce::Font(9.0f, juce::Font::plain));
    g.drawText("Drag controls | Double-click to reset | Click value to type", 80, 244, 445, 16,
               juce::Justification::centredLeft);
    g.setFont(juce::Font(8.0f, juce::Font::bold));
    g.drawText("LF-1 | REV A", 738, 244, 75, 16, juce::Justification::centredRight);
    g.drawText("ZERO-LATENCY DSP", 816, 244, 72, 16, juce::Justification::centredRight);
}

void RackEditor::resized()
{
    frequency.setBounds(69, 90, 146, 118);
    boost.setBounds(267, 90, 146, 118);
    atten.setBounds(473, 90, 146, 118);
    trim.setBounds(657, 94, 134, 114);
    eqIn.setBounds(804, 105, 112, 62);
}
