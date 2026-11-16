"""Сверка верхнего края банка с сохранённым sweep CPS30/10/5 при 96 кГц."""
import json
from pathlib import Path
import numpy as np
import soundfile as sf
from check_v5_rate_targets import native_basis
from probe_pultec_control_edges import CPS,LOCAL,MODEL,OUT,arrays,base_weights,factor,kernel,save,sha256


def main():
    rows = json.loads((OUT.parent/"lowlevel_analysis_manifest.json").read_text())["rows"]
    row, = [r for r in rows if r["sample_rate_hz"]==96000 and
            tuple(r["configuration"][k] for k in ("lf_cps_hz","lf_boost_ui","lf_atten_ui"))==(30,10,5)]
    inputs = json.loads(Path(row["analysis_json"]).read_text())["inputs"]
    signals = []
    for field in ("input_sha256","output_sha256"):
        path, = [Path(p) for p,v in inputs.items() if v==row[field]]
        assert sha256(path)==row[field]
        signal,rate = sf.read(path,always_2d=True)
        assert rate==96000
        signals.append(np.fft.rfft(signal[:,0]))
    x,y = signals
    freq = np.fft.rfftfreq((len(x)-1)*2,1/rate)
    pole,table = arrays(json.loads(MODEL.read_text()))
    delta = np.asarray(json.loads(LOCAL.read_text())["delta"])
    v5 = json.loads((OUT/"anchor_precision_train_v5.json").read_text())
    i = CPS.index(30)
    w = base_weights(table[i],delta[i],10,5)+factor(10,5)*(kernel([[10,5]])@np.asarray(v5["weights"])[i])[0]
    bank = np.load(OUT/"native_rate_projection_v1.npz")
    fir = bank["reference_ratio_fir96000"]
    f = np.unique(np.r_[np.linspace(18000,43200,601),20413.6962890625])
    indices = np.searchsorted(freq,f)
    indices = indices[abs(x[indices])>1e-4*max(abs(x))]
    assert min(abs(freq[indices]-20413.696))<.1
    f = freq[indices]
    pred = (native_basis(f,pole,rate)@(bank["map96000"]@w))*(np.exp(-2j*np.pi*f[:,None]*np.arange(len(fir))/rate)@fir)
    ref = y[indices]/x[indices]*np.exp(2j*np.pi*f*row["latency_compensated_samples"]/rate)
    db = lambda v: 20*np.log10(abs(v))
    logs = [dict(hz=fr,model_db=m,reference_db=r,error_db=m-r,phase_error_deg=ph)
            for fr,m,r,ph in zip(f,db(pred),db(ref),np.angle(pred/ref,deg=True))]
    save("native_peak_reference_96k.csv",logs)
    print(len(logs),f[-1],logs[np.argmin(abs(f-20413.696))],max(logs,key=lambda r:abs(r["error_db"])))


if __name__=="__main__":
    main()
