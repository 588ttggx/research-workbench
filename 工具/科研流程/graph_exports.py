"""Professional directed layout via Graphviz; source graph and last good export persist."""
import json
import html
from locale import getencoding
from pathlib import Path
import subprocess
import textwrap
import uuid
from urllib.parse import urlencode,urlparse
import workflow as w
from research_store import Store

THEME_VERSION=3
TYPES={'Dataset':('数据','#E8F4F0','#397E6D'),'RawData':('原始数据','#E8F4F0','#397E6D'),
       'Code':('代码','#EDF1F9','#566C9B'),'Environment':('环境','#EFF1F3','#626E7A'),
       'RUN':('运行','#FBF0DD','#92702D'),'Result':('结果','#F0ECF8','#75619E'),
       'Figure':('图表','#F8ECEF','#A26678'),'Paper':('文献','#ECF1F8','#5A7196'),
       'Claim':('论断','#F0ECF8','#75619E')}


def _title(node):
    return node['data'].get('title') or {'Code':'分析代码快照','Environment':'运行环境','RUN':'分析运行'}.get(node['kind'],node['id'])


def _url(node,graph):
    base='http://127.0.0.1:8503/';navigation=node.get('navigation')
    if navigation:return base+'#'+navigation['route']+'?'+urlencode({'id':navigation['id']})
    if node.get('owner')=='RSpace':
        uri=node.get('uri') or ''
        return uri if urlparse(uri).scheme in ('http','https') else None
    if node['kind']=='Dataset' and node['data'].get('purpose')=='software_validation':return base+'#analyze?'+urlencode({'dataset':node['id']})
    runs=[n for n in graph['nodes'] if n['kind']=='RUN']
    selected=node if node['kind']=='RUN' else next((n for n in runs if n['id']==node['data'].get('run_id')),None)
    if not selected and node['kind'] in ('Figure','Result'):
        parents={node['id']};front={node['id']};found=set();by_id={n['id']:n for n in graph['nodes']}
        while front:
            reached={i for i in front if by_id[i]['kind']=='RUN'};found|=reached
            next_ids={e['target'] for e in graph['relations'] if e['source'] in front-reached and e['kind'] in ('DerivedFrom','ProducedBy','Uses')}-parents
            if not next_ids:break
            parents|=next_ids;front=next_ids
        origins=[n for n in runs if n['id'] in found]
        if len(origins)==1:selected=origins[0]
    if not selected and len(runs)==1:selected=runs[0]
    if not selected:return None
    if selected['data'].get('purpose')=='software_validation':
        figure=node['data'].get('artifact','figure.svg').split('.')[0] if node['kind']=='Figure' else 'source' if node['kind'] in ('Code','Environment') else 'waveform'
        return base+'#analyze?'+urlencode({'validation':selected['id'],'figure':figure})
    if selected['data'].get('analysis_id'):return base+'#run?'+urlencode({'id':selected['data']['analysis_id']})
    return None


