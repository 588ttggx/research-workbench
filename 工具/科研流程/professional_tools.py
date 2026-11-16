"""Task-scoped adapters to mature desktop tools; persisted products stay readable.

Launch arguments follow the pinned Cytoscape distribution's Karaf launcher and
VOSviewer manual. No shell interpolation, arbitrary programs, or session deletion.
"""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import zipfile
import re
import ctypes
import math
import unicodedata
import csv
import io
import xml.etree.ElementTree as ET
from filelock import FileLock
import requests
import workflow as w

CY = 'http://127.0.0.1:1235/v1'
LOCK = threading.Lock()
LAUNCH_LOCK = threading.Lock()
RUNTIME = '工具/Cytoscape/3.10.5/cytoscape-windows-3.10.5'
JAVA = '工具/Java17/jdk-17.0.20.1_1/jdk-17.0.20.1+1/bin/java.exe'
R_EXE = '工具/R/4.6.1/bin/Rscript.exe'


def _path(relative):
    path = (w.ROOT / relative).resolve()
    path.relative_to(w.ROOT.resolve())
    return path


def _relative(path):
    # Windows may supply an 8.3 alias for temporary or user directories.
    return Path(path).resolve().relative_to(w.ROOT.resolve()).as_posix()


def _graph_identity(data):
    """Visual dragging is not a new scientific network version."""
    source = json.loads(json.dumps(data))
    for group in ('nodes', 'edges'):
        rows = source.get('elements', {}).get(group, [])
        for row in rows:
            for key in ('position', 'renderedPosition', 'selected', 'selectable', 'grabbable', 'locked', 'classes', 'style'):
                row.pop(key, None)
        rows.sort(key=lambda row: str(row.get('data', {}).get('id', '')))
    return source


def r_environment():
    env = os.environ.copy()
    env.update(LC_ALL='English_United States.utf8', LANG='en_US.UTF-8',
               R_LIBS_USER=str(_path('工具/R/library')))
    return env


def _process_stamp(pid):
    """Check our recorded process identity, including creation time, not PID alone."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.c_void_p] * 4)]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        stamps = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(s) for s in stamps]):
            return None
        return str(stamps[0].value) if stamps[1].value == 0 else None
    finally:
        kernel.CloseHandle(handle)


def _launch(args, folder, env=None, *, cwd=None):
    folder.mkdir(parents=True, exist_ok=True)
    with LAUNCH_LOCK:
        old = w.read_json(folder / 'process.json', {})
        if old.get('stamp') and _process_stamp(old['pid']) == old['stamp']:
            return {'status': 'running', 'pid': old['pid'], 'reused': True}
        with (folder / 'startup.log').open('ab') as log:
            process = subprocess.Popen(args, cwd=cwd or w.ROOT, env=env, stdout=log, stderr=log,
                                       stdin=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
        w.write_json(folder / 'process.json', {'pid': process.pid, 'stamp': _process_stamp(process.pid), 'started': w.now()})
        return {'status': 'starting', 'pid': process.pid}


def start_teraanalyzer():
    config=w.read_json(w.ROOT/'工具/工具版本.json',{}).get('teraanalyzer',{})
    path=Path(config.get('executable','')).resolve()
    if not config.get('sha256') or path.name.lower()!='tdsanalyzer.exe' or not path.is_file():
        raise ValueError('已登记的 TeraAnalyzer 程序当前不可用。')
    if w.digest(path.read_bytes())!=config['sha256']:
        raise ValueError('TeraAnalyzer 程序版本已变化，请先核对工具登记。')
    result=_launch([str(path)],w.DATA/'native-tools/teraanalyzer',cwd=path.parent)
    return {**result,'version':config.get('version'),'message':'已打开配套软件；数值与物理标尺验证仍沿原记录。'}


def status():
    try:
        response = requests.get(CY + '/version', timeout=2)
        response.raise_for_status()
        cy = {'installed': True, 'online': True, 'version': response.json()}
    except (requests.RequestException, ValueError):
        cy = {'installed': _path(RUNTIME + '/framework').is_dir(), 'online': False}
    cct=w.read_json(w.ROOT/'output/科研工作区重构/配套软件接入.json',{})
    registered=w.read_json(w.ROOT/'工具/工具版本.json',{}).get('teraanalyzer',{})
    return {'cytoscape': cy,
            'cct':{'available':bool(registered.get('executable') and Path(registered['executable']).is_file()),'version':registered.get('version'),
                   'format_connected':bool(cct.get('format')),'native_ui_verified':bool(cct.get('native_acceptance',{}).get('complete')),
                   'native_import_verified':bool(cct.get('native_acceptance',{}).get('imported')),
                   'message':'原厂软件已读入隔离副本，点数与格式解码一致；CSV 数值和物理标尺仍待核验。' if cct.get('native_acceptance',{}).get('imported') else '配套文件格式已核对并用于实战演练；原生程序界面尚未验收。'},
            'vosviewer': {'installed': _path('工具/VOSviewer/1.6.21/VOSviewer.jar').is_file(), 'version': '1.6.21'},
            'bibliometrix': {'installed': _path('工具/R/library/bibliometrix/DESCRIPTION').is_file(), 'version': '5.5.0'},
            'rspace': {**__import__('rspace_runtime').deployment(),'message':'原生 ELN/Inventory 沿本机管理器维护；软件恢复见维护记录，真实实验与签署按实际任务核验'}}


def cytoscape_arguments():
    runtime = _path(RUNTIME); framework = runtime / 'framework'; data = _path('工具/Cytoscape/data')
    data.mkdir(parents=True, exist_ok=True)
    # Reproduce the vendor Java launch directly to support Chinese paths and a
    # detached Windows process. Keep the configuration within this project.
    karaf = data / 'karaf_data'; (karaf / 'tmp').mkdir(parents=True, exist_ok=True)
    # Windows AF_UNIX paths have a short byte limit; keep Java's temporary socket
    # names out of the long project path, in the user's configured cache drive.
    temporary = w.ROOT/'runtime/cache/Cytoscape/tmp'
    args = [str(_path(JAVA)), '-Xms512M', '-Xmx2048M', '-Dsun.java2d.d3d=false', '-Dsun.java2d.noddraw=true', '-Dprism.order=sw', '-Djdk.util.zip.disableZip64ExtraFieldValidation=true',
            '--add-reads=java.xml=java.logging',
            '--add-exports=java.base/org.apache.karaf.specs.locator=java.xml,ALL-UNNAMED',
            '--patch-module', 'java.base=' + str(framework / 'lib/endorsed/org.apache.karaf.specs.locator-4.3.7.jar'),
            '--patch-module', 'java.xml=' + str(framework / 'lib/endorsed/org.apache.karaf.specs.java.xml-4.3.7.jar'),
            '-p', str(framework / 'lib/openjfx/win'), '--add-modules', 'javafx.base,javafx.swing,javafx.media,javafx.web']
    for module in ['java.base/java.security', 'java.base/java.net', 'java.base/java.lang', 'java.base/java.util',
                   'java.naming/javax.naming.spi', 'java.rmi/sun.rmi.transport.tcp']:
        args += ['--add-opens', module + '=ALL-UNNAMED']
    for module in ['java.base/sun.net.www.protocol.file', 'java.base/sun.net.www.protocol.ftp',
                   'java.base/sun.net.www.protocol.http', 'java.base/sun.net.www.protocol.https',
                   'java.base/sun.net.www.protocol.jar', 'java.base/sun.net.www.content.text',
                   'jdk.xml.dom/org.w3c.dom.html', 'jdk.naming.rmi/com.sun.jndi.url.rmi',
                   'java.rmi/sun.rmi.registry', 'java.security.sasl/com.sun.security.sasl']:
        args += ['--add-exports', module + '=ALL-UNNAMED']
    classpath = [framework / 'conf', *sorted((framework / 'lib/boot').glob('*.jar')),
                 *sorted((framework / 'lib/jdk9plus').glob('*.jar'))]
    args += ['-classpath', os.pathsep.join(map(str, classpath))]
    properties = {'karaf.instances': karaf / 'instances', 'karaf.home': framework, 'karaf.base': framework,
                  'karaf.etc': framework / 'etc', 'karaf.log': karaf / 'log', 'karaf.data': karaf,
                  'java.io.tmpdir': temporary, 'user.home': data, 'cytoscape.home': runtime,
                  'jdk.net.unixdomain.tmpdir': temporary,
                  'karaf.startLocalConsole': 'false', 'karaf.startRemoteShell': 'false',
                  'java.util.logging.config.file': framework / 'etc/java.util.logging.properties'}
    args += ['-D' + k + '=' + str(v) for k, v in properties.items()]
    args += ['org.cytoscape.launcher.internal.Launcher', '-R', '1235']
    return args


def start_cytoscape():
    if status()['cytoscape']['online']:
        return {'status': 'running'}
    runtime = _path(RUNTIME); data = _path('工具/Cytoscape/data')
    args = cytoscape_arguments()
    env = os.environ.copy(); env['JAVA_HOME'] = str(_path(JAVA).parent.parent)
    return {**_launch(args, data, env), 'message': '正在启动 Cytoscape，稍后可再次打开网络'}


def _cy(method, path, **kwargs):
    response = requests.request(method, CY + path, timeout=90, **kwargs)
    response.raise_for_status()
    if response.content and 'json' in response.headers.get('Content-Type', ''):
        result = response.json()
        if isinstance(result, dict) and result.get('errors'):
            raise ValueError('Cytoscape 操作未完成：' + str(result['errors'])[:400])
        return result
    return response.content


def _native_label(label):
    """Reflow the dashboard's narrow labels for desktop cards, preserving text."""
    lines = str(label).split('\n')
    heading, body = (lines[0], ''.join(lines[1:])) if len(lines) > 1 else ('', lines[0])
    wrapped = []; row = ''; width = 0
    for char in body:
        advance = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if row and width + advance > 24:
            wrapped.append(row); row = ''; width = 0
        row += char; width += advance
    if row:
        wrapped.append(row)
    return '\n'.join(([heading] if heading else []) + wrapped)


