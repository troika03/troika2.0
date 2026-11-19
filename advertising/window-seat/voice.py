"""Generate independent Russian voices with the free series speech workflow."""
from pathlib import Path
import json
from importlib.util import module_from_spec, spec_from_file_location

root = Path(__file__).resolve().parent
spec = spec_from_file_location('series_voice', root.parent/'troika-hyperframes-20261117/voice.py')
service = module_from_spec(spec)
spec.loader.exec_module(service)
story = json.loads((root/'story.json').read_text('utf-8'))
service.SPEC['episodes'] = [{'id':'voice','beats':[
    {'id':f'{index:02}','voice':speaker,'say':words}
    for index,(speaker,words) in enumerate(story)
]}]
service.OUT = root/'local/voices'
service.generate()
