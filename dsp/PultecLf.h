#pragma once

#include <array>
#include <algorithm>
#include <cmath>

// Reusable, host-independent LF filter kernel. A caller supplies a measured
// six-section model; parameter-to-model mapping is deliberately separate.
class PultecLf
{
public:
    static constexpr int sectionCount = 6;
    static constexpr int modelParameterCount = 1 + sectionCount * 4;

    struct Biquad
    {
        double b0 = 1.0, b1 = 0.0, b2 = 0.0;
        double a1 = 0.0, a2 = 0.0;
    };

    using Model = std::array<Biquad, sectionCount>;
    using RootParameters = std::array<double, modelParameterCount>;

    void prepare(double sampleRate)
    {
        rate = sampleRate;
        rampSamples = std::max(1, static_cast<int>(std::lround(sampleRate * 0.020)));
        for (auto& section : sections)
            section.reset();
        wet = targetWet = 0.0;
        wetRemaining = 0;
        outputGain = targetOutputGain = 1.0;
        outputGainRemaining = 0;
        wasWet = false;
    }

    static Model fromRootParameters(const RootParameters& p)
    {
        Model model {};
        const double gain = std::exp(p[0]);
        for (int i = 0; i < sectionCount; ++i)
        {
            const int offset = 1 + i * 4;
            const double poleRadius = p[offset];
            const double poleAngle = p[offset + 1];
            const double zeroRadius = p[offset + 2];
            const double zeroAngle = p[offset + 3];
            const double sectionGain = (i == 0 ? gain : 1.0);
            model[i] = {
                sectionGain,
                sectionGain * -2.0 * zeroRadius * std::cos(zeroAngle),
                sectionGain * zeroRadius * zeroRadius,
                -2.0 * poleRadius * std::cos(poleAngle),
                poleRadius * poleRadius
            };
        }
        return model;
    }

    static bool isStable(const Model& model)
    {
        for (const auto& c : model)
        {
            if (!std::isfinite(c.b0) || !std::isfinite(c.b1) || !std::isfinite(c.b2)
                || !std::isfinite(c.a1) || !std::isfinite(c.a2))
                return false;
            // Jury conditions for the normalized second-order denominator.
            if (!(std::abs(c.a2) < 1.0 && 1.0 + c.a1 + c.a2 > 0.0
                  && 1.0 - c.a1 + c.a2 > 0.0))
                return false;
        }
        return true;
    }

    bool setModel(const Model& next)
    {
        if (!isStable(next))
            return false;
        for (int i = 0; i < sectionCount; ++i)
            sections[i].setTarget(next[i], rampSamples);
        return true;
    }

    void setEnabled(bool enabled)
    {
        const double next = enabled ? 1.0 : 0.0;
        if (next == targetWet)
            return;
        targetWet = next;
        wetRemaining = rampSamples;
        wetStep = (targetWet - wet) / static_cast<double>(rampSamples);
    }

    void setOutputTrimDb(double decibels)
    {
        const double bounded = std::clamp(decibels, -12.0, 12.0);
        const double next = std::pow(10.0, bounded / 20.0);
        if (next == targetOutputGain)
            return;
        targetOutputGain = next;
        outputGainRemaining = rampSamples;
        outputGainStep = (targetOutputGain - outputGain) / static_cast<double>(rampSamples);
    }

    void process(float& left, float& right)
    {
        for (auto& section : sections)
            section.advance();
        if (wetRemaining > 0)
        {
            wet += wetStep;
            if (--wetRemaining == 0)
                wet = targetWet;
        }
        if (outputGainRemaining > 0)
        {
            outputGain += outputGainStep;
            if (--outputGainRemaining == 0)
                outputGain = targetOutputGain;
        }
        if (wet == 0.0)
        {
            if (wasWet)
                for (auto& section : sections)
                    section.clearState();
            wasWet = false;
        }
        else
        {
            wasWet = true;
            double filteredLeft = left;
            double filteredRight = right;
            for (auto& section : sections)
            {
                filteredLeft = section.process(filteredLeft, 0);
                filteredRight = section.process(filteredRight, 1);
            }
            left = static_cast<float>(left + wet * (filteredLeft - left));
            right = static_cast<float>(right + wet * (filteredRight - right));
        }
        left = static_cast<float>(left * outputGain);
        right = static_cast<float>(right * outputGain);
    }

    double sampleRate() const { return rate; }

private:
    struct Filter
    {
        Biquad current {}, target {};
        std::array<double, 5> step {};
        std::array<double, 2> z1 {}, z2 {};
        int remaining = 0;

        void reset()
        {
            current = target = {};
            current.b0 = target.b0 = 1.0;
            step = {};
            clearState();
            remaining = 0;
        }

        void setTarget(const Biquad& next, int ramp)
        {
            target = next;
            remaining = ramp;
            const std::array<double, 5> from {current.b0,current.b1,current.b2,current.a1,current.a2};
            const std::array<double, 5> to {target.b0,target.b1,target.b2,target.a1,target.a2};
            for (int i = 0; i < 5; ++i)
                step[i] = (to[i] - from[i]) / static_cast<double>(ramp);
        }

        void advance()
        {
            if (remaining <= 0)
                return;
            current.b0 += step[0]; current.b1 += step[1]; current.b2 += step[2];
            current.a1 += step[3]; current.a2 += step[4];
            if (--remaining == 0)
                current = target;
        }

        double process(double input, int channel)
        {
            const double output = current.b0 * input + z1[channel];
            z1[channel] = current.b1 * input - current.a1 * output + z2[channel];
            z2[channel] = current.b2 * input - current.a2 * output;
            return output;
        }

        void clearState() { z1 = {}; z2 = {}; }
    };

    std::array<Filter, sectionCount> sections {};
    double rate = 48000.0;
    double wet = 0.0, targetWet = 0.0, wetStep = 0.0;
    double outputGain = 1.0, targetOutputGain = 1.0, outputGainStep = 0.0;
    int rampSamples = 960, wetRemaining = 0, outputGainRemaining = 0;
    bool wasWet = false;
};