def _svg_text(content):
    """Normalize the native Windows renderer's UTF-8/GB18030 XML without lossy decoding."""
    try:text=content.decode('utf-8')
    except UnicodeDecodeError:text=content.decode('gb18030')
    text=re.sub(r'(<\?xml[^>]*encoding=[\"\x27])[^\"\x27]+',r'\g<1>UTF-8',text,count=1)
    if ET.fromstring(text).tag!='{http://www.w3.org/2000/svg}svg':raise ValueError('专业图不是有效 SVG')
    return text


def _native_analysis(suid, folder, source):
    """Run Cytoscape's Analyzer on this exact saved network, retaining native results."""
    expected=source['elements']; ids={str(n['data']['id']) for n in expected['nodes']}
    edge_ids={str(e['data']['id']) for e in expected.get('edges',[])}
    saved=w.read_json(folder/'网络分析.json',{})
    if saved.get('schema')==1 and saved.get('source_hash')==folder.name and all(
            (folder/name).is_file() and w.digest((folder/name).read_bytes())==sha
            for name,sha in saved.get('checksums',{}).items()) and len(saved.get('checksums',{}))==3:
        return {**saved,'reused':True}
    current_nodes=_cy('GET',f'/networks/{suid}/tables/defaultnode')['rows']
    current_edges=_cy('GET',f'/networks/{suid}/tables/defaultedge')['rows']
    if {str(n.get('id')) for n in current_nodes}!=ids or {str(e.get('id')) for e in current_edges}!=edge_ids:
        raise ValueError('桌面网络的对象或关系已修改；保留精修内容，请重新导入当前问题网络')
    native=_cy('POST','/commands/analyzer/analyze',json={'network':'SUID:'+str(suid),'directed':False,'selectedOnly':False})
    metrics=native.get('data',{}) if isinstance(native,dict) else {}
    if int(metrics.get('nodeCount',-1))!=len(ids) or int(metrics.get('edgeCount',-1))!=len(expected.get('edges',[])):
        raise ValueError('原生网络分析未返回当前范围的完整结果；已有图保留')
    tables={name:_cy('GET',f'/networks/{suid}/tables/'+table)['rows']
            for name,table in [('节点指标.csv','defaultnode'),('关系指标.csv','defaultedge')]}
    if {str(n.get('id')) for n in tables['节点指标.csv']}!=ids or len(tables['关系指标.csv'])!=len(expected.get('edges',[])):
        raise ValueError('原生网络指标表不完整，未登记为成功分析')
    for name,rows in tables.items():
        output=io.StringIO(newline='');columns=sorted({key for row in rows for key in row})
        writer=csv.DictWriter(output,fieldnames=columns);writer.writeheader()
        # CSV is a viewing/export copy; original native values are kept in JSON.
        for row in rows:
            writer.writerow({key:('\t'+value if isinstance(value,str) and value.startswith(('=','+','-','@')) else value)
                             for key,value in row.items()})
        w.atomic_text(folder/name,'\ufeff'+output.getvalue())
    pending=folder/'网络分析.pending.cys'
    _cy('POST','/session',params={'file':str(pending)})
    deadline=time.monotonic()+15
    while not zipfile.is_zipfile(pending):
        if time.monotonic()>deadline:raise ValueError('网络分析会话尚未保存完整；自动布局会话保留')
        time.sleep(.2)
    pending.replace(folder/'网络分析.cys')
    result={'status':'completed','schema':1,'source_hash':folder.name,'tool':'Cytoscape Analyzer',
            'directed':False,'scope':'当前显示网络，包含已显示的待核关系；拓扑指标不代表证据强度或科研重要性',
            'created':w.now(),'nodes':len(ids),'edges':len(expected.get('edges',[])),
            'components':int(metrics['ncc']),
            'isolated':[{'id':n['id'],'label':n.get('label') or n.get('name') or n['id']} for n in tables['节点指标.csv'] if n.get('IsSingleNode')],
            'native':native,'tables':tables,
            'checksums':{name:w.digest((folder/name).read_bytes()) for name in ('节点指标.csv','关系指标.csv','网络分析.cys')}}
    w.write_json(folder/'网络分析.json',result)
    return result


