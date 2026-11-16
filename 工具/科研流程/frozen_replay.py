"""Replay an internal snapshot; no user-supplied commands or executable uploads."""
import hashlib
import json
from pathlib import Path
import sys


def run(folder):
    folder=Path(folder).resolve()
    parameters=json.loads((folder/'parameters.json').read_text('utf-8'))
    source=(folder/parameters['input']).resolve()
    repository=folder.parents[1]
    source.relative_to((repository/'datasets').resolve())
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=parameters['input_sha256']:
        raise ValueError('Frozen input checksum mismatch')
    code=folder/'code.zip'
    if hashlib.sha256(code.read_bytes()).hexdigest()!=parameters['code_archive_sha256']:
        raise ValueError('Frozen code checksum mismatch')
    sys.path.insert(0,str(code))
    from data_analysis import compute
    from scientific_figures import export
    result=compute(raw.decode('utf-8'),parameters['kind'],parameters['options'])
    outputs=folder/'computed';outputs.mkdir(exist_ok=True)
    (folder/'metrics.json').write_text(json.dumps(result['metrics'],ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    (outputs/'figure.plotly.json').write_text(json.dumps(result['figure'],ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    export(result['figure'],outputs,parameters['run_id'])


if __name__=='__main__':run(Path(__file__).parent)
