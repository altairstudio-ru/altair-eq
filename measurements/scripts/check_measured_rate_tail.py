"""Общая добавочная FIR по измеренным осям целевого SR, проверка на joint."""
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from check_v5_rate_targets import native_basis
from probe_pultec_control_edges import (CPS,LOCAL,MODEL,OUT,arrays,base_weights,curve,
    factor,kernel,record,save,sha256)


def main():
    poles,table = arrays(json.loads(MODEL.read_text()))
    local = np.asarray(json.loads(LOCAL.read_text())["delta"])
    edge = np.asarray(json.loads((OUT/"anchor_precision_train_v5.json").read_text())["weights"])
    bank = np.load(OUT/"native_rate_projection_v1.npz")
    rows = json.loads((OUT.parent/"lowlevel_analysis_manifest.json").read_text())["rows"]
    logs = []
    for rate in (48000,96000):
        matrix,rhs = [],[]
        for group in ("axis","joint"):
            cases = []
            for row in rows:
                c,b,a = [row["configuration"][k] for k in ("lf_cps_hz","lf_boost_ui","lf_atten_ui")]
                if row["sample_rate_hz"]!=rate or bool(b*a)!=(group=="joint"):
                    continue
                f,h,_ = curve(Path(row["analysis_csv"]))
                inputs = json.loads(Path(row["analysis_json"]).read_text())["inputs"]
                signals = []
                for field in ("input_sha256","output_sha256"):
                    path, = [Path(p) for p,v in inputs.items() if v==row[field]]
                    assert sha256(path)==row[field]
                    x,sr = sf.read(path,always_2d=True)
                    assert sr==rate
                    signals.append(np.fft.rfft(x[:,0]))
                X,Y = signals
                freq = np.fft.rfftfreq(len(x),1/rate)
                ix = np.searchsorted(freq,np.unique(np.r_[np.linspace(18001,.45*rate,320),20413.696]))
                ix = ix[abs(X[ix])>1e-4*max(abs(X))]
                ext = freq[ix]
                target = Y[ix]/X[ix]*np.exp(2j*np.pi*ext*row["latency_compensated_samples"]/rate)
                ff = np.r_[f,ext]
                design = np.exp(-2j*np.pi*ff[:,None]*np.arange(96)/rate)
                i = CPS.index(c)
                w = base_weights(table[i],local[i],b,a)+factor(b,a)*(kernel([[b,a]])@edge[i])[0]
                fir = bank[f"reference_ratio_fir{rate}"]
                pred = (native_basis(ff,poles,rate)@(bank[f"map{rate}"]@w))*(design[:,:len(fir)]@fir)
                cases.append((c,b,a,f,h,ext,target,pred,design))
                if group=="axis":
                    # Preserve the previous in-band transfer; fit complex absolute error above it.
                    scale = np.r_[8/np.abs(h),np.ones(len(ext))]
                    d = design*scale[:,None]
                    y = np.r_[np.zeros(len(f)),target-pred[len(f):]]*scale
                    matrix.extend((d.real,d.imag))
                    rhs.extend((y.real,y.imag))
            if group=="axis":
                assert len(cases)==12
                matrix.append(.05*np.eye(96))
                rhs.append(np.zeros(96))
                taps = np.linalg.lstsq(np.vstack(matrix),np.concatenate(rhs),rcond=1e-9)[0]
                np.save(OUT/f"measured_tail_additive96_{rate}.npy",taps)
                # Use only axis curves to cap the correction before evaluating joint cases.
                alpha = None
                for scale in np.linspace(1,0,101):
                    if all(record(c,b,a,f,p[:len(f)]+scale*(d[:len(f)]@taps),h)["passed"]
                           for c,b,a,f,h,ext,target,p,d in cases):
                        alpha = scale
                        break
                assert alpha is not None
                print(rate,"axis-limited scale",alpha)
                np.save(OUT/f"measured_tail_axis_limited_{rate}.npy",alpha*taps)
            for c,b,a,f,h,ext,target,pred,d in cases:
                for name,p in (("base",pred),("corrected",pred+d@taps),("axis_limited",pred+alpha*(d@taps))):
                    tail = p[len(f):]
                    j = np.argmin(abs(ext-20413.696))
                    logs.append(dict(rate=rate,group=group,model=name,**record(c,b,a,f,p[:len(f)],h),
                        error_20414_db=20*np.log10(abs(tail[j]/target[j])),
                        ext_max_complex=max(abs(tail-target)),ext_peak_db=20*np.log10(max(abs(tail)))))
    save("measured_rate_tail.csv",logs)
    for rate in (48000,96000):
        for name in ("base","corrected","axis_limited"):
            rs=[r for r in logs if r["rate"]==rate and r["model"]==name]
            print(rate,name,[sum(r["passed"] for r in rs if r["group"]==g) for g in ("axis","joint")],
                  max(r["ext_max_complex"] for r in rs),next(r["error_20414_db"] for r in rs if (r["cps"],r["boost"],r["atten"])==(30,10,5)))


if __name__=="__main__":
    main()
