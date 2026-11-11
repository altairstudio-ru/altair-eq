#!/usr/bin/env python3
"""Repeat three preselected static-grid impulse renders in fresh processes."""
import hashlib, json, random, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
grid=json.loads((root/'measurements/grid/pultec_lf_grid.json').read_text(encoding='utf-8'))
manifest_path=root/'measurements/results/pultec_lf/render_manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
imp=[r for r in grid['rows'] if r['signal']=='impulse' and r['group'] in ('boost_only','atten_only','boost_atten_trick')]
rng=random.Random(20261110)
chosen=[]
for group in ('boost_only','atten_only','boost_atten_trick'):
    candidates=[r for r in imp if r['group']==group and r['sample_rate_hz']==44100]
    chosen.append(rng.choice(candidates))
out=root/'measurements/renders/pultec_lf/repeats'
out.mkdir(parents=True,exist_ok=True)
results=[]
for row in chosen:
    original=manifest['rows'][row['id']]
    argv=list(original['command'])
    target=out/(row['id']+'-repeat.wav')
    argv[3]=str(target)
    cp=subprocess.run(argv,cwd=root,capture_output=True,text=True)
    if cp.returncode or not target.is_file():
        raise SystemExit('repeat failed '+row['id']+'\n'+cp.stderr)
    original_path=root/original['output']
    digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    result={'grid_id':row['id'],'configuration':row,'original_sha256':digest(original_path),
            'repeat_sha256':digest(target),'bit_identical_wav':digest(original_path)==digest(target),
            'repeat_path':str(target.relative_to(root)),'latency_gate':original.get('latency_reported'),
            'stdout':cp.stdout,'stderr':cp.stderr}
    results.append(result)
path=root/'measurements/results/pultec_lf/repeat_checks.json'
path.write_text(json.dumps({'schema':'altair-eq.pultec-lf-repeat/1','seed':20261110,
                            'results':results},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(results,indent=2,ensure_ascii=False))
