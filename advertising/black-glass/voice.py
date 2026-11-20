"""Generate the opening dialogue and narrator takes with the two series voices."""
import json
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location

root = Path(__file__).resolve().parent
spec = spec_from_file_location('series_voice', root.parent/'troika-hyperframes-20261117/voice.py')
voice = module_from_spec(spec)
spec.loader.exec_module(voice)
story = json.loads((root/'story.json').read_text('utf-8'))
hook = [{'id': role, 'voice': role, 'say': words}
        for role, words in zip(('user', 'troika'), story[0][1], strict=True)]
voice.SPEC['episodes'] = [{'id': 'opening', 'beats': hook}, {'id':'chapter', 'beats':[
    {'id':str(i), 'voice':'user', 'say':' '.join(lines)}
    for i, (_, lines) in enumerate(story) if i > 0]}]
voice.OUT = root/'local/voices'
voice.generate()
