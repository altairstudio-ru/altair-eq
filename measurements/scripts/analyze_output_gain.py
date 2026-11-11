#!/usr/bin/env python3
"""Analyze Output trim response against the 0 dB trim sweep."""
import csv,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
GRID=json.loads((ROOT/'measurements/grid/pultec_lf_grid.json').read_text(encoding='utf-8'))
MAN=json.loads((ROOT/'measurements/results/pultec_lf/render_manifest.json').read_text(encoding='utf-8'))
AN=ROOT/'measurements/scripts/analyze.py'; out=ROOT/'measurements/results/pultec_lf/output_gain'; out.mkdir(parents=True,exist_ok=True)
rows=[r for r in GRID['rows'] if r['group']=='output_gain']
tables={}
for r in rows:
 e=MAN['rows'][r['id']]; name=r['id']; csvp=out/(name+'.csv'); jsonp=out/(name+'.json')
 cp=subprocess.run([sys.executable,str(AN),'transfer',str(ROOT/e['input']),str(ROOT/e['output']),str(jsonp),'--latency','86','--csv',str(csvp)],cwd=ROOT,capture_output=True,text=True)
 if cp.returncode: raise SystemExit(cp.stderr)
 with csvp.open(newline='',encoding='utf-8') as f: tables[name]=list(csv.DictReader(f))
base=next(r for r in rows if r['plugin']['output_gain_ui']==0.0)
bmap={float(x['freq_hz']):float(x['magnitude_db']) for x in tables[base['id']]}
summary=[]
for r in rows:
 m=[]
 for x in tables[r['id']]:
  hz=float(x['freq_hz']); measured=float(x['magnitude_db'])-bmap[hz]; requested=float(r['plugin']['output_gain_ui']); m.append((hz,measured,measured-requested))
 summary.append({'id':r['id'],'requested_db':r['plugin']['output_gain_ui'],'measured_delta_vs_zero_trim_db':{
  'min':min(x[1] for x in m),'max':max(x[1] for x in m),'mean':sum(x[1] for x in m)/len(m)},
  'max_abs_error_from_requested_db':max(abs(x[2]) for x in m),'frequency_bins':len(m)})
dest=ROOT/'measurements/results/pultec_lf/output_gain_analysis.json'
dest.write_text(json.dumps({'schema':'altair-eq.output-trim-analysis/1','method':'sweep FFT transfer; relative to measured 0 dB setting','summary':summary},indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2))