def _analysis_result(suid, folder, source):
    try:return _native_analysis(suid,folder,source)
    except (requests.RequestException,ValueError,KeyError,TypeError,OSError):
        return {'status':'unavailable','message':'原生网络分析未完成，已有图和来源保留，可稍后重试'}


def _pack_native_view(suid, view_id, folder):
    """Use Graphviz's native overlap removal and component packing, not a new layout engine.

    Cytoscape lays out the relationships. ccomps / neato / gvpack preserve the
    network, remove rectangular overlaps, and pack disconnected components.
    Only positions return to Cytoscape; scientific nodes/edges never change.
    """
    config = w.read_json(w.ROOT / '工具/工具版本.json', {}).get('graphviz', {})
    binary = _path(config.get('executable', '工具/Graphviz/unavailable')).parent
    if not all((binary / name).is_file() for name in ('ccomps.exe', 'neato.exe', 'gvpack.exe')):
        raise ValueError('Graphviz 排版工具暂不可用；网络来源和已有专业图保留')
    view = _cy('GET', f'/networks/{suid}/views/first')['elements']
    nodes = view['nodes']; edges = view.get('edges', [])
    names = {node['data']['id']: 'n' + str(i) for i, node in enumerate(nodes)}
    rows = ['digraph native { node [shape=box, fixedsize=true, label="", width=3.194445, height=1.527778];']
    for node in nodes:
        x, y = node['position']['x'], node['position']['y']
        if not all(math.isfinite(float(v)) for v in (x, y)):
            raise ValueError('专业网络坐标尚未生成；来源文件保留')
        rows.append(names[node['data']['id']] + f' [pos="{float(x)},{-float(y)}!"];')
    for edge in edges:
        rows.append(names[edge['data']['source']] + ' -> ' + names[edge['data']['target']] + ';')
    rows.append('}')
    source = '\n'.join(rows).encode('utf-8')
    w.atomic_text(folder / 'native-layout.dot', source.decode('utf-8'))

    def run(name, args, content, allowed=(0,)):
        result = subprocess.run([str(binary / name), *args], input=content, capture_output=True,
                                timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode not in allowed or not result.stdout:
            raise ValueError('专业网络排版未完成；来源和已有图保留：' + name)
        return result.stdout

    components = run('ccomps.exe', ['-x'], source, (0, 1))  # 1 means disconnected, not failure.
    spaced = run('neato.exe', ['-n', '-Goverlap=prism', '-Gsep=+16', '-Tdot'], components)
    packed = run('gvpack.exe', ['-g', '-m48'], spaced)
    output = json.loads(run('neato.exe', ['-n2', '-Tjson0'], packed))
    positions = {row['name']: [float(v) for v in row['pos'].split(',')]
                 for row in output.get('objects', []) if 'pos' in row}
    if set(positions) != set(names.values()) or not all(
            len(xy) == 2 and all(math.isfinite(v) for v in xy) for xy in positions.values()):
        raise ValueError('专业排版返回的节点不完整；不替换已有专业图')
    w.atomic_text(folder / 'packed-layout.dot', packed.decode('utf-8'))
    for node in nodes:
        xy = positions[names[node['data']['id']]]
        _cy('PUT', f'/networks/{suid}/views/{view_id}/nodes/{node["data"]["SUID"]}', json=[
            {'visualProperty': 'NODE_X_LOCATION', 'value': xy[0]},
            {'visualProperty': 'NODE_Y_LOCATION', 'value': -xy[1]}])
    return {'tool': 'Graphviz ' + str(config.get('version', '')), 'overlap': 'prism',
            'components': 'ccomps + gvpack', 'nodes': len(nodes), 'edges': len(edges)}


def export_cytoscape(data):
    """Create a separate workspace-managed network, never overwrite a refined one."""
    elements = data.get('elements', {})
    nodes = elements.get('nodes', []); edges = elements.get('edges', [])
    if not 1 <= len(nodes) <= 600 or len(edges) > 3000:
        raise ValueError('请选择 1–600 个节点的当前问题网络')
    ids = {str(n.get('data', {}).get('id', '')) for n in nodes}
    if '' in ids or len(ids) != len(nodes):
        raise ValueError('网络节点需要唯一稳定 ID')
    if any(e.get('data', {}).get('source') not in ids or e.get('data', {}).get('target') not in ids for e in edges):
        raise ValueError('关系两端需要包含在导出网络中')
    if len(json.dumps(data)) > 1500000:
        raise ValueError('网络资料过大，请缩小当前范围')
    if data.get('layout') not in (None, 'breadthfirst', 'fcose'):
        raise ValueError('请选择证据分层或自然聚类布局')
    token = w.digest(json.dumps({'design': 8, 'source': _graph_identity(data)}, sort_keys=True, ensure_ascii=False))[:20]
    folder = _path('output/科研工作区重构/专业网络') / token
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / 'source.cyjs').is_file():
        w.write_json(folder / 'source.cyjs', {**data, 'source_hash': token, 'authority': '工作区索引；专业图文件为可重建产物'})
    if not status()['cytoscape']['online']:
        saved=w.read_json(folder/'receipt.json',{})
        readable=saved.get('status')=='exported' and all(
            saved.get(k) and (w.ROOT/saved[k]).is_file() for k in ('svg','png','session'))
        try:launch=start_cytoscape()
        except (OSError,ValueError):
            if not readable:raise
            launch={'status':'unavailable','message':'桌面工具暂不可用，已保存图仍可查看'}
        if readable:return {**saved,'reused':True,'native_status':launch['status'],
                             'message':launch.get('message','')}
        return {**launch, 'source': _relative(folder / 'source.cyjs')}
    with LOCK, FileLock(str(folder.parent / '.native-operation.lock'), timeout=180):
        title = '研序 · ' + data.get('project', '') + ' · ' + token
        checkpoint = w.read_json(folder / 'network.json', {})
        suid = checkpoint.get('network_suid')
        loaded = _cy('GET', '/networks')
        if suid not in loaded or _cy('GET', '/networks/' + str(suid)).get('data', {}).get('name') != title:
            native = json.loads(json.dumps(elements))
            for node in native['nodes']:
                label = str(node['data'].get('label') or node['data']['id'])
                node['data']['display_label'] = _native_label(label[:160])
                node['data']['visual_role'] = 'focus' if node['data'].get('root') else node['data'].get('kind','其他')
            for edge in native.get('edges',[]):
                edge['data']['visual_state'] = 'candidate' if edge['data'].get('pending') else 'recorded'
                edge['data']['display_label'] = str(edge['data'].get('label') or '') + (' · 待核' if edge['data'].get('pending') else '')
            result = _cy('POST', '/networks', params={'title': title}, json={'data': {'name': title}, 'elements': native})
            suid = result['networkSUID']
            w.write_json(folder / 'network.json', {'network_suid': suid, 'title': title})
        saved = w.read_json(folder / 'receipt.json', {})
        if saved.get('status') == 'exported' and saved.get('network_suid') == suid and all((w.ROOT / saved[k]).is_file() for k in ('svg','png','session')):
            _cy('POST', '/commands/network/set current', json={'network': 'SUID:'+str(suid)})
            saved['analysis']=_analysis_result(suid,folder,data)
            w.write_json(folder/'receipt.json',saved)
            return {**saved, 'reused': True}
        style_name = '研序 · 证据网络 · ' + token
        style = {'title': style_name, 'defaults': [
            {'visualProperty': 'NETWORK_BACKGROUND_PAINT', 'value': '#FAFBFD'},
            {'visualProperty': 'NODE_FILL_COLOR', 'value': '#EEF3FA'},
            {'visualProperty': 'NODE_BORDER_PAINT', 'value': '#BBC8D8'},
            {'visualProperty': 'NODE_BORDER_WIDTH', 'value': 1.2},
            {'visualProperty': 'NODE_WIDTH', 'value': 230.0}, {'visualProperty': 'NODE_HEIGHT', 'value': 110.0},
            {'visualProperty': 'NODE_SHAPE', 'value': 'ROUND_RECTANGLE'},
            {'visualProperty': 'NODE_LABEL_COLOR', 'value': '#223044'},
            {'visualProperty': 'NODE_LABEL_FONT_FACE', 'value': 'Microsoft YaHei,plain,15'},
            {'visualProperty': 'NODE_LABEL_WIDTH', 'value': 210.0},
            {'visualProperty': 'NODE_LABEL_FONT_SIZE', 'value': 15},
            {'visualProperty': 'EDGE_WIDTH', 'value': 1.3},
            {'visualProperty': 'EDGE_TRANSPARENCY', 'value': 180},
            {'visualProperty': 'EDGE_LABEL_COLOR', 'value': '#5B6B7C'},
            {'visualProperty': 'EDGE_LABEL_FONT_FACE', 'value': 'Microsoft YaHei,plain,11'},
            {'visualProperty': 'EDGE_LABEL_FONT_SIZE', 'value': 11},
            {'visualProperty': 'EDGE_STROKE_UNSELECTED_PAINT', 'value': '#9AAABB'},
            {'visualProperty': 'EDGE_TARGET_ARROW_SHAPE', 'value': 'DELTA'},
            {'visualProperty': 'EDGE_TARGET_ARROW_UNSELECTED_PAINT', 'value': '#9AAABB'}],
            'mappings': [{'mappingType': 'passthrough', 'mappingColumn': 'display_label', 'mappingColumnType': 'String',
                          'visualProperty': 'NODE_LABEL'},
                         {'mappingType':'passthrough','mappingColumn':'display_label','mappingColumnType':'String','visualProperty':'EDGE_LABEL'},
                         {'mappingType':'discrete','mappingColumn':'visual_state','mappingColumnType':'String','visualProperty':'EDGE_LINE_TYPE',
                          'map':[{'key':'candidate','value':'LONG_DASH'},{'key':'recorded','value':'SOLID'}]},
                         {'mappingType':'discrete','mappingColumn':'visual_state','mappingColumnType':'String','visualProperty':'EDGE_STROKE_UNSELECTED_PAINT',
                          'map':[{'key':'candidate','value':'#B19770'},{'key':'recorded','value':'#879DB6'}]},
                         {'mappingType':'discrete','mappingColumn':'visual_role','mappingColumnType':'String','visualProperty':'NODE_LABEL_COLOR',
                          'map':[{'key':'focus','value':'#FFFFFF'}]},
                         {'mappingType': 'discrete', 'mappingColumn': 'visual_role', 'mappingColumnType': 'String',
                          'visualProperty': 'NODE_FILL_COLOR', 'map': [
                              {'key': k, 'value': v} for k, v in {'focus':'#345D55','主线':'#E0EBE5','论文':'#EAF0F7',
                              '项目记录': '#E6EEE7', '项目': '#E6EEE7', '报告': '#F0EAF6', '分析报告':'#F0EAF6',
                              '阅读笔记': '#FFF3DF', '背景': '#E7EDF5', '方法记录': '#E4F1EE', '研究问题': '#F3EBDF'}.items()]}]}
        if style_name not in _cy('GET', '/styles'):
            _cy('POST', '/styles', json=style)
        _cy('PUT', '/styles/' + style_name + '/dependencies', json=[
            {'visualPropertyDependency': 'nodeSizeLocked', 'enabled': False}])
        _cy('GET', '/apply/styles/' + style_name + '/' + str(suid))
        # CyREST returns before Swing has necessarily repainted. Confirm the
        # actual view properties before using dimensions for layout or export.
        views = _cy('GET', '/networks/' + str(suid) + '/views')
        view_id = views[0]
        first_node = _cy('GET', '/networks/' + str(suid) + '/views/first')['elements']['nodes'][0]['data']['SUID']
        deadline = time.monotonic() + 15
        while True:
            props = _cy('GET', f'/networks/{suid}/views/{view_id}/nodes/{first_node}')
            props = {p['visualProperty']: p['value'] for p in props}
            if props.get('NODE_WIDTH') == 230 and props.get('NODE_LABEL'):
                break
            if time.monotonic() > deadline:
                raise ValueError('专业网络样式尚未刷新；来源文件已保留，可以重试')
            time.sleep(.2)
        layout = ('hierarchical' if data.get('layout') == 'breadthfirst' or
                  (data.get('layout') is None and data.get('mode') in ('structure', 'question')) else 'cose')
        before = _cy('GET', '/apply/layouts/' + layout + '/parameters')
        try:
            settings = ({'idealEdgeLength': 100, 'repulsionStrength': 65, 'gravityStrength': 60, 'springStrength': 60,
                         'smartEdgeLengthCalc': False, 'smartRepulsionRangeCalc': False} if layout == 'cose' else
                        {'nodeHorizontalSpacing': 280, 'nodeVerticalSpacing': 220, 'componentSpacing': 80,
                         'bandGap': 140, 'rightMargin': 1800})
            _cy('PUT', '/apply/layouts/' + layout + '/parameters', json=[{'name': k, 'value': v} for k, v in settings.items()])
            _cy('GET', '/apply/layouts/' + layout + '/' + str(suid))
        finally:
            _cy('PUT', '/apply/layouts/' + layout + '/parameters', json=[{'name': p['name'], 'value': p['value']} for p in before])
        packing = _pack_native_view(suid, view_id, folder)
        points = [node['position'] for node in _cy('GET', f'/networks/{suid}/views/first')['elements']['nodes']]
        if any(abs(a['x']-b['x']) < 242 and abs(a['y']-b['y']) < 122
               for i,a in enumerate(points) for b in points[i+1:]):
            raise ValueError('当前网络节点仍有重叠，请缩小范围或在 Cytoscape 中精修；来源文件保留')
        _cy('POST', '/commands/view/update', json={'network': 'SUID:'+str(suid)})
        _cy('GET', '/apply/fit/' + str(suid))
        # Wait for the native renderer, not only the task response. Require two
        # stable images; a failed refresh never replaces a previous receipt.
        previous_png = None
        for _ in range(12):
            time.sleep(.25)
            png = _cy('GET', '/networks/' + str(suid) + '/views/first.png', params={'w': 2400})
            if png == previous_png:
                break
            previous_png = png
        else:
            raise ValueError('专业图仍在刷新；旧产物保留，请稍后重试')
        svg = _cy('GET', '/networks/' + str(suid) + '/views/first.svg')
        if not isinstance(svg, bytes) or b'<svg' not in svg:
            raise ValueError('Cytoscape 未生成有效矢量图；旧产物保留')
        w.atomic_text(folder / '自动布局.svg', _svg_text(svg))
        if not isinstance(png, bytes) or not png.startswith(b'\x89PNG'):
            raise ValueError('Cytoscape 预览生成未完成；已有产物保留')
        (folder / '自动布局.png').write_bytes(png)
        # The generic "session save" command can save the current session name
        # instead of honoring a new destination. CyREST's dedicated Save As API
        # explicitly requires the new file and avoids touching a refined file.
        _cy('POST', '/session', params={'file': str(folder / '自动布局.cys')})
        deadline = time.monotonic() + 15
        while not zipfile.is_zipfile(folder / '自动布局.cys'):
            if time.monotonic() > deadline:
                raise ValueError('专业会话尚未保存完整；来源文件和旧产物保留')
            time.sleep(.2)
        result = {'status': 'exported', 'id': token, 'network_suid': suid, 'nodes': len(nodes), 'edges': len(edges),
                  'svg': _relative(folder / '自动布局.svg'),
                  'png': _relative(folder / '自动布局.png'),
                  'session': _relative(folder / '自动布局.cys'),
                  'source': _relative(folder / 'source.cyjs'), 'layout': layout, 'packing': packing,
                  'tool': 'Cytoscape Desktop 3.10.5', 'created': w.now()}
        result['analysis']=_analysis_result(suid,folder,data)
        w.write_json(folder / 'receipt.json', result)
        return result


