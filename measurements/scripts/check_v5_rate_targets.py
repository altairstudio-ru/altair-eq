"""Сравнить форму v5 в физических Гц с сохранёнными целями других SR."""
import json
from pathlib import Path
import numpy as np
from probe_pultec_control_edges import CPS, FILE, LOCAL, MODEL, OUT, arrays, base_weights, basis, curve, factor, kernel, record, save, sha256
from probe_pultec_lf_causal_bank import paths


def native_basis(f,poles,rate):
    p = np.exp(np.log(poles)*44100/rate)
    assert np.max(abs(p)) < 1
    q = np.exp(-2j*np.pi*f[:,None]/rate)
    pos = (1-abs(p))/(1-p*q)
    neg = (1-abs(p))/(1-p.conj()*q)
    return np.column_stack([q**np.arange(int(np.ceil(48*rate/44100))),
                            (pos+neg)/2,(pos-neg)/(2j)])


def native_projection(poles,rate):
    # One linear change of basis per rate, independent of all reference measurements.
    f = np.unique(np.r_[np.geomspace(10,19845,640),np.linspace(0,19845,800)])
    target = basis(f,poles)
    design = native_basis(f,poles,rate)
    tail = native_basis(np.linspace(19845,rate/2,256),poles,rate)
    matrix = np.vstack([design.real,design.imag,.01*tail.real,.01*tail.imag,
                        .00001*np.eye(design.shape[1])])
    rhs = np.vstack([target.real,target.imag,np.zeros((len(matrix)-2*len(f),target.shape[1]))])
    return np.linalg.lstsq(matrix,rhs,rcond=1e-11)[0]


def main():
    v5 = json.loads((OUT/"anchor_precision_train_v5.json").read_text())
    v3 = json.loads(LOCAL.read_text())
    assert sha256(FILE)==v5["parent_sha256"] and sha256(LOCAL)==v5["base_sha256"]
    assert sha256(MODEL)==v3["base_sha256"]
    poles,tables = arrays(json.loads(MODEL.read_text()))
    logs = []
    comparisons = []
    source_paths = paths()
    reference_ratios = {}
    exports = {}
    shared = {}
    maps = {rate:native_projection(poles,rate) for rate in (48000,96000)}
    native = {}
    for row in json.loads((OUT.parent/"lowlevel_analysis_manifest.json").read_text())["rows"]:
        rate = row["sample_rate_hz"]
        if rate not in (48000,96000):
            continue
        conf = row["configuration"]
        c,b,a = (conf[k] for k in ("lf_cps_hz","lf_boost_ui","lf_atten_ui"))
        i = CPS.index(c)
        w = base_weights(tables[i],np.asarray(v3["delta"])[i],b,a)
        w += factor(b,a)*(kernel([[b,a]])@np.asarray(v5["weights"])[i])[0]
        f,h,_ = curve(Path(row["analysis_csv"]))
        pred = basis(f,poles)@w
        native[rate,c,b,a] = native_basis(f,poles,rate)@(maps[rate]@w)
        logs.append(dict(rate=rate,**record(c,b,a,f,pred,h)))
        grid,original,_ = curve(source_paths[c,b,a])
        np.testing.assert_array_equal(grid,f)
        reference_ratios[rate,c,b,a] = (f,h,original,pred)
    for (rate,c,b,a),(f,h,original,pred) in reference_ratios.items():
        # Diagnostic: estimate a common complex ratio on axes, excluding this setting.
        ratios = [data[1]/data[2] for (sr,cc,bb,aa),data in reference_ratios.items()
                  if sr==rate and bb*aa==0 and (cc,bb,aa)!=(c,b,a)]
        correction = np.mean(ratios,axis=0)
        # Fit a real causal FIR correction around unity; anchor the unmeasured tail.
        taps = np.arange(32)
        D = np.exp(-2j*np.pi*f[:,None]*taps/rate)
        tail = np.exp(-2j*np.pi*np.linspace(19000,rate/2,64)[:,None]*taps/rate)
        matrix = np.vstack([D.real,D.imag,.1*tail.real,.1*tail.imag,.001*np.eye(len(taps))])
        rhs = np.r_[correction.real-1,correction.imag,np.zeros(2*len(tail)+len(taps))]
        fir = 1+D@np.linalg.lstsq(matrix,rhs,rcond=None)[0]
        converted = native[rate,c,b,a]
        # Final shared FIR uses the converted bank as baseline and all twelve axes.
        if rate not in exports:
            axis_keys = [k for k in native if k[0]==rate and k[2]*k[3]==0]
            assert len(axis_keys)==12
            ratio = np.mean([reference_ratios[k][1]/native[k] for k in axis_keys],axis=0)
            taps_native = np.linalg.lstsq(matrix,np.r_[ratio.real-1,ratio.imag,
                                     np.zeros(2*len(tail)+len(taps))],rcond=None)[0]
            taps_native[0]+=1
            exports[rate] = taps_native
            ratio = np.mean([reference_ratios[k][1]/reference_ratios[k][2] for k in axis_keys],axis=0)
            taps_ref = np.linalg.lstsq(matrix,np.r_[ratio.real-1,ratio.imag,
                                  np.zeros(2*len(tail)+len(taps))],rcond=None)[0]
            taps_ref[0]+=1
            shared[rate] = taps_ref
        comparisons.append(dict(rate=rate,mode="native_shared",
                                **record(c,b,a,f,converted*(D@shared[rate]),h)))
        comparisons.append(dict(rate=rate,mode="native_axis_calibrated",
                                **record(c,b,a,f,converted*(D@exports[rate]),h)))
        comparisons.append(dict(rate=rate,mode="native_vs_v5",**record(c,b,a,f,converted,pred)))
        comparisons.append(dict(rate=rate,mode="native_fir32",**record(c,b,a,f,converted*fir,h)))
        for mode,p in (("reference",original),("reference_corrected",original*correction),
                       ("v5_corrected",pred*correction),("v5_fir32",pred*fir)):
            comparisons.append(dict(rate=rate,mode=mode,**record(c,b,a,f,p,h)))
    save("rate_reference_comparison.csv",comparisons)
    np.savez_compressed(OUT/"native_rate_projection_v1.npz",**{
        name+str(rate):value for rate in maps for name,value in (
            ("map",maps[rate]),("reference_ratio_fir",shared[rate]),("axis_calibrated_fir",exports[rate]),
            ("poles",np.exp(np.log(poles)*44100/rate)))})
    for rate in (48000,96000):
        for mode in ("reference","reference_corrected","v5_corrected","v5_fir32","native_vs_v5","native_fir32","native_axis_calibrated","native_shared"):
            group = [r for r in comparisons if r["rate"]==rate and r["mode"]==mode]
            print(rate,mode,sum(r["passed"] for r in group),[round(max(r[k] for r in group),5) for k in ("low","mid","high","phase")])
    save("v5_same_hz_rate_targets.csv",logs)
    for rate in (48000,96000):
        selected = [r for r in logs if r["rate"]==rate]
        print(rate,len(selected),sum(r["passed"] for r in selected),[max(r[k] for r in selected) for k in ("low","mid","high","phase")])


if __name__=="__main__":
    main()
