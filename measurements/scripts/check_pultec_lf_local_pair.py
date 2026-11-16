"""Нижняя граница ВЧ-пика при добавлении одной параллельной секции."""
import csv
import json

import numpy as np
from scipy.optimize import linprog

from fit_pultec_lf_extended_guard import EXT, MODEL, OUT, TRAIN_KEYS, arrays, targets
from probe_pultec_lf_causal_bank import BASE, CPS, FLAT, LIMIT, ROOT, SR, basis, curve, errors


def control_weights(value, cubic):
    count = 4 if cubic else 2
    start = min(11-count,max(0,int(value)-(1 if cubic else 0)))
    nodes = range(start,start+count)
    return [(i,np.prod([(value-j)/(i-j) for j in nodes if j!=i])) for i in nodes]


def check_fractional(poles, tables, cubic=False):
    measurements = {}
    for manifest in sorted(BASE.parent.glob("interpolation_44k1*manifest.json")):
        rows = json.loads(manifest.read_text(encoding="utf-8"))["rows"]
        for row in rows.values() if isinstance(rows,dict) else rows:
            if row.get("status") != "complete" or not row.get("analysis_csv"):
                continue
            b,a = float(row["lf_boost_ui"]),float(row["lf_atten_ui"])
            if not (b.is_integer() and a.is_integer()):
                measurements[row["lf_cps_hz"],b,a] = row["analysis_csv"]
    output = []
    for (c,b,a),path in sorted(measurements.items()):
        grid,target,_ = curve(ROOT/path)
        table = tables[CPS.index(c)]
        blend = np.zeros(table.shape[-1])
        for ib,wb in control_weights(b,cubic):
            for ia,wa in control_weights(a,cubic):
                blend += wb*wa*table[ib,ia]
        err = errors(grid,basis(grid,poles) @ blend,target)
        output.append([c,b,a,*err,int(np.all(err<=LIMIT))])
    name = "baseline_fractional_cubic.csv" if cubic else "baseline_fractional_audit.csv"
    with (OUT/name).open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["cps","boost","atten","low_db","mid_db","high_db","phase_deg","pass"])
        writer.writerows(output)
    for joint in (False,True):
        group=[r for r in output if bool(r[1]*r[2])==joint]
        print("fractional", "joint" if joint else "axis",sum(r[-1] for r in group),len(group))


def peak_bound(grid, target, original, upper, design, upper_design):
    relative = design / target[:, None]
    baseline = original / target
    limit_db = np.select([grid < 100, grid < 1000], [.20, .15], default=.10)
    maximum = 10 ** (limit_db / 20)
    minimum_real = np.cos(np.deg2rad(2)) / maximum
    maximum_imag = maximum * np.sin(np.deg2rad(2))
    # Внешний прямоугольник содержит каждый отклик, проходящий АЧХ и фазу.
    matrix = np.vstack([relative.real, -relative.real, relative.imag, -relative.imag])
    rhs = np.r_[maximum-baseline.real, baseline.real-minimum_real,
                maximum_imag-baseline.imag, maximum_imag+baseline.imag]
    # Проекция на направление исходного отклика даёт нижнюю границу модуля.
    rotation = np.conj(upper)/abs(upper)
    constraints = np.vstack([np.column_stack([matrix, np.zeros(len(rhs))]),
                             np.column_stack([(rotation[:,None]*upper_design).real,
                                              -np.ones(len(upper))])])
    result = linprog([0,0,1], A_ub=constraints, b_ub=np.r_[rhs,-abs(upper)],
                     bounds=[(None,None),(None,None),(0,None)],method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    return 20*np.log10(result.fun)


def main():
    poles,tables = arrays(json.loads(MODEL.read_text()))
    check_fractional(poles,tables)
    check_fractional(poles,tables,cubic=True)
    grid = curve(FLAT)[0]
    spec,extended = targets(TRAIN_KEYS,grid)
    weights = np.array([tables[CPS.index(c),b,a] for c,b,a in TRAIN_KEYS])
    predicted = weights @ basis(EXT,poles).T
    # Для отклонения семейства достаточно одной обучающей настройки.
    i = np.argmax(abs(predicted).max(axis=1))
    original = basis(grid,poles) @ weights[i]
    rows = []
    for center in np.arange(19000,21001,100):
        for bandwidth in (25,50,100,200,400,800,1600,3200):
            pole = np.array([np.exp(2*np.pi*(-bandwidth+1j*center)/SR)])
            bound = peak_bound(grid,spec[i],original,predicted[i],
                               basis(grid,pole)[:,-2:],basis(EXT,pole)[:,-2:])
            rows.append((center,bandwidth,bound))
    path = OUT/"local_pair_train_bounds.csv"
    with path.open("w",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["center_hz","pole_decay_hz","peak_lower_bound_db"])
        writer.writerows(rows)
    print("train", TRAIN_KEYS[i],"original peak",20*np.log10(abs(predicted[i]).max()),
          "reference peak",20*np.log10(abs(extended[i]).max()),"best bound",min(rows,key=lambda r:r[2]))
    full_f = np.linspace(18000,SR/2,2049)
    print("baseline peak through Nyquist for same state",20*np.log10(abs(basis(full_f,poles)@weights[i]).max()))


if __name__=="__main__":
    main()
