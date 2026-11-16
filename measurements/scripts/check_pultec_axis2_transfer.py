"""Одна поправка оси CPS60/2/0 и её перенос через таблицу v2."""
import json
import numpy as np
from scipy.interpolate import RBFInterpolator
from probe_pultec_total_relative import (MODEL,TRAIN,AXES,CPS,FLAT,arrays,basis,curve,
    paths,record,save,control_weights)
from validate_pultec_total_reserve import DIRECTORY


def main():
    files = paths()
    f,axis,_ = curve(files[60,2,0])
    poles,tables = arrays(json.loads(MODEL.read_text()))
    table = tables[CPS.index(60)]
    design = basis(f,poles)
    residual = axis-design@table[2,0]
    # Fit only the measured axis, emphasizing the low band and limiting tail changes.
    scale = np.where(f<=100,8.,1.)/axis
    scaled = design*scale[:,None]
    tail = basis(np.linspace(18000,22050,128),poles)
    matrix = np.vstack([scaled.real,scaled.imag,tail.real,tail.imag,.001*np.eye(len(table[2,0]))])
    rhs = np.r_[(residual*scale).real,(residual*scale).imag,np.zeros(2*len(tail)+len(table[2,0]))]
    fitted = design@np.linalg.lstsq(matrix,rhs,rcond=1e-10)[0]
    centers = TRAIN+[(0,0)]+AXES
    values = [-float(b==2) for b,a in TRAIN]+[0.]*(1+len(AXES))
    interp = RBFInterpolator(centers,values,kernel="cubic")
    rows = []
    cases = [(b,a,FLAT if (b,a)==(0,0) else files[60,b,a]) for b,a in np.ndindex(11,11)]
    cases.append((.5,10,DIRECTORY.parent/"boundary_half__7y2162f/transfer.csv"))
    for b,a,path in cases:
        grid,h,_ = curve(path)
        np.testing.assert_array_equal(grid,f)
        w = np.zeros_like(table[0,0])
        gain = 0.
        for j,v in control_weights(b,True):
            w += v*table[j,a]
            gain += v*(float(j==2)+interp([[j,a]])[0])
        p = design@w
        for name,delta in (("v2",0.),("measured",residual),("bank",fitted)):
            pred = p+gain*delta
            db = 20*np.log10(abs(pred/h))
            phase = np.angle(pred/h,deg=True)
            low = np.flatnonzero((f>=20)&(f<=100))
            rows.append(dict(model=name,gain=gain,low_hz=f[low[np.argmax(abs(db[low]))]],
                             phase_hz=f[np.argmax(abs(phase))],**record(60,b,a,f,pred,h)))
    save("axis2_transfer.csv",rows)
    for name in ("v2","measured","bank"):
        group=[r for r in rows if r["model"]==name]
        print(name,sum(r["passed"] for r in group[:-1]),[(r["boost"],r["atten"],r["low"],r["phase"],r["passed"]) for r in group if (r["boost"],r["atten"]) in ((2,0),(1,10),(.5,10))])


if __name__=="__main__":
    main()
