"""Экспорт фиксированных таблиц трёх SR и независимых временных golden-векторов."""
import json
from pathlib import Path
import numpy as np
from scipy.signal import lfilter
from probe_pultec_control_edges import (CPS, CENTERS, DIRECTORY, LOCAL, MODEL, OUT, ROOT,
    arrays, base_weights, factor, kernel, sha256)


def emit(stream,name,data):
    values = np.asarray(data).ravel()
    stream.write(f"inline constexpr double {name}[] = {{\n")
    for i in range(0,len(values),8):
        stream.write(",".join(format(x,".17g") for x in values[i:i+8])+",\n")
    stream.write("};\n")


def main():
    freeze = json.loads((DIRECTORY.parent/"native_fractional_fzir_ftz/freeze.json").read_text())
    assert all(sha256(Path(p))==h for p,h in freeze["hashes"].items())
    poles,tables = arrays(json.loads(MODEL.read_text()))
    delta = np.asarray(json.loads(LOCAL.read_text())["delta"])
    edge = np.asarray(json.loads((OUT/"anchor_precision_train_v5.json").read_text())["weights"])
    archive = np.load(OUT/"native_rate_projection_v1.npz")
    with (ROOT/"dsp/FrozenLfData.inc").open("w") as data,(ROOT/"tests/golden/FrozenLfVectors.inc").open("w") as gold:
        emit(data,"centers",CENTERS)
        for rate in (44100,48000,96000):
            projection = np.eye(tables.shape[-1]) if rate==44100 else archive[f"map{rate}"]
            p = poles if rate==44100 else archive[f"poles{rate}"]
            fir = np.ones(1) if rate==44100 else archive[f"reference_ratio_fir{rate}"]
            tail = np.zeros(1) if rate==44100 else np.load(OUT/f"measured_tail_axis_limited_{rate}.npy")
            for name,values in (("pr",p.real),("pi",p.imag),("norm",1-abs(p)),("fir",fir),("tail",tail),
                                ("table",tables@projection.T),("local",delta@projection.T),("edge",edge@projection.T)):
                emit(data,name+str(rate),values)
            n = round(rate*.02)
            t = np.arange(5*n)/rate
            x = np.sin(2*np.pi*53*t)*.06+np.cos(2*np.pi*1300*t)*.01
            outputs = []
            for c,b,a in ((30,0,0),(60,.5,10),(100,4.5,4.5)):
                i = CPS.index(c)
                w = projection@(base_weights(tables[i],delta[i],b,a)+factor(b,a)*(kernel([[b,a]])@edge[i])[0])
                taps = len(w)-2*len(p)
                y = lfilter(w[:taps],[1],x)
                for j,pole in enumerate(p):
                    z = lfilter([1-abs(pole)],[1,-pole],x)
                    y += w[taps+j]*z.real+w[taps+len(p)+j]*z.imag
                outputs.append(y)
            mix = np.array([1.,0,0])
            y = np.zeros_like(x)
            for k in range(len(x)):
                if k in (n,n+n//2):
                    begin = mix.copy()
                    end = np.eye(3)[1 if k==n else 2]
                    pos = k
                if k>=n:
                    mix = begin+(end-begin)*min((k-pos+1)/n,1)
                y[k] = sum(m*s[k] for m,s in zip(mix,outputs))
            emit(gold,"gold"+str(rate),(lfilter(fir,[1],y)+lfilter(tail,[1],x))[::13])


if __name__=="__main__":
    main()
