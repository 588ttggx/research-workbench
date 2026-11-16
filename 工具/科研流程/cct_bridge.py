"""Read the supplied software's version-0 CCTF data via Microsoft's NRBF API."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import numpy as np

NATIVE_SCALE=3.4332275390625e-05
FORMAT_SOURCE='Supplied TeraAnalyzer 1.2.10.5 / ImportPlotFrom.ImportThread / ExplainImgFileHead'


def _pwsh():
    """Find PowerShell 7 on PATH, by recorded path, or in this workspace.

    The frozen replay imports this module from its code archive, so the module
    path cannot locate the tools folder; the run folder is still inside the
    workspace, which is why the working directory is searched as well.
    """
    found=shutil.which('pwsh.exe') or shutil.which('pwsh') or os.environ.get('RESEARCH_PWSH')
    if found and Path(found).is_file():return found
    roots=[Path(__file__).resolve().parents[2], *Path.cwd().parents]
    for root in roots:
        tools=root/'工具'/'PowerShell'
        if not tools.is_dir():continue
        for candidate in sorted(tools.glob('*/pwsh.exe'),reverse=True):
            if candidate.is_file():return str(candidate)
    return None


def runtime():
    pwsh=_pwsh()
    if not pwsh:raise ValueError('CCT 数据接入需要 Microsoft PowerShell / NRBF 组件')
    script="""$ErrorActionPreference='Stop'; $assembly=[Reflection.Assembly]::Load('System.Formats.Nrbf'); [ordered]@{powershell=$PSVersionTable.PSVersion.ToString();dotnet=[Environment]::Version.ToString();nrbf=$assembly.GetName().Version.ToString();nrbf_sha256=(Get-FileHash -LiteralPath $assembly.Location -Algorithm SHA256).Hash.ToLowerInvariant()} | ConvertTo-Json -Compress"""
    native=subprocess.run([pwsh,'-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if native.returncode:raise ValueError('Microsoft NRBF 读取组件未就绪，保留旧运行与产物')
    return json.loads(native.stdout.decode('utf-8-sig'))


def decode(inputs,folder,code_archive):
    folder=Path(folder);pwsh=_pwsh()
    if not pwsh:raise ValueError('CCT 数据接入需要当前 Microsoft PowerShell / NRBF 组件')
    source=[]
    for dataset in inputs:
        snapshot=(folder.parent/dataset['snapshot']).resolve()
        for item in dataset['files']:
            path=(snapshot/item['path']).resolve();path.relative_to(snapshot)
            source.append({'id':item['id'],'source':str(path),'sha256':item['sha256'],'dataset':dataset['id'],'path':item['path'],'extension':item['extension']})
    with tempfile.TemporaryDirectory(prefix='_cct_',dir=folder) as tmp:
        tmp=Path(tmp);records=[];arrays={}
        with zipfile.ZipFile(code_archive) as archive:script=archive.read('cct_decode.ps1').decode('utf-8-sig')
        # File IDs are relative-path identities and may repeat across collections.
        # Decode each collection separately; outputs stay keyed by dataset + file ID.
        for dataset in inputs:
            selected=[r for r in source if r['dataset']==dataset['id']]
            manifest=tmp/'input.json';manifest.write_text(json.dumps(selected,ensure_ascii=False),encoding='utf-8')
            env=os.environ.copy();env.update(RESEARCH_CCT_INPUT=str(manifest),RESEARCH_CCT_OUTPUT=str(tmp))
            native=subprocess.run([pwsh,'-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            if native.returncode:raise ValueError('配套格式读取未完成；仅支持已核验的 CCTF v0 Int32 数据，未猜解其他格式')
            decoded=json.loads((tmp/'decoded.json').read_text('utf-8-sig'))
            if isinstance(decoded,dict):decoded=[decoded]
            lookup={r['id']:r for r in decoded}
            for item in selected:
                meta=lookup[item['id']];array=np.fromfile(tmp/(item['id']+'.i32'),dtype='<i4')
                if len(array)!=meta['points']:raise ValueError('转换后样点数量不一致')
                key=dataset['id']+'__'+item['id'];arrays[key]=array
                records.append({**meta,**{k:item[k] for k in ('dataset','path','extension')},'array_key':key,'native_scale':NATIVE_SCALE})
        np.savez_compressed(folder/'waveforms.npz',**arrays)
        (folder/'waveform_sources.json').write_text(json.dumps({'format_source':FORMAT_SOURCE,'records':records,
            'decoder':'Microsoft System.Formats.Nrbf (data-only)','time_axis':'sample index; optical-delay mapping not yet verified',
            'amplitude':'integer ADC count and software native scale; physical unit not asserted',
            'scope':'软件实战演练；文件扩展名不证明材料类别、独立样品或实际参考配对'},ensure_ascii=False,indent=2),encoding='utf-8')
    return records,arrays
