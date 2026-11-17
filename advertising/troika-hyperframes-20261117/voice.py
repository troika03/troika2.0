"""Original narration in the energetic voices selected for this video series.

Only the configured zero-price model is accepted. Credentials stay in memory.
No reference audio, cloning, or creator voices are sent to the provider.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
import json
import os
import subprocess
import time
import requests

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SPEC = json.loads((ROOT / 'episodes.json').read_text(encoding='utf-8'))
OUT = ROOT / 'materials' / 'voice-final'


def credential():
    key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not key:
        for line in (REPO / 'data/test-runtime/.env').read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('\"\'')
                break
    if not key:
        raise RuntimeError('Speech credential unavailable')
    return key

def generate():
    OUT.mkdir(parents=True, exist_ok=True)
    headers = {'Authorization': 'Bearer ' + credential(), 'Content-Type': 'application/json', 'X-Title': 'Troika original short stories'}
    response = requests.get('https://openrouter.ai/api/v1/models?output_modalities=speech', headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f'Model discovery HTTP {response.status_code}')
    model = next((m for m in response.json()['data'] if m['id'] == SPEC['model']), None)
    if not model or not model.get('pricing') or any(Decimal(str(v)) != 0 for v in model['pricing'].values()):
        raise RuntimeError('Configured zero-price voice model is unavailable')
    jobs = [(ep['id'] + '-' + b['id'], b) for ep in SPEC['episodes'] for b in ep['beats'] if b.get('say')]
    selected = os.environ.get('VOICE_ONLY')
    if selected:
        jobs = [item for item in jobs if item[0] == selected]
    role = os.environ.get('VOICE_ROLE')
    if role:
        jobs = [item for item in jobs if item[1]['voice'] == role]
    def one(item):
        name, beat = item
        path = OUT / (name + '.mp3')
        limit = len(beat['say']) / 8 + 2
        if path.exists() and path.stat().st_size > 1000 and os.environ.get('VOICE_FORCE') != '1':
            duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))
            if duration <= limit:
                return name + ' cached'
        payload = {'model': SPEC['model'], 'voice': SPEC['voices'][beat['voice']], 'input': beat['say'], 'response_format': 'mp3'}
        for attempt in range(3):
            try:
                res = requests.post('https://openrouter.ai/api/v1/audio/speech', headers=headers, json=payload, timeout=(20, 160), allow_redirects=False)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise RuntimeError(name + ': speech connection failed') from None
                time.sleep(2)
                continue
            if res.status_code == 200 and len(res.content) > 1000:
                pending = path.with_suffix('.pending.mp3')
                pending.write_bytes(res.content)
                duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(pending)]))
                if duration > limit:
                    if attempt == 2:
                        raise RuntimeError(name + ': unexpectedly long speech')
                    continue
                pending.replace(path)
                return f'{name}: {duration:.2f}s'
            if res.status_code not in (429,500,502,503,504) or attempt == 2:
                raise RuntimeError(f'{name}: speech HTTP {res.status_code}')
            time.sleep(3)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(one, item) for item in jobs]):
            print(f.result(), flush=True)

if __name__ == '__main__':
    generate()