def _cluster_parameters(algorithm):
    common={'clusterAttribute':'workspace_cluster','createGroups':False,'selectedOnly':False,'showUI':False}
    if algorithm=='glay':return {**common,'undirectedEdges':True}
    if algorithm=='mcode':
        # CyREST converts JSON numbers to Double; this app's integer tunables
        # require decimal strings. These exact native parameters are recorded.
        return {**common,'degreeCutoff':'2','scoreCutoff':'0.2','haircut':True,'fluff':False,
                'includeLoops':False,'kCore':'2','maxDepth':'100'}
    raise ValueError('请选择按关联分组（GLay）或查找密集关联（MCODE）')


def _cluster_membership(source, rows, native):
    ids={str(n['data']['id']) for n in source['elements']['nodes']}
    if {str(n.get('id')) for n in rows}!=ids or len(rows)!=len(ids):
        raise ValueError('聚类返回的对象范围与原网络不一致，未替换已有产物')
    lookup={int(n['SUID']):n for n in rows};assigned=set();groups=[]
    for group in native.get('data',{}).get('clusters',[]):
        members=[]
        for node in group.get('nodes',[]):
            row=lookup.get(int(node.get('suid',-1)))
            if not row or row['id'] in assigned:raise ValueError('聚类返回重复或未知对象')
            assigned.add(row['id']);members.append(row['id'])
        if not members:raise ValueError('聚类返回空分组')
        groups.append({'number':int(group['clusterNumber']),'members':sorted(members),
                       **{key:group[key] for key in ('clusterScore','modularity') if key in group}})
    if len(groups)!=int(native.get('data',{}).get('nclusters',-1)):
        raise ValueError('原生聚类结果不完整')
    return groups,sorted(ids-assigned)


