"""Проверяет интерполяцию v2 на измеренных опорах для всех CPS."""
import numpy as np
from scipy.interpolate import RBFInterpolator
from probe_pultec_total_relative import AXES, CPS, FLAT, TRAIN, control_weights, curve, paths, record, save
from validate_pultec_total_reserve import DIRECTORY


def main():
    files = paths()
    centers = TRAIN+[(0,0)]+AXES
    integer = list(np.ndindex(11,11))
    influences = RBFInterpolator(centers,np.eye(len(centers)),kernel="cubic")(integer)
    f,flat,_ = curve(FLAT)
    rows = []
    def measured(path):
        grid,h,_ = curve(path)
        np.testing.assert_array_equal(grid,f)
        return h
    for c in CPS:
        nodes = {(0,0):flat}
        for b,a in AXES+TRAIN:
            nodes[b,a] = measured(files[c,b,a])
        residual = np.array([nodes[b,a]-nodes[b,0]-nodes[0,a]+flat for b,a in TRAIN])
        predicted = (influences[:,:len(TRAIN)]@residual +
                     np.array([nodes[b,0]+nodes[0,a]-flat for b,a in integer]))
        predicted = predicted.reshape(11,11,-1)
        for b,a in centers:
            np.testing.assert_allclose(predicted[b,a],nodes[b,a],rtol=0,atol=1e-10)
        for b,a in integer:
            if (b,a) not in nodes:
                rows.append(record(c,b,a,f,predicted[b,a],measured(files[c,b,a])))
        if c==60:
            half = sum(weight*predicted[b,10] for b,weight in control_weights(.5,True))
            rows.append(record(c,.5,10,f,half,measured(DIRECTORY.parent/"boundary_half__7y2162f/transfer.csv")))
    save("measured_table_all_cps.csv",rows)
    for c in CPS:
        group = [r for r in rows if r["cps"]==c and r["boost"]!=.5]
        assert len(group)==77
        print(c,sum(r["passed"] for r in group),[max(r[k] for r in group) for k in ("low","mid","high","phase")])
    print(next(r for r in rows if r["boost"]==.5))


if __name__=="__main__":
    main()
