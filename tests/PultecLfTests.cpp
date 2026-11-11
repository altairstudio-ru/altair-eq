#include "PultecLf.h"
#include "PultecLfRuntimeGolden.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace
{
constexpr double sampleRate = 44100.0;
constexpr double pi = 3.14159265358979323846;

void check(bool ok, const char* message)
{
    if (!ok)
        throw std::runtime_error(message);
}

struct Transfer
{
    double magnitudeDb;
    double phaseDegrees;
};

template <size_t N>
Transfer renderSine(const PultecLf::RootParameters& roots,
                    const std::array<PultecLfGolden::Sample, N>& goldens,
                    size_t index)
{
    PultecLf eq;
    eq.prepare(sampleRate);
    const auto model = PultecLf::fromRootParameters(roots);
    check(PultecLf::isStable(model), "measured SOS model is stable");
    check(eq.setModel(model), "valid model accepted");
    eq.setEnabled(true);

    const auto frequency = goldens[index].frequency;
    const int warmup = static_cast<int>(sampleRate);
    const int capture = static_cast<int>(sampleRate);
    double sineProjection = 0.0, cosineProjection = 0.0, inputEnergy = 0.0;
    for (int i = 0; i < warmup + capture; ++i)
    {
        const double phase = 2.0 * pi * frequency * i / sampleRate;
        const float input = static_cast<float>(0.1 * std::sin(phase));
        float left = input;
        float right = -input;
        eq.process(left, right);
        check(std::isfinite(left) && std::abs(left + right) < 1.0e-6f,
              "finite output and independent symmetric stereo channels");
        if (i >= warmup)
        {
            sineProjection += static_cast<double>(left) * std::sin(phase);
            cosineProjection += static_cast<double>(left) * std::cos(phase);
            inputEnergy += static_cast<double>(input) * input;
        }
    }
    const double sine = 2.0 * sineProjection / capture;
    const double cosine = 2.0 * cosineProjection / capture;
    const double amplitude = std::hypot(sine, cosine);
    return {20.0 * std::log10(amplitude / std::sqrt(2.0 * inputEnergy / capture)),
            std::atan2(cosine, sine) * 180.0 / pi};
}

template <size_t N>
void compareGolden(const PultecLf::RootParameters& roots,
                   const std::array<PultecLfGolden::Sample, N>& values)
{
    for (size_t i = 0; i < N; ++i)
    {
        const auto actual = renderSine(roots, values, i);
        check(std::abs(actual.magnitudeDb - values[i].magnitudeDb) <= 0.12,
              "runtime magnitude matches measured sweep golden");
        check(std::abs(std::remainder(actual.phaseDegrees - values[i].phaseDegrees, 360.0)) <= 1.9,
              "runtime phase matches measured sweep golden");
    }
}
}

int main()
{
    try
    {
        compareGolden(PultecLfGolden::flatModel, PultecLfGolden::flat);
        compareGolden(PultecLfGolden::boostModel, PultecLfGolden::boostCps60B6);

        PultecLf eq;
        eq.prepare(sampleRate);
        auto invalid = PultecLf::fromRootParameters(PultecLfGolden::flatModel);
        invalid[0].a2 = 1.01;
        check(!eq.setModel(invalid), "unstable model rejected");

        auto valid = PultecLf::fromRootParameters(PultecLfGolden::boostModel);
        check(eq.setModel(valid), "valid model accepted for coefficient ramp");
        eq.setEnabled(true);
        for (int i = 0; i < static_cast<int>(sampleRate * 0.05); ++i)
        {
            float left = 0.25f, right = -0.125f;
            eq.process(left, right);
            check(std::isfinite(left) && std::isfinite(right), "model ramp remains finite");
        }
        eq.setEnabled(false);
        for (int i = 0; i < static_cast<int>(sampleRate * 0.021); ++i)
        {
            float left = 0.123f, right = -0.321f;
            eq.process(left, right);
        }
        float left = 0.123f, right = -0.321f;
        eq.process(left, right);
        check(left == 0.123f && right == -0.321f, "EQ In dry endpoint is bit-transparent");

        eq.setOutputTrimDb(6.0);
        for (int i = 0; i < static_cast<int>(sampleRate * 0.021); ++i)
        {
            float l = 0.0f, r = 0.0f;
            eq.process(l, r);
        }
        left = 0.25f; right = -0.125f;
        eq.process(left, right);
        check(std::abs(left / 0.25f - std::pow(10.0f, 6.0 / 20.0)) < 1.0e-6f,
              "Output Trim gain matches decibel setting with EQ In off");

        std::cout << "PASS: Pultec LF runtime kernel, measured goldens, stability, stereo and bypass\n";
        return 0;
    }
    catch (const std::exception& e)
    {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
