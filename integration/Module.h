#pragma once
#include <array>
#include <string_view>

namespace altair {
struct ProcessSpec { double sampleRate; int maximumBlockSize; int channels = 2; };
struct ParameterDescriptor
{
    std::string_view id, unit;
    float minimum, maximum, defaultValue;
};
struct ModuleDescriptor
{
    std::string_view id, name;
    int stateVersion = 1;
    int latencySamples = 0;
    double tailSeconds = 0;
};

// Prepare/reset on a suspended graph. Remaining operations must not allocate,
// lock, access files, throw, or retain pointers to the host's audio buffers.
class Module
{
public:
    virtual ~Module() = default;
    virtual ModuleDescriptor descriptor() const noexcept = 0;
    virtual int parameterCount() const noexcept = 0;
    virtual const ParameterDescriptor* parameter(int index) const noexcept = 0;
    virtual bool setParameter(int index, float value) noexcept = 0;
    virtual void prepare(ProcessSpec) = 0;
    virtual void reset() noexcept = 0;
    virtual void process(float& left, float& right) noexcept = 0;
};

class PassThrough final : public Module
{
public:
    ModuleDescriptor descriptor() const noexcept override { return {"altair.passthrough", "Pass-through (test)", 1, 0, 0}; }
    int parameterCount() const noexcept override { return 0; }
    const ParameterDescriptor* parameter(int) const noexcept override { return nullptr; }
    bool setParameter(int, float) noexcept override { return false; }
    void prepare(ProcessSpec) override {}
    void reset() noexcept override {}
    void process(float&, float&) noexcept override {}
};

// Fixed-capacity serial rack. This first core version accepts zero-latency,
// zero-tail modules only; it does not pretend to compensate arbitrary plugins.
class SerialRack
{
public:
    static constexpr int capacity = 4;
    bool connect(int slot, Module* module, bool bypass) noexcept
    {
        if (slot < 0 || slot >= capacity) return false;
        if (module && (module->descriptor().latencySamples != 0 || module->descriptor().tailSeconds != 0)) return false;
        slots[size_t(slot)] = {module, bypass}; return true;
    }
    void prepare(ProcessSpec spec)
    { for (auto& slot : slots) if (slot.module) slot.module->prepare(spec); }
    void reset() noexcept
    { for (auto& slot : slots) if (slot.module) slot.module->reset(); }
    void process(float& l, float& r) noexcept
    { for (auto& slot : slots) if (slot.module && !slot.bypass) slot.module->process(l, r); }
private:
    struct Slot { Module* module = nullptr; bool bypass = false; };
    std::array<Slot, capacity> slots {};
};
}
