"""Generate the approved dialogue using the product's configured free voice workflow."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import json

root = Path(__file__).resolve().parent
spec = spec_from_file_location('series_voice', root.parent / 'troika-hyperframes-20261117' / 'voice.py')
module = module_from_spec(spec)
spec.loader.exec_module(module)
lines = json.loads((root / 'story.json').read_text(encoding='utf-8'))
module.SPEC['episodes'] = [{'id':'line', 'beats':[
    {'id':str(i), 'voice':role, 'say':line} for i, (role,line) in enumerate(lines)
]}]
module.OUT = root / 'local' / 'voices'
module.generate()
