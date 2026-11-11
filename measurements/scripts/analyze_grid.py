#!/usr/bin/env python3
"""Analyze completed Pultec static grid renders and service nulls."""
import csv, hashlib, json, subprocess, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
GRID=json.loads((ROOT/'measurements/grid/pultec_lf_grid.json').read_text(encoding='utf-8'))
MAN=json.loads((ROOT/'measurements/results/pultec_lf/render_manifest.json').read_text(encoding='utf-8'))
OUT=ROOT/'measurements/results/pultec_lf/transfer'
AN=ROOT/'measurements/scripts/analyze.py'
GROUPS={'boost_only','atten_only','boost_atten_trick','sr_reduced'}
def run(args):
    cp=subprocess.run([sys.executable,str(AN),*map(str,args)],cwd=ROOT,capture_output=True,text=True)
    if cp.returncode: raise RuntimeError(' '.join(map(str,args))+'\n'+cp.stdout+'\n'+cp.stderr)
    return cp.stdout.strip()

def read_csv(path):
    with path.open(newline='',encoding='utf-8') as f: return list(csv.DictReader(f))

def main():
    if MAN.get('status')!='complete' or len(MAN.get('rows',{}))!=GRID['row_count']:
        raise SystemExit('render manifest is incomplete')
    OUT.mkdir(parents=True,exist_ok=True)
    rows={r['id']:r for r in GRID['rows']}
    configs={}
    for r in GRID['rows']:
        if r['group'] in GROUPS:
            cfg=r['id'].rsplit('-',1)[0]
            configs.setdefault(cfg,{})[r['signal']]=r
    summary=[]
    for idx,(cfg,signals) in enumerate(sorted(configs.items()),1):
        if not {'impulse','sweep_log'} <= set(signals):
            raise SystemExit('missing paired static signals: '+cfg)
        records={}
        for signal,row in signals.items():
            entry=MAN['rows'][row['id']]
            source=ROOT/entry['input']; rendered=ROOT/entry['output']
            stem=cfg+'-'+('imp' if signal=='impulse' else 'swp')
            report=OUT/(stem+'.json'); table=OUT/(stem+'.csv')
            run(['transfer',source,rendered,report,'--latency',MAN['latency_samples'][str(row['sample_rate_hz'])], '--fmin',20,'--fmax',min(18000,row['sample_rate_hz']/2-1),'--csv',table])
            records[signal]={'json':str(report.relative_to(ROOT)),'csv':str(table.relative_to(ROOT))}
        a=read_csv(ROOT/records['impulse']['csv']); b=read_csv(ROOT/records['sweep_log']['csv'])
        pairs=zip(a,b)
        magdiff=[]; phasediff=[]
        for x,y in pairs:
            magdiff.append(abs(float(x['magnitude_db'])-float(y['magnitude_db'])))
            d=float(x['phase_deg'])-float(y['phase_deg'])
            phasediff.append(abs((d+180)%360-180))
        summary.append({'configuration_id':cfg,'group':signals['impulse']['group'],
                        'sample_rate_hz':signals['impulse']['sample_rate_hz'],
                        'parameters':signals['impulse']['plugin'],
                        'impulse_transfer':records['impulse'],'sweep_transfer':records['sweep_log'],
                        'max_impulse_sweep_magnitude_difference_db':max(magdiff),
                        'median_impulse_sweep_magnitude_difference_db':sorted(magdiff)[len(magdiff)//2],
                        'max_impulse_sweep_phase_difference_deg':max(phasediff),
                        'csv_point_count':len(magdiff)})
        if idx%10==0: print('[{}/{}] analyzed {}'.format(idx,len(configs),cfg),flush=True)
    service=[]
    for r in GRID['rows']:
        if r['group']!='service' or r['signal'] not in ('impulse','sweep_log'): continue
        entry=MAN['rows'][r['id']]
        if r['plugin']['fx_present'] is False:
            out=OUT/(r['id']+'-null.json')
            result=run(['null',ROOT/entry['input'],ROOT/entry['output'],out])
            service.append({'id':r['id'],'analysis':str(out.relative_to(ROOT)),'result':result})
        elif r['id'].startswith('svc-hostbypass') or r['id'].startswith('svc-eqoff'):
            source=ROOT/entry['input']; rendered=ROOT/entry['output']; stem=r['id']
            report=OUT/(stem+'.json'); table=OUT/(stem+'.csv')
            run(['transfer',source,rendered,report,'--latency',MAN['latency_samples'][str(r['sample_rate_hz'])],'--csv',table])
            service.append({'id':r['id'],'analysis':str(report.relative_to(ROOT)),'csv':str(table.relative_to(ROOT))})
    data={'schema':'altair-eq.pultec-lf-analysis/1','grid_sha256':MAN['grid_sha256'],
          'analyzed_configurations':len(summary),'configurations':summary,'service_checks':service}
    path=ROOT/'measurements/results/pultec_lf/analysis_manifest.json'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    diffs=[x['max_impulse_sweep_magnitude_difference_db'] for x in summary]
    print('analysis complete: {} configurations; max impulse/sweep magnitude difference {:.6g} dB; manifest {}'.format(len(summary),max(diffs),path))

if __name__=='__main__': main()
