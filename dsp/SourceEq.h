#pragma once
#include <array>
#include <algorithm>
#include <cmath>

// Shared stereo DSP component. No host/UI dependencies or audio-thread allocation.
class SourceEq
{
    struct Filter
    {
        std::array<double, 5> current {1, 0, 0, 0, 0}, target {1, 0, 0, 0, 0}, step {};
        std::array<double, 2> z1 {}, z2 {};
        int remaining = 0;
        void set(const std::array<double, 5>& c, int ramp)
        { target = c; remaining = ramp; for (int i = 0; i < 5; ++i) step[i] = (c[i] - current[i]) / ramp; }
        void advance()
        { if (remaining > 0) { for (int i = 0; i < 5; ++i) current[i] += step[i]; if (--remaining == 0) current = target; } }
        double sample(double x, int ch)
        {
            const auto y = current[0] * x + z1[ch];
            z1[ch] = current[1] * x - current[3] * y + z2[ch];
            z2[ch] = current[2] * x - current[4] * y;
            return y;
        }
        void clear() { z1 = {}; z2 = {}; }
    };
public:
    void prepare(double sr)
    { rate = sr; ramp = std::max(1, int(sr * 0.02)); filters = {}; previous = {100, 100, 100}; wet = targetWet = 0; wetRemaining = 0; wasWet = false; }
    void configure(bool enabled, const std::array<float, 3>& gains)
    {
        const double nextWet = enabled ? 1 : 0;
        if (nextWet != targetWet) { targetWet = nextWet; wetRemaining = ramp; wetStep = (targetWet - wet) / ramp; }
        for (int i = 0; i < 3; ++i)
        {
            const double gain = std::clamp(double(gains[i]), -6.0, 6.0);
            if (gain != previous[i]) { previous[i] = gain; filters[i].set(coefficients(i, gain), ramp); }
        }
    }
    void process(float& left, float& right)
    {
        if (wetRemaining > 0) { wet += wetStep; if (--wetRemaining == 0) wet = targetWet; }
        if (wet == 0) { if (wasWet) for (auto& f : filters) f.clear(); wasWet = false; return; }
        wasWet = true;
        double l = left, r = right;
        for (auto& f : filters) { f.advance(); l = f.sample(l, 0); r = f.sample(r, 1); }
        left = float(left + wet * (l - left)); right = float(right + wet * (r - right));
    }
private:
    std::array<double, 5> coefficients(int band, double gain) const
    {
        if (gain == 0) return {1, 0, 0, 0, 0};
        const double frequencies[] = {150, 1000, 6000};
        const auto w = 2 * 3.14159265358979323846 * std::min(frequencies[band], rate * 0.45) / rate;
        const auto a = std::pow(10.0, gain / 40), c = std::cos(w), s = std::sin(w);
        double b0, b1, b2, a0, a1, a2;
        if (band == 1)
        {
            const auto alpha = s / (2 * 0.7071067811865476);
            b0 = 1 + alpha * a; b1 = -2 * c; b2 = 1 - alpha * a;
            a0 = 1 + alpha / a; a1 = -2 * c; a2 = 1 - alpha / a;
        }
        else
        {
            const auto t = std::sqrt(2 * a) * s;
            if (band == 0)
            {
                b0 = a * ((a + 1) - (a - 1) * c + t); b1 = 2 * a * ((a - 1) - (a + 1) * c);
                b2 = a * ((a + 1) - (a - 1) * c - t);
                a0 = (a + 1) + (a - 1) * c + t; a1 = -2 * ((a - 1) + (a + 1) * c); a2 = (a + 1) + (a - 1) * c - t;
            }
            else
            {
                b0 = a * ((a + 1) + (a - 1) * c + t); b1 = -2 * a * ((a - 1) + (a + 1) * c);
                b2 = a * ((a + 1) + (a - 1) * c - t);
                a0 = (a + 1) - (a - 1) * c + t; a1 = 2 * ((a - 1) - (a + 1) * c); a2 = (a + 1) - (a - 1) * c - t;
            }
        }
        return {b0/a0, b1/a0, b2/a0, a1/a0, a2/a0};
    }
    std::array<Filter, 3> filters;
    std::array<double, 3> previous {100, 100, 100};
    double rate = 48000, wet = 0, targetWet = 0, wetStep = 0;
    int ramp = 960, wetRemaining = 0;
    bool wasWet = false;
};