def export(identifier,store=None):
    from research_records import trace
    graph=trace(identifier,store=store);token=w.digest(json.dumps([THEME_VERSION,graph],sort_keys=True,ensure_ascii=False))[:20]
    folder=w.ROOT/'output/科研工作区重构/来源图';folder.mkdir(parents=True,exist_ok=True)
    dot=folder/(token+'.dot');svg=folder/(token+'.svg')
    q=lambda value:json.dumps(str(value),ensure_ascii=False)
    validation=any(n['data'].get('purpose')=='software_validation' for n in graph['nodes'])
    title='软件实战演练 · 来源链' if validation else '科研来源链'
    subtitle=str(len(graph['nodes']))+' 项来源 · '+str(len(graph['relations']))+' 条已登记关系'
    if validation:subtitle+=' · 物理标尺、材料及实际参考配对仍未核实'
    heading='<<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="4"><TR><TD ALIGN="LEFT"><FONT POINT-SIZE="20"><B>'+title+'</B></FONT></TD></TR><TR><TD ALIGN="LEFT"><FONT COLOR="#667582" POINT-SIZE="11">'+html.escape(subtitle)+'</FONT></TD></TR></TABLE>>'
    rows=['digraph provenance {','graph [rankdir=LR, bgcolor="#FAFAF8", pad=0.4, nodesep=0.36, ranksep=0.6, fontname="Microsoft YaHei", fontcolor="#263744", labelloc=t, labeljust=l, label='+heading+'];',
          'node [shape=box,style="rounded,filled",fontname="Microsoft YaHei",fontsize=12,penwidth=1.1,margin="0.14,0.10"];',
          'edge [color="#A2ADB7",fontcolor="#697682",fontname="Microsoft YaHei",fontsize=10,arrowsize=0.65,penwidth=1.05];']
    for node in graph['nodes']:
        kind,fill,color=TYPES.get(node['kind'],(node['kind'],'#F1F3F4','#687581'))
        text=str(_title(node));lines=textwrap.wrap(text,width=27)[:3] or [node['id']]
        label='<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3"><TR><TD ALIGN="LEFT"><FONT COLOR="'+color+'" POINT-SIZE="10">'+html.escape(kind+' · '+node['owner'])+'</FONT></TD></TR>'
        label+=''.join('<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="12">'+html.escape(line)+'</FONT></TD></TR>' for line in lines)
        label+='<TR><TD ALIGN="LEFT"><FONT COLOR="#6D7A84" POINT-SIZE="9">'+html.escape(node['id'])+'</FONT></TD></TR></TABLE>>'
        attrs=['label='+label,'fillcolor='+q(fill),'color='+q(color),'tooltip='+q(text+' · '+node['id'])]
        link=_url(node,graph)
        if link:attrs+=['URL='+q(link),'target="_top"']
        rows.append(q(node['id'])+' ['+','.join(attrs)+'];')
    for edge in graph['relations']:
        reverse=edge['kind'] in ('Uses','ProducedBy','DerivedFrom');source,target=(edge['target'],edge['source']) if reverse else (edge['source'],edge['target'])
        label={'Uses':'输入','ProducedBy':'生成','DerivedFrom':'派生'}.get(edge['kind'],edge['kind'])
        rows.append(q(source)+' -> '+q(target)+' [label='+q(label)+',tooltip='+q(edge['source']+' '+edge['kind']+' '+edge['target'])+',style='+q('solid' if edge['status']=='VERIFIED' else 'dashed')+'];')
    rows.append('}');w.atomic_text(dot,'\n'.join(rows))
    if not svg.exists():
        config=w.read_json(w.ROOT/'工具/工具版本.json',{}).get('graphviz',{})
        exe=(w.ROOT/config.get('executable','')).resolve()
        if not exe.is_file():return {'dot':dot.relative_to(w.ROOT).as_posix(),'status':'tool_unavailable'}
        temporary=svg.with_name(token+'-'+uuid.uuid4().hex+'.svg')
        try:
            # Keep the native renderer independent of output-directory permissions and path encoding.
            result=subprocess.run([str(exe),'-Tsvg'],input=dot.read_bytes(),capture_output=True,
                                  timeout=45,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:
                stderr=result.stderr.decode(getencoding(),errors='replace')
                reason=next((line.strip() for line in stderr.splitlines() if line.lstrip().startswith('Error:')),'')
                raise ValueError(f'专业来源图生成未完成（Graphviz 退出码 {result.returncode}）'+
                                 ('。'+reason[:220] if reason else ''))
            if b'<svg' not in result.stdout:raise ValueError('专业来源图生成未完成，Graphviz 未返回 SVG')
            temporary.write_bytes(result.stdout)
            temporary.replace(svg)
        finally:temporary.unlink(missing_ok=True)
    return {'status':'exported','path':svg.relative_to(w.ROOT).as_posix(),'dot':dot.relative_to(w.ROOT).as_posix(),'id':token,'sha256':w.digest(svg.read_bytes()),'missing':graph['missing']}


def read_svg(identifier):
    import re
    if not re.fullmatch('[a-f0-9]{20}',identifier):raise ValueError('图产物不存在')
    return (w.ROOT/'output/科研工作区重构/来源图'/(identifier+'.svg')).read_bytes()
