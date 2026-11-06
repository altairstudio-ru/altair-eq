#include "SourceEq.h"
#include <iostream>
#include <stdexcept>

void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main()
{
    try {
        for (double rate : {44100.0, 48000.0, 96000.0}) {
            for (int band = 0; band < 3; ++band) {
                SourceEq eq; eq.prepare(rate);
                std::array<float, 3> gains {}; gains[band] = 6;
                eq.configure(true, gains);
                const double frequencies[] = {35, 1000, 16000};
                double input = 0, output = 0;
                for (int i = 0; i < int(rate); ++i) {
                    float x = float(0.1 * std::sin(2 * 3.141592653589793 * frequencies[band] * i / rate));
                    float l = x, r = -x; eq.process(l, r);
                    check(std::isfinite(l) && std::abs(l + r) < 1e-6f, "stereo symmetry");
                    if (i > int(rate / 2)) { input += double(x) * x; output += double(l) * l; }
                }
                double db = 10 * std::log10(output / input);
                check(db > 5.7 && db < 6.1, "band gain response");
                eq.configure(false, gains);
                for (int i = 0; i < int(rate * 0.03); ++i) { float l = 0.1f, r = -0.2f; eq.process(l, r); }
                float l = 0.123f, r = -0.321f; eq.process(l, r);
                check(l == 0.123f && r == -0.321f, "dry after bypass ramp");
            }
            SourceEq flat; flat.prepare(rate); flat.configure(true, {0, 0, 0});
            for (int i = 0; i < 2000; ++i) {
                float l = float(std::sin(i * 0.1)), original = l, r = -l;
                flat.process(l, r); check(l == original && r == -original, "flat is transparent");
            }
        }
        std::cout << "PASS: source EQ baseline at 44.1/48/96 kHz\n"; return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
