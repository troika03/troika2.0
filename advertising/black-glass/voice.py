"""Generate the eight Russian narration takes using the series voice."""
import json
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location

root = Path(__file__).resolve().parent
spec = spec_from_file_location('series_voice', root.parent/'troika-hyperframes-20261117/voice.py')
voice = module_from_spec(spec)
spec.loader.exec_module(voice)
story = json.loads((root/'story.json').read_text('utf-8'))
voice.SPEC['episodes'] = [{'id':'chapter', 'beats':[
    {'id':str(i), 'voice':'user', 'say':' '.join(lines)}
    for i, (_, lines) in enumerate(story)]}]
voice.OUT = root/'local/voices'
voice.generate()