def _saved_cluster(folder):
    saved=w.read_json(folder/'聚类分析.json',{})
    files=('分组对象.csv','聚类分析.cys','聚类分析.svg','聚类分析.png')
    if saved.get('status')=='completed' and saved.get('schema')==2 and saved.get('id')==folder.name and set(saved.get('checksums',{}))==set(files) and all(
            (folder/name).is_file() and w.digest((folder/name).read_bytes())==saved['checksums'][name] for name in files):
        return {**saved,'reused':True}
    return None


def _cluster_layout(suid,folder,source,groups,unassigned):
    config=w.read_json(w.ROOT/'工具/工具版本.json',{}).get('graphviz',{})
    binary=_path(config.get('executable','工具/Graphviz/unavailable')).parent/'dot.exe'
    if not binary.is_file():raise ValueError('专业分组排版工具暂不可用，原图和原生分组保留')
    elements=source['elements'];names={n['data']['id']:'n'+str(i) for i,n in enumerate(elements['nodes'])}
    rows=['digraph grouped { graph [overlap=prism, sep="+20", pack=true, packmode=clust, start=42];',
          'node [shape=box, fixedsize=true, label="", width=3.194445, height=1.527778];']
    for group in [*groups,*([{'number':0,'members':unassigned}] if unassigned else [])]:
        rows.append('subgraph cluster_'+str(group['number'])+' { graph [margin=36];')
        rows.extend(names[node]+';' for node in group['members']);rows.append('}')
    for edge in elements.get('edges',[]):
        rows.append(names[edge['data']['source']]+' -> '+names[edge['data']['target']]+';')
    rows.append('}');content='\n'.join(rows).encode('utf-8')
    run=subprocess.run([str(binary),'-Kfdp','-Tjson0'],input=content,capture_output=True,timeout=45,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if run.returncode or not run.stdout:raise ValueError('专业分组排版未完成，原图保留：'+run.stderr.decode('utf-8',errors='replace')[:240])
    result=json.loads(run.stdout);positions={row['name']:[float(v) for v in row['pos'].split(',')]
            for row in result.get('objects',[]) if 'pos' in row}
    if set(positions)!=set(names.values()) or not all(len(xy)==2 and all(math.isfinite(v) for v in xy) for xy in positions.values()):
        raise ValueError('专业分组排版对象不完整，未替换已有图')
    w.atomic_text(folder/'cluster-layout.dot',content.decode('utf-8'))
    view=_cy('GET',f'/networks/{suid}/views/first');nodes=view['elements']['nodes']
    table=_cy('GET',f'/networks/{suid}/tables/defaultnode')['rows']
    original_ids={int(n['SUID']):n['id'] for n in table}
    if {original_ids.get(int(n['data']['SUID'])) for n in nodes}!=set(names):raise ValueError('排版前网络范围已变化')
    view_id=_cy('GET',f'/networks/{suid}/views')[0]
    for node in nodes:
        xy=positions[names[original_ids[int(node['data']['SUID'])]]]
        _cy('PUT',f'/networks/{suid}/views/{view_id}/nodes/{node["data"]["SUID"]}',json=[
                {'visualProperty':'NODE_X_LOCATION','value':xy[0]},
                {'visualProperty':'NODE_Y_LOCATION','value':-xy[1]}])
    return {'tool':'Graphviz '+str(config.get('version','')),'algorithm':'fdp with cluster subgraphs','start':42}


def _run_cluster(algorithm,parameters,suid):
    try:return _cy('POST','/commands/cluster/'+algorithm,json={**parameters,'network':'SUID:'+str(suid)})
    except requests.HTTPError as error:
        response=error.response
        if algorithm=='mcode' and response is not None and response.status_code==500:
            try:body=response.json()
            except ValueError:raise error
            if any('this.results' in str(row.get('message','')) and 'null' in str(row.get('message',''))
                   for row in body.get('errors',[])):
                return {'status':'needs_attention','native':body,
                        'message':'本机扩展未返回可用的密集关联分组。原图和全部对象保留，可用 GLay 按关联分组，或在桌面版核对 MCODE 参数。'}
        raise


def cluster_network(data, progress=None):
    """Local clusterMaker2 algorithms on a separate, source-bound derived network."""
    progress=progress or (lambda label:None)
    original=artifact_folder('cytoscape',data.get('id'))
    source=w.read_json(original/'source.cyjs',{})
    if not source.get('elements',{}).get('nodes'):raise ValueError('请先打开并保存当前专业网络')
    if source.get('professional_analysis'):raise ValueError('请从原网络选择聚类，避免对派生结果反复分组')
    algorithm=data.get('algorithm','glay');parameters=_cluster_parameters(algorithm)
    cached=w.read_json(original/'cluster_index.json',{}).get(algorithm)
    if cached:
        saved=_saved_cluster(artifact_folder('cytoscape',cached))
        if saved and saved.get('source_id')==original.name and saved.get('algorithm')==algorithm:
            return saved  # Saved professional products work without the desktop tool.
    progress('正在核对原网络与本机聚类扩展')
    # Check the actual installed app; no remote cluster algorithms or uploads.
    apps=_cy('GET','/commands/apps/list installed')
    match=re.search(r'name: clusterMaker2, version: ([^,\r\n]+), status: Installed',apps.decode('utf-8'))
    if not match:raise ValueError('本机 clusterMaker2 扩展尚未就绪，请先在 Cytoscape 安装官方扩展')
    version=match.group(1)
    source.pop('source_hash',None);source.pop('authority',None)
    derived={**source,'professional_analysis':{'schema':2,'type':'structural_cluster','source_network':original.name,
                'algorithm':algorithm,'version':version,'parameters':parameters}}
    progress('正在准备独立专业会话，保留原图与精修内容')
    opened=export_cytoscape(derived)
    if opened.get('status')!='exported':raise ValueError('Cytoscape 尚未就绪，请稍后重试；原网络保留')
    folder=artifact_folder('cytoscape',opened['id']);suid=opened['network_suid']
    with LOCK,FileLock(str(folder.parent/'.native-operation.lock'),timeout=180):
        files=('分组对象.csv','聚类分析.cys','聚类分析.svg','聚类分析.png')
        saved=_saved_cluster(folder)
        if saved:return saved
        nodes=_cy('GET',f'/networks/{suid}/tables/defaultnode')['rows']
        edges=_cy('GET',f'/networks/{suid}/tables/defaultedge')['rows']
        if ({str(n.get('id')) for n in nodes}!={str(n['data']['id']) for n in source['elements']['nodes']} or
                {str(e.get('id')) for e in edges}!={str(e['data']['id']) for e in source['elements'].get('edges',[])}):
            raise ValueError('派生桌面网络已有人工修改，保留精修内容，请从新的当前范围重试')
        progress('正在本机运行 '+algorithm.upper()+'，科研关系保持原审核状态')
        native=_run_cluster(algorithm,parameters,suid)
        if native.get('status')=='needs_attention':
            result={**native,'id':folder.name,'source_id':original.name,'algorithm':algorithm,
                    'tool':'clusterMaker2 '+version,'parameters':parameters,'created':w.now()}
            w.write_json(folder/'聚类分析.json',result)
            return result
        rows=_cy('GET',f'/networks/{suid}/tables/defaultnode')['rows']
        groups,unassigned=_cluster_membership(source,rows,native)
        current_edges=_cy('GET',f'/networks/{suid}/tables/defaultedge')['rows']
        if {str(e.get('id')) for e in current_edges}!={str(e.get('id')) for e in edges} or len(current_edges)!=len(edges):
            raise ValueError('聚类改变了原网络关系范围，未登记为成功结果')
        progress('正在用专业排版排列关联分组')
        layout=_cluster_layout(suid,folder,source,groups,unassigned)
        # Native grouping is a display attribute, never a persisted research relation.
        palette=['#DCEBE4','#DCE6F3','#F1E4D7','#E7E0F1','#DEEDEB','#F2E9C8','#E9DFE3','#E0E7D1']
        style_name='研序 · 关联分组 · '+folder.name+' · '+w.digest(json.dumps(groups,sort_keys=True))[:8]
        base=_cy('GET','/styles/研序 · 证据网络 · '+folder.name)
        base['title']=style_name
        base['mappings']=[m for m in base['mappings'] if m.get('visualProperty') not in ('NODE_FILL_COLOR','NODE_LABEL_COLOR')]
        base['defaults']=[p for p in base['defaults'] if p['visualProperty']!='NODE_FILL_COLOR']+[
            {'visualProperty':'NODE_FILL_COLOR','value':'#F0F1F3'}]
        base['mappings'].append({'mappingType':'discrete','mappingColumn':'workspace_cluster','mappingColumnType':'Integer',
              'visualProperty':'NODE_FILL_COLOR','map':[{'key':str(g['number']),'value':palette[i%len(palette)]} for i,g in enumerate(groups)]})
        if style_name not in _cy('GET','/styles'):_cy('POST','/styles',json=base)
        _cy('PUT','/styles/'+style_name+'/dependencies',json=[{'visualPropertyDependency':'nodeSizeLocked','enabled':False}])
        _cy('GET','/apply/styles/'+style_name+'/'+str(suid))
        progress('正在保存原生分组、专业图与可编辑会话')
        _cy('POST','/commands/view/update',json={'network':'SUID:'+str(suid)})
        _cy('GET','/apply/fit/'+str(suid))
        previous=None
        for _ in range(12):
            time.sleep(.25)
            png=_cy('GET',f'/networks/{suid}/views/first.png',params={'w':2400})
            if png==previous:break
            previous=png
        else:raise ValueError('专业聚类图尚未稳定，原图保留，可稍后重试')
        svg=_cy('GET',f'/networks/{suid}/views/first.svg')
        if not isinstance(svg,bytes) or b'<svg' not in svg or not isinstance(png,bytes) or not png.startswith(b'\x89PNG'):
            raise ValueError('聚类图未完整生成；原网络和旧图保留')
        pending=folder/'聚类分析.pending.cys';_cy('POST','/session',params={'file':str(pending)})
        deadline=time.monotonic()+15
        while not zipfile.is_zipfile(pending):
            if time.monotonic()>deadline:raise ValueError('聚类会话尚未保存完整；原图保留')
            time.sleep(.2)
        member_group={node:g['number'] for g in groups for node in g['members']}
        output=io.StringIO(newline='');writer=csv.writer(output);writer.writerow(['id','group','label'])
        for node in source['elements']['nodes']:
            n=node['data'];label=str(n.get('full_label') or n.get('label') or n['id'])
            writer.writerow([n['id'],member_group.get(n['id'],''),'\t'+label if label.startswith(('=','+','-','@')) else label])
        w.atomic_text(folder/'分组对象.csv','\ufeff'+output.getvalue())
        w.atomic_text(folder/'聚类分析.svg',_svg_text(svg));(folder/'聚类分析.png').write_bytes(png)
        pending.replace(folder/'聚类分析.cys')
        result={'status':'completed','schema':2,'id':folder.name,'source_id':original.name,'source_hash':folder.name,
             'algorithm':algorithm,'tool':'clusterMaker2 '+version,'parameters':parameters,'created':w.now(),
             'nodes':len(rows),'edges':len(edges),'groups':groups,'unassigned':unassigned,'native':native,'layout':layout,
             'scope':'当前显示网络的拓扑分组；不表示相同科研结论、证据强度或已核查关系。未归组对象保留。',
             'checksums':{name:w.digest((folder/name).read_bytes()) for name in files}}
        w.write_json(folder/'聚类分析.json',result)
        with FileLock(str(original/'.cluster-index.lock'),timeout=10):
            index=w.read_json(original/'cluster_index.json',{});index[algorithm]=folder.name
            w.write_json(original/'cluster_index.json',index)
        return result


def run_bibliometrics(data):
    source = data.get('source', 'zotero')
    if source not in ('zotero', 'wos', 'scopus', 'pubmed'):
        raise ValueError('请选择 Zotero 或专业数据库导出格式')
    project = str(data.get('project') or '')[:100]
    network_limit=int(data.get('network_limit',300))
    if not 20<=network_limit<=1000:raise ValueError('每类网络的对象上限应为 20–1000')
    keys = []
    if source == 'zotero':
        library = w.read_json(w.LIBRARY, {'records': []})['records']
        members=set(__import__('project_materials').snapshot(project)['papers']) if project else None
        selected=[p for p in library if members is None or p['id'] in members]
        keys = sorted({p['zotero_key'] for p in selected if p.get('zotero_key')})
        if not keys:
            raise ValueError('当前范围没有 Zotero 题录，请先同步文献')
        response = requests.get(w.ZOTERO + '/items', params={'itemKey': ','.join(keys), 'format': 'bibtex', 'limit':100}, timeout=60)
        response.raise_for_status()
        content = response.content
        suffix = 'bib'
    else:
        content = str(data.get('content') or '').encode('utf-8')
        suffix = 'csv' if source == 'scopus' else 'txt'
    if not content or len(content) > 20*1024*1024:
        raise ValueError('题录文件为空或超过 20 MB')
    script = w.HERE / 'r/analyze_bibliography.R'
    token = w.digest(content + script.read_bytes() + source.encode() + project.encode() + str(network_limit).encode())[:20]
    folder = _path('output/科研工作区重构/文献计量') / token
    folder.mkdir(parents=True, exist_ok=True)
    with LOCK:
        old = w.read_json(folder / 'receipt.json', {})
        if old.get('status') == 'completed' and (folder / 'analysis.json').is_file():
            return {**old, 'reused': True}
        path = folder / ('input.' + suffix)
        path.write_bytes(content)
        with (folder / 'analysis.log').open('wb') as log:
            run = subprocess.run([str(_path(R_EXE)), str(script), str(path), str(folder),
                                  str(_path('工具/R/library')), source,str(network_limit)], env=r_environment(),
                                 stdout=log, stderr=log, timeout=180,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode or not (folder / 'analysis.json').is_file():
            raise ValueError('Bibliometrix 未完成，请核对导出格式和题录字段；输入与错误日志已保留')
        analysis = w.read_json(folder / 'analysis.json')
        result = {'status': 'completed', 'id': token, 'project': project, 'source': source, 'source_keys': keys, 'source_hash': w.digest(content),
                  'created': w.now(), 'analysis': analysis, 'files': sorted(p.name for p in folder.iterdir() if p.suffix in ('.svg','.gml','.rds','.csv','.bib','.txt') or p.name.endswith('.plotly.json'))}
        w.write_json(folder / 'receipt.json', result)
        return result


def start_biblioshiny():
    try:
        response = requests.get('http://127.0.0.1:8506', timeout=2)
        if response.ok:
            return {'status': 'running', 'url': 'http://127.0.0.1:8506'}
    except requests.RequestException:
        pass
    result = _launch([str(_path(R_EXE)), str(w.HERE / 'r/start_biblioshiny.R'),
                      str(_path('工具/R/library'))], _path('工具/R/Biblioshiny'), r_environment())
    return {**result, 'url': 'http://127.0.0.1:8506'}


def start_vosviewer(data):
    folder = artifact_folder('bibliometrics', data.get('id'))
    receipt = w.read_json(folder / 'receipt.json', {})
    network = str(data.get('network') or '')
    row = receipt.get('analysis', {}).get('networks', {}).get(network, {})
    if row.get('status') != 'exported' or not row.get('gml'):
        raise ValueError('所选网络缺少题录，不能生成专业图')
    gml = folder / row['gml']
    gml.resolve().relative_to(folder.resolve())
    # New attempts have separate files. VOSviewer prompts before overwriting;
    # immutable attempt folders also protect a user's refined map.
    target = folder / ('VOSviewer-' + network)
    saved = w.read_json(target / 'receipt.json', {})
    if all((target / name).is_file() for name in ('map.txt','network.txt','network.svg','network.png')):
        args = [str(_path(JAVA)), '-Dsun.java2d.d3d=false', '-Dsun.java2d.noddraw=true',
                '-jar', str(_path('工具/VOSviewer/1.6.21/VOSviewer.jar')),
                '-map', (target / 'map.txt').as_uri(), '-network', (target / 'network.txt').as_uri()]
    else:
        args = [str(_path(JAVA)), '-Dsun.java2d.d3d=false', '-Dsun.java2d.noddraw=true',
                '-jar', str(_path('工具/VOSviewer/1.6.21/VOSviewer.jar')),
                '-map', (folder / (network + '-map.txt')).as_uri(), '-network', (folder / (network + '-network.txt')).as_uri(),
                '-run_layout', '-run_clustering',
                '-save_map', str(target / 'map.txt'), '-save_network', str(target / 'network.txt'),
                '-save_screenshot_svg', str(target / 'network.svg'), '-save_screenshot_png', str(target / 'network.png')]
        # A partial previous attempt must not trigger an invisible overwrite dialog.
        if target.exists() and any(target.glob('*.txt')):
            process = w.read_json(target / 'process.json', {})
            if process.get('stamp') and _process_stamp(process['pid']) == process['stamp']:
                return {'status': 'starting', 'id': data['id'], 'network': network, 'message': 'VOSviewer 正在生成网络'}
            target = target / ('retry-' + str(time.time_ns()))
            args = [a.replace(str(folder / ('VOSviewer-' + network)), str(target)) for a in args]
    result = _launch(args, target)
    w.write_json(target / 'receipt.json', {'tool': 'VOSviewer 1.6.21', 'source': _relative(gml), 'created': w.now()})
    return {**result, 'id': data['id'], 'network': network, 'folder': _relative(target)}


def artifact_folder(kind, identifier):
    if kind not in ('cytoscape', 'bibliometrics') or not re.fullmatch(r'[a-f0-9]{20}', str(identifier or '')):
        raise ValueError('专业产物 ID 无效')
    return _path('output/科研工作区重构/' + ('专业网络' if kind == 'cytoscape' else '文献计量')) / identifier


def artifact_file(kind, identifier, filename):
    folder = artifact_folder(kind, identifier)
    path = (folder / str(filename)).resolve()
    path.relative_to(folder.resolve())
    if (path.suffix not in ('.svg','.png','.cys','.cyjs','.gml','.rds','.csv','.bib','.txt') and not path.name.endswith('.plotly.json') and path.name not in ('网络分析.json','聚类分析.json')) or not path.is_file():
        raise ValueError('专业产物不存在')
    return path


def bibliography_record(identifier):
    root=artifact_folder('bibliometrics',identifier)
    row=w.read_json(root/'receipt.json',{})
    if row.get('status')!='completed' or row.get('id')!=identifier:
        raise ValueError('已保存的文献计量分析不存在')
    row['files']=sorted(set(row.get('files',[])+[p.relative_to(root).as_posix() for p in root.glob('VOSviewer-*/**/*')
        if p.suffix in ('.svg','.png','.txt') and (p.parent/'network.png').is_file()]))
    return row


def bibliography_history(project):
    folder = _path('output/科研工作区重构/文献计量')
    records = []
    for path in folder.glob('*/receipt.json'):
        row = w.read_json(path, {})
        if row.get('status') == 'completed' and row.get('id') == path.parent.name and (not project or row.get('project') == project):
            records.append(row)
    records.sort(key=lambda r: r.get('created', ''), reverse=True)
    grouped = {}
    for row in records:
        root = folder / row['id']
        source_hash = row.get('source_hash')
        if not source_hash:
            inputs = [p for p in root.glob('input.*') if p.is_file()]
            source_hash = w.digest(inputs[0].read_bytes()) if inputs else row['id']
        identity = (row.get('project'), row.get('source', 'zotero'), source_hash)
        row['files']=bibliography_record(row['id'])['files']
        if identity in grouped:
            grouped[identity].setdefault('previous_versions', []).append(row)
            continue
        grouped[identity] = row
    return list(grouped.values())[:30]


if __name__ == '__main__':
    import sys
    print(json.dumps(cytoscape_arguments() if sys.argv[1:] == ['launch-arguments'] else start_cytoscape() if sys.argv[1:] == ['start-cytoscape'] else status(), ensure_ascii=True))
