"""Прямая и двухступенчатая интерполяция на ранее измеренных дробных настройках."""
import json
import numpy as np
from scipy.interpolate import RBFInterpolator
from probe_pultec_total_relative import AXES,CPS,FLAT,TRAIN,control_weights,curve,paths,record,save
from validate_pultec_total_reserve import DIRECTORY


def main():
    files = paths()
    cases = {}
    for name in ("edges_v4_anchors","edges_v4_reserve","local_control_train",
                 "local_control_reserve","total_relative_v2_reserve"):
        folder = DIRECTORY.parent/name
        for r in json.loads((folder/"manifest.json").read_text())["rows"]:
            cases[r["c"],r["b"],r["a"]] = (folder/r["wav"]).with_suffix(".csv")
    cases[60,.5,10] = DIRECTORY.parent/"boundary_half__7y2162f/transfer.csv"
    f,flat,_ = curve(FLAT)
    centers = TRAIN+[(0,0)]+AXES
    weights = RBFInterpolator(centers,np.eye(len(centers)),kernel="cubic")
    logs = []
    for c in CPS:
        nodes = {(0,0):flat}
        for b,a in AXES+TRAIN:
            grid,h,_ = curve(files[c,b,a])
            np.testing.assert_array_equal(f,grid)
            nodes[b,a] = h
        residual = np.array([nodes[b,a]-nodes[b,0]-nodes[0,a]+flat for b,a in TRAIN])
        for (cc,b,a),path in cases.items():
            if cc!=c:
                continue
            bw,aw = control_weights(b,True),control_weights(a,True)
            base = sum(v*nodes[j,0] for j,v in bw)+sum(v*nodes[0,j] for j,v in aw)-flat
            direct = weights([[b,a]])[0,:len(TRAIN)]
            staged = sum(v*u*weights([[j,k]])[0,:len(TRAIN)] for j,v in bw for k,u in aw)
            grid,h,_ = curve(path)
            np.testing.assert_array_equal(f,grid)
            for name,w in (("direct",direct),("staged",staged)):
                logs.append(dict(method=name,**record(c,b,a,f,base+w@residual,h)))
    save("direct_fractional_comparison.csv",logs)
    for name in ("direct","staged"):
        rows = [r for r in logs if r["method"]==name]
        print(name,len(rows),sum(r["passed"] for r in rows),[(r["cps"],r["boost"],r["atten"],round(r["low"],4),round(r["high"],4),round(r["phase"],3)) for r in rows if not r["passed"]])


if __name__=="__main__":
    main()
