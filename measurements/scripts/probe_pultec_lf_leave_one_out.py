"""Исключение одного joint-узла при неизменных измеренных осях."""
import json

import numpy as np
from scipy.interpolate import RBFInterpolator

from probe_pultec_total_relative import (
    AXES, CPS, FLAT, MODEL, TRAIN, arrays, basis, curve, paths, record, save)


def main():
    poles,tables=arrays(json.loads(MODEL.read_text()))
    files=paths()
    f,flat,_=curve(FLAT)
    design=basis(f,poles)
    anchors=[(0,0)]+AXES
    coords=TRAIN+anchors
    records=[]
    for i,c in enumerate(CPS):
        measured={(0,0):flat}
        measured.update({k:curve(files[(c,*k)])[1] for k in AXES+TRAIN})
        modeled={k:design@tables[i,k[0],k[1]] for k in coords}
        for j,(b,a) in enumerate(TRAIN):
            keep=np.arange(len(coords))!=j
            # Linear weights independent of the frequency basis and of held-out response.
            alpha=RBFInterpolator(np.asarray(coords)[keep],np.eye(sum(keep)),kernel="cubic")([[b,a]])[0]
            target=measured[b,a]
            positive=np.arange(len(TRAIN))!=j
            train_xy=np.array(TRAIN)[positive]
            normalized_alpha=RBFInterpolator(train_xy,np.eye(len(train_xy)),kernel="cubic")([[b,a]])[0]
            normalized_alpha*=b*a/np.prod(train_xy,axis=1)
            for name,source in (("measured",measured),("bank",modeled)):
                base=source[b,0]+source[0,a]-source[0,0]
                residuals=[source[x,y]-source[x,0]-source[0,y]+source[0,0] for x,y in coords]
                prediction=base+alpha@np.array(residuals)[keep]
                row=record(c,b,a,f,prediction,target)
                records.append(dict(method=name,**row))
                factored=base+normalized_alpha@np.array(residuals)[:len(TRAIN)][positive]
                records.append(dict(method=name+"_factored",**record(c,b,a,f,factored,target)))
            records.append(dict(method="node_fit",**record(c,b,a,f,modeled[b,a],target)))
    save("total_relative_leave_one_out.csv",records)
    for name in ("measured","bank","measured_factored","bank_factored","node_fit"):
        rows=[r for r in records if r["method"]==name]
        print(name,[sum(r["passed"] for r in rows if r["cps"]==c) for c in CPS],
              [(k,round(max(r[k] for r in rows),4)) for k in ("low","mid","high","phase")])


if __name__=="__main__":
    main()
