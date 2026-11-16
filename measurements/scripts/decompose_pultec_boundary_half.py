"""Отделяет ошибки целых узлов v2 от кубической интерполяции комплексного отклика."""
import json
import numpy as np
from probe_pultec_control_edges import (CPS, DIRECTORY, MODEL, arrays, basis,
    control_weights, curve, paths, record, save)


def main():
    f,target,_ = curve(DIRECTORY.parent/"boundary_half__7y2162f/transfer.csv")
    poles,tables = arrays(json.loads(MODEL.read_text()))
    design = basis(f,poles)
    files = paths()
    interpolated = np.zeros_like(target)
    modeled = np.zeros_like(target)
    rows = []
    def log(label,ratio,boost=.5):
        summary = record(60,boost,10,f,ratio,np.ones_like(ratio))
        mag = 20*np.log10(abs(ratio))
        phase = np.angle(ratio,deg=True)
        row = dict(component=label,**summary,db_at_35=mag[np.argmin(abs(f-35.338405))],
                   deg_at_21=phase[np.argmin(abs(f-21.171503))])
        rows.append(row)
        print(label,*[round(row[k],5) for k in ("low","phase","db_at_35","deg_at_21")])
    for b,weight in control_weights(.5,True):
        grid,h,_ = curve(files[60,b,10])
        np.testing.assert_array_equal(f,grid)
        p = design@tables[CPS.index(60),b,10]
        log(f"node_{b}",p/h,b)
        interpolated += weight*h
        modeled += weight*p
    log("measured_cubic",interpolated/target)
    log("model_node_contribution",modeled/interpolated)
    log("total_v2",modeled/target)
    np.testing.assert_allclose((modeled/interpolated)*(interpolated/target),modeled/target)
    save("boundary_half_cubic_decomposition.csv",rows)


if __name__=="__main__":
    main()
