"""Run HyperFrames checks and take the changed frames for human visual review."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent
CLI = Path.home()/'.agents/skills/hyperframes/scripts/plugin-cli.mjs'
ENV = dict(os.environ, TEMP=str(ROOT.parents[1]/'work/hyperframes-20261117/temp'), TMP=str(ROOT.parents[1]/'work/hyperframes-20261117/temp'), npm_config_cache=str(ROOT.parents[1]/'work/hyperframes-20261117/npm-cache'))

def one(ep):
    project = ROOT if ep['id']=='coffee' else ROOT/'episodes'/ep['id']
    for command,name in [(['check','--json'],'check'),(['snapshot','--review','--output','qa-final'],'snapshot-final')]:
        with (project/(name+'.json' if name=='check' else name+'.log')).open('w',encoding='utf-8') as out, (project/(name+'-stderr.log')).open('w',encoding='utf-8') as err:
            result=subprocess.run(['node',str(CLI)]+command,cwd=project,env=ENV,stdout=out,stderr=err)
        if result.returncode:
            print(ep['id'],name,'FAILED',result.returncode,flush=True)
            return
    data=json.loads((project/'check.json').read_text(encoding='utf-8-sig'))
    print(ep['id'],'ok',data['ok'],[(k,v.get('errorCount'),v.get('warningCount')) for k,v in data.items() if isinstance(v,dict) and 'findings' in v],flush=True)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(one,json.loads((ROOT/'timelines.json').read_text(encoding='utf-8'))))
