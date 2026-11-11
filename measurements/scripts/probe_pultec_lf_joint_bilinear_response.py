#!/usr/bin/env python3
"""Probe bilinear complex-response interpolation against held-out joint LF measurements."""
import csv
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator, RegularGridInterpolator

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"measurements/results/pultec_lf/lowlevel_analysis_manifest.json"
JOINT=ROOT/"measurements/results/pultec_lf/joint_grid_44k1_coarse_manifest.json"
INTEGER=ROOT/"measurements/results/pultec_lf/joint_grid_44k1_integer_manifest.json"
TRICK=BASE
FLAT=ROOT/"measurements/results/pultec_lf/level_sweep_control_v2/flat-m36-44k1-sweep.csv"
OUT=ROOT/"measurements/results/pultec_lf/joint_bilinear_response_probe.json"
SR=44100


def curve(path):
    with path.open(newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
    freq=np.array([float(r["freq_hz"]) for r in rows]); db=np.array([float(r["magnitude_db"]) for r in rows]); ph=np.deg2rad([float(r["phase_deg"]) for r in rows])
    return freq,10**(db/20)*np.exp(1j*ph),db


def metric(pred,target,db,freq):
    mag=20*np.log10(np.maximum(np.abs(pred),1e-12))-db; phase=np.angle(pred*np.conj(target))*180/np.pi
    bands={}
    for lo,hi in ((20,100),(100,1000),(1000,18000)):
        m=(freq>=lo)&(freq<hi if hi<18000 else freq<=hi); bands[f"{lo}-{hi}"]=float(np.max(np.abs(mag[m])))
    p=float(np.max(np.abs(phase))); passed=bool(bands["20-100"]<=.2 and bands["100-1000"]<=.15 and bands["1000-18000"]<=.1 and p<=2)
    return {"pass":passed,"band_max_magnitude_error_db":bands,"max_phase_error_deg":p}


def bracket(value):
    grid=tuple(range(0,11))
    if value in grid:
        if value==0: return 0,1
        if value==10: return 9,10
        return value-1,value+1
    low=int(value//1)
    return low,low+1


def main():
    data={}
    for row in json.loads(BASE.read_text(encoding="utf-8"))["rows"]:
        if row["sample_rate_hz"]!=SR: continue
        c=row["configuration"]; b=float(c["lf_boost_ui"]); a=float(c["lf_atten_ui"])
        data[(c["lf_cps_hz"],b,a)]=curve(ROOT/row["analysis_csv"])
    for row in json.loads(JOINT.read_text(encoding="utf-8"))["rows"].values():
        if row["status"]=="complete":
            data[(row["lf_cps_hz"],row["lf_boost_ui"],row["lf_atten_ui"])]=curve(ROOT/row["analysis_csv"])
    integer_rows=[]
    for row in json.loads(INTEGER.read_text(encoding="utf-8"))["rows"].values():
        if row["status"]=="complete":
            key=(row["lf_cps_hz"],row["lf_boost_ui"],row["lf_atten_ui"])
            data[key]=curve(ROOT/row["analysis_csv"])
            # Odd integer settings are withheld; the model uses the measured even grid.
            if int(row["lf_boost_ui"])%2 or int(row["lf_atten_ui"])%2:
                integer_rows.append(row)
    flat=curve(FLAT)
    for cps in (20,30,60,100): data[(cps,0.0,0.0)]=flat
    trick=json.loads(TRICK.read_text(encoding="utf-8"))["rows"]
    heldout=[row for row in trick if row["sample_rate_hz"]==SR and
             (float(row["configuration"]["lf_boost_ui"]),float(row["configuration"]["lf_atten_ui"]))
             in ((10.0,5.0),(5.0,10.0),(8.0,2.0),(2.0,8.0))]
    heldout += [{"id":r["id"],"configuration":{"lf_cps_hz":r["lf_cps_hz"],
                  "lf_boost_ui":r["lf_boost_ui"],"lf_atten_ui":r["lf_atten_ui"]},
                  "analysis_csv":r["analysis_csv"]} for r in integer_rows]
    rbf_by_cps={}; rbf_log_by_cps={}; regular_grid_by_cps={}
    for cps in (20,30,60,100):
        train_coords=np.array([[bv,av] for bv in (0,2,4,6,8,10) for av in (0,2,4,6,8,10)
                               if (cps,float(bv),float(av)) in data and (bv,av) not in ((8,2),(2,8))],dtype=float)/2.0
        train_h=np.array([data[(cps,float(bv),float(av))][1] for bv,av in train_coords*2])
        train_values=np.concatenate([train_h.real,train_h.imag],axis=1)
        rbf_by_cps[cps]={}; rbf_log_by_cps[cps]={}
        phase_values=np.unwrap(np.angle(train_h),axis=1)
        flat_phase=np.unwrap(np.angle(flat[1]))
        for i in range(len(phase_values)):
            shift=2*np.pi*np.round(np.median((flat_phase-phase_values[i])/(2*np.pi)))
            phase_values[i]+=shift
        log_values=np.concatenate([np.log(np.maximum(np.abs(train_h),1e-12)),phase_values],axis=1)
        for kernel,degree in (("thin_plate_spline",1),("cubic",1),("quintic",2),
                              ("linear",0),("gaussian",0),("multiquadric",0)):
            try:
                rbf_by_cps[cps][kernel]=RBFInterpolator(train_coords,train_values,kernel=kernel,
                                                        degree=degree,epsilon=1.0)
                rbf_log_by_cps[cps][kernel]=RBFInterpolator(train_coords,log_values,kernel=kernel,
                                                            degree=degree,epsilon=1.0)
            except Exception as exc:
                print(f"RBF skipped CPS {cps}/{kernel}: {exc}",flush=True)
        grid_values=np.array((0,2,4,6,8,10),dtype=float)
        shape=(len(grid_values),len(grid_values),train_h.shape[1])
        logmag_grid=np.full(shape,np.nan); phase_grid=np.full(shape,np.nan)
        flat_phase=np.unwrap(np.angle(flat[1]))
        for bi,bv in enumerate(grid_values):
            for ai,av in enumerate(grid_values):
                if (int(bv),int(av)) in ((8,2),(2,8)): continue
                h=data[(cps,float(bv),float(av))][1]
                phase=np.unwrap(np.angle(h))
                phase+=2*np.pi*np.round(np.median((flat_phase-phase)/(2*np.pi)))
                logmag_grid[bi,ai]=np.log(np.maximum(np.abs(h),1e-12))
                phase_grid[bi,ai]=phase
        for hb,ha in ((2,8),(8,2)):
            bi=int(hb/2); ai=int(ha/2)
            for surface in (logmag_grid,phase_grid):
                surface[bi,ai]=.25*(surface[bi-1,ai-1]+surface[bi+1,ai-1]
                                      +surface[bi-1,ai+1]+surface[bi+1,ai+1])
        regular_grid_by_cps[cps]={}
        for method in ("cubic","quintic","pchip"):
            try:
                regular_grid_by_cps[cps][method]=(RegularGridInterpolator((grid_values,grid_values),logmag_grid,method=method),
                                                  RegularGridInterpolator((grid_values,grid_values),phase_grid,method=method))
            except Exception as exc:
                print(f"grid {method} skipped CPS {cps}: {exc}",flush=True)
    results=[]
    for row in heldout:
        c=row["configuration"]; cps=c["lf_cps_hz"]; b=float(c["lf_boost_ui"]); a=float(c["lf_atten_ui"])
        is_integer_holdout=(b.is_integer() and a.is_integer() and (int(b)%2 or int(a)%2))
        if (b,a) not in ((10.0,5.0),(5.0,10.0),(8.0,2.0),(2.0,8.0)) and not is_integer_holdout: continue
        b0,b1=bracket(b); a0,a1=bracket(a)
        freq,target,db=curve(ROOT/row["analysis_csv"])
        u=(b-b0)/(b1-b0); v=(a-a0)/(a1-a0)
        coords=np.array([[bv,av] for bv in (0,2,4,6,8,10) for av in (0,2,4,6,8,10)
                         if (cps,float(bv),float(av)) in data and (bv,av)!=(b,a)],dtype=float)
        responses=np.array([data[(cps,float(bv),float(av))][1] for bv,av in coords])
        corners=[data[(cps,bv,av)] for bv,av in ((b0,a0),(b1,a0),(b0,a1),(b1,a1))]
        bilinear=(1-u)*(1-v)*corners[0][1]+u*(1-v)*corners[1][1]+(1-u)*v*corners[2][1]+u*v*corners[3][1]
        methods={"bilinear":metric(bilinear,target,db,freq)}
        scaled=(coords-np.array([b,a]))/2.0
        distance=np.sqrt(np.sum(scaled*scaled,axis=1))
        for power in (1,2,4,8):
            weights=1.0/np.maximum(distance,1e-12)**power; weights/=np.sum(weights)
            methods[f"idw_{power}"]=metric(weights@responses,target,db,freq)
        for sigma in (.5,1.0,2.0):
            weights=np.exp(-.5*(distance/sigma)**2); weights/=np.sum(weights)
            methods[f"gaussian_{sigma:g}"]=metric(weights@responses,target,db,freq)
        for kernel,interpolator in rbf_by_cps[cps].items():
            value=interpolator(np.array([[b/2.0,a/2.0]]))[0]
            predicted=value[:len(freq)]+1j*value[len(freq):]
            methods[f"rbf_{kernel}"]=metric(predicted,target,db,freq)
        for kernel,interpolator in rbf_log_by_cps[cps].items():
            value=interpolator(np.array([[b/2.0,a/2.0]]))[0]
            predicted=np.exp(value[:len(freq)]+1j*value[len(freq):])
            methods[f"rbf_log_{kernel}"]=metric(predicted,target,db,freq)
        for method,(mag_grid,phase_grid_interp) in regular_grid_by_cps[cps].items():
            point=np.array([[b,a]])
            predicted=np.exp(mag_grid(point)[0]+1j*phase_grid_interp(point)[0])
            methods[f"grid_{method}"]=metric(predicted,target,db,freq)
        results.append({"id":row["id"],"lf_cps_hz":cps,"boost":b,"atten":a,
                        "corners":[[b0,a0],[b1,a0],[b0,a1],[b1,a1]],"u":u,"v":v,
                        "methods":methods})
    summary={}
    method_names=("bilinear","idw_1","idw_2","idw_4","idw_8","gaussian_0.5","gaussian_1","gaussian_2")
    method_names += tuple(f"rbf_{name}" for name in ("thin_plate_spline","cubic","quintic","linear","gaussian","multiquadric"))
    method_names += tuple(f"rbf_log_{name}" for name in ("thin_plate_spline","cubic","quintic","linear","gaussian","multiquadric"))
    method_names += tuple(f"grid_{name}" for name in ("cubic","quintic","pchip"))
    for method in method_names:
        metrics=[r["methods"][method] for r in results]
        summary[method]={"pass":sum(r["pass"] for r in metrics),"total":len(metrics),
                         "max_phase_error_deg":max(r["max_phase_error_deg"] for r in metrics),
                         "max_band_errors_db":{band:max(r["band_max_magnitude_error_db"][band] for r in metrics)
                                                for band in ("20-100","100-1000","1000-18000")}}
    OUT.write_text(json.dumps({"schema":"altair-eq.pultec-lf-joint-surface-cv/1",
                               "method":"surface interpolation trained on even integer settings, evaluated on withheld odd integer settings and asymmetric cross-checks",
                               "sample_rate_hz":SR,"summary":summary,"results":results},indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,indent=2)); print(f"details: {OUT}")

if __name__=="__main__": main()
