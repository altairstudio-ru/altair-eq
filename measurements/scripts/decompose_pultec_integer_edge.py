"""Восстановление прогноза v2 при CPS60/1/10 по обучающим измерениям."""
import numpy as np
import json
from scipy.interpolate import RBFInterpolator
from probe_pultec_total_relative import AXES, CPS, FLAT, MODEL, TRAIN, arrays, basis, curve, paths, record, save


def main():
    target = (1,10)
    assert target not in TRAIN
    files = paths()
    f,h,_ = curve(files[(60,*target)])
    poles,tables = arrays(json.loads(MODEL.read_text()))
    design = basis(f,poles)
    table = tables[CPS.index(60)]
    centers = TRAIN+[(0,0)]+AXES
    influence = RBFInterpolator(centers,np.eye(len(centers)),kernel="cubic")([target])[0]
    measured, modeled = {}, {}
    for b,a in centers:
        grid,response,_ = curve(FLAT if (b,a)==(0,0) else files[60,b,a])
        np.testing.assert_array_equal(grid,f)
        measured[b,a] = response
        modeled[b,a] = design@table[b,a]
    def predict(nodes):
        residuals = [nodes[b,a]-nodes[b,0]-nodes[0,a]+nodes[0,0] for b,a in TRAIN]
        return nodes[1,0]+nodes[0,10]-nodes[0,0]+influence[:len(TRAIN)]@np.asarray(residuals)
    ideal,actual = predict(measured),predict(modeled)
    np.testing.assert_allclose(actual,design@table[target],atol=1e-10,rtol=0)
    rows = []
    for name,ratio in (("measured_interpolation",ideal/h),("node_fit",actual/ideal),("v2",actual/h)):
        row = dict(component=name,**record(60,1,10,f,ratio,np.ones_like(h)),
                   db35=20*np.log10(abs(ratio[np.argmin(abs(f-35.338405))])),
                   deg21=np.angle(ratio[np.argmin(abs(f-21.171503))],deg=True))
        rows.append(row)
        print(row)
    save("integer_edge_decomposition.csv",rows)
    weights = dict.fromkeys(centers,0.)
    weights[1,0],weights[0,10],weights[0,0] = 1.,1.,-1.
    for (b,a),v in zip(TRAIN,influence):
        for key,k in (((b,a),1),((b,0),-1),((0,a),-1),((0,0),1)):
            weights[key] += k*v
    impacts = []
    for key,v in weights.items():
        restored = actual-v*(modeled[key]-measured[key])
        impacts.append(dict(boost=key[0],atten=key[1],weight=v,
                            db35=20*np.log10(abs((restored/h)[np.argmin(abs(f-35.338405))])),
                            deg21=np.angle((restored/h)[np.argmin(abs(f-21.171503))],deg=True)))
    save("integer_edge_one_node_restored.csv",impacts)
    for metric in ("db35","deg21"):
        print(metric,sorted(impacts,key=lambda r:abs(r[metric]))[:2])


if __name__=="__main__":
    main()
