"""Численная проверка сохранённого банка через импульс и рекурсии полюсов."""
import json
import numpy as np
from scipy.signal import lfilter
from check_v5_rate_targets import native_basis
from probe_pultec_control_edges import (CPS,FILE,LOCAL,MODEL,OUT,arrays,base_weights,basis,
    factor,kernel,save,sha256)


def main():
    local = json.loads(LOCAL.read_text())
    model = json.loads((OUT/"anchor_precision_train_v5.json").read_text())
    assert sha256(FILE)==model["parent_sha256"] and sha256(LOCAL)==model["base_sha256"]
    assert sha256(MODEL)==local["base_sha256"]
    poles,tables = arrays(json.loads(MODEL.read_text()))
    archive = np.load(OUT/"native_rate_projection_v1.npz")
    n = 262144
    impulse = np.zeros(n)
    impulse[0] = 1
    logs = []
    for rate in (44100,48000,96000):
        p = poles if rate==44100 else archive[f"poles{rate}"]
        fir = np.ones(1) if rate==44100 else archive[f"reference_ratio_fir{rate}"]
        assert max(abs(p))<1
        states = np.array([lfilter([1-abs(z)],[1,-z],impulse) for z in p])
        freq = np.fft.rfftfreq(n,1/rate)
        bins = np.unique(np.linspace(0,len(freq)-1,2049).astype(int))
        design = basis(freq[bins],poles) if rate==44100 else native_basis(freq[bins],poles,rate)
        corr = np.fft.rfft(fir,n)[bins]
        for c,b,a in [(30,0,0),(60,.5,10),(100,4.5,4.5),(30,10,0),(30,10,5),(30,7,0)]:
            i = CPS.index(c)
            w = base_weights(tables[i],np.asarray(local["delta"])[i],b,a)
            w += factor(b,a)*(kernel([[b,a]])@np.asarray(model["weights"])[i])[0]
            if rate!=44100:
                w = archive[f"map{rate}"]@w
            taps = len(w)-2*len(p)
            out = w[taps:taps+len(p)]@states.real+w[taps+len(p):]@states.imag
            out[:taps] += w[:taps]
            response = np.fft.rfft(lfilter(fir,[1],out))
            analytic = (design@w)*corr
            error = max(abs(response[bins]-analytic))
            assert error<1e-7 and np.isfinite(response).all()
            high = np.flatnonzero(freq>18000)
            j = high[np.argmax(abs(response[high]))]
            logs.append(dict(rate=rate,cps=c,boost=b,atten=a,error=error,
                             peak_hz=freq[j],peak_db=20*np.log10(abs(response[j]))))
    save("rate_bank_impulse.csv",logs)
    for rate in (44100,48000,96000):
        group = [r for r in logs if r["rate"]==rate]
        print(rate,max(r["error"] for r in group),max(group,key=lambda r:r["peak_db"]))


if __name__=="__main__":
    main()
