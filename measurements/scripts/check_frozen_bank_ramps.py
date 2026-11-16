"""Офлайн-сверка плавных переходов и прерывания текущей рампы у банка v5."""
import json
import numpy as np
from scipy.signal import lfilter
from probe_pultec_control_edges import CPS, DIRECTORY, LOCAL, MODEL, OUT, arrays, base_weights, factor, kernel, save, sha256
from pathlib import Path


def main():
    freeze = json.loads((DIRECTORY.parent/"native_fractional_fzir_ftz/freeze.json").read_text())
    assert all(sha256(Path(p))==h for p,h in freeze["hashes"].items())
    poles,tables = arrays(json.loads(MODEL.read_text()))
    delta = np.asarray(json.loads(LOCAL.read_text())["delta"])
    edge = np.asarray(json.loads((OUT/"anchor_precision_train_v5.json").read_text())["weights"])
    weights = []
    for c,b,a in ((20,0,0),(100,10,0),(60,.625,9.375),(30,0,10),(100,4.5,4.5)):
        i = CPS.index(c)
        weights.append(base_weights(tables[i],delta[i],b,a)+factor(b,a)*(kernel([[b,a]])@edge[i])[0])
    archive = np.load(OUT/"native_rate_projection_v1.npz")
    logs = []
    for rate in (44100,48000,96000):
        n = round(.02*rate)
        t = np.arange(9*n)/rate
        x = .05*np.sin(2*np.pi*43*t)+.01*np.sin(2*np.pi*1350*t)
        p = poles if rate==44100 else archive[f"poles{rate}"]
        ws = np.array(weights) if rate==44100 else np.array(weights)@archive[f"map{rate}"].T
        fir = [1.] if rate==44100 else archive[f"reference_ratio_fir{rate}"]
        tail = [0.] if rate==44100 else np.load(OUT/f"measured_tail_axis_limited_{rate}.npy")
        # Construct expected result by mixing complete static branch outputs before the common FIR.
        states = np.stack([lfilter([1-abs(z)],[1,-z],x) for z in p])
        taps = ws.shape[1]-2*len(p)
        static = np.array([lfilter(w[:taps],[1],x)+w[taps:taps+len(p)]@states.real+
                           w[taps+len(p):]@states.imag for w in ws])
        controls = {2*n:1,4*n:2,4*n+n//4:3,6*n:4}
        mix = np.eye(len(ws))[0]
        w = ws[0].copy()
        z = np.zeros_like(p)
        history = np.zeros(taps)
        actual,expected = np.zeros_like(x),np.zeros_like(x)
        left = 0
        for k,sample in enumerate(x):
            if k in controls:
                target = controls[k]
                start = mix.copy()
                step = (ws[target]-w)/n
                left = n
            if left:
                w += step
                left -= 1
                progress = (n-left)/n
                mix = (1-progress)*start + progress*np.eye(len(ws))[target]
                if left==0:
                    w = ws[target].copy()
            z = p*z+(1-abs(p))*sample
            history[1:] = history[:-1]
            history[0] = sample
            actual[k] = w[:taps]@history+w[taps:taps+len(p)]@z.real+w[taps+len(p):]@z.imag
            expected[k] = mix@static[:,k]
        actual = lfilter(fir,[1],actual)+lfilter(tail,[1],x)
        expected = lfilter(fir,[1],expected)+lfilter(tail,[1],x)
        error = np.max(abs(actual-expected))
        assert np.isfinite(actual).all() and error<1e-8
        logs.append(dict(rate=rate,ramp_samples=n,events=len(controls),max_abs_error=error,
                         peak=float(np.max(abs(actual)))))
    save("frozen_bank_ramps.csv",logs)
    print(logs)


if __name__=="__main__":
    main()
