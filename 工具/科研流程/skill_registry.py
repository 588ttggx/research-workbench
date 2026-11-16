"""Built-in routes plus explicit, manually selected workspace skill registrations."""
from pathlib import Path
import re
import yaml
import workspace_runtime as w

SKILLS = {'idea-evaluator': {'label': '想法与可行性评估',
                    'required_refs': ['references/five-dimensions.md', 'references/fatal-flaws.md'],
                    'max_papers': 8,
                    'language_policy': 'user'},
 'tech-paper-template': {'label': '研究与论文结构',
                         'required_refs': ['references/thinking-template.md',
                                           'references/consistency-checks.md'],
                         'max_papers': 8,
                         'language_policy': 'user'},
 'figure-designer': {'label': '图表设计分析',
                     'required_refs': ['references/design-rules.md'],
                     'max_papers': 8,
                     'language_policy': 'user'},
 'pre-submission-reviewer': {'label': '稿件问题核查',
                             'required_refs': ['references/logic-and-structure.md',
                                               'references/grammar-rules.md',
                                               'references/latex-rules.md',
                                               'references/forbidden-patterns.md',
                                               'references/section-guides.md'],
                             'max_papers': 8,
                             'language_policy': 'user'},
 'deep-research': {'label': '文献线索分析',
                   'required_refs': ['references/search-strategy.md',
                                     'references/citation-protocol.md',
                                     'references/synthesis-framework.md'],
                   'max_papers': 8,
                   'language_policy': 'user'},
 'benchmark-paper-template': {'label': '评测研究框架',
                              'required_refs': ['references/benchmark-design.md', 'references/checklist.md'],
                              'max_papers': 8,
                              'language_policy': 'user'},
 'paper-polish': {'label': '文字润色',
                  'required_refs': ['references/ai-tone-guardrails.md', 'references/section-conventions.md'],
                  'max_papers': 8,
                  'language_policy': 'target'},
 'intro-drafter': {'label': '引言组织',
                   'required_refs': ['references/evidence-discipline.md',
                                     'references/flowchart.md',
                                     'references/prose-delivery.md'],
                   'max_papers': 8,
                   'language_policy': 'target'},
 'paper-writer': {'label': '基于材料写作',
                  'required_refs': ['references/evidence-discipline.md',
                                    'references/verification-ladder.md',
                                    'references/prose-delivery.md'],
                  'max_papers': 8,
                  'language_policy': 'target'},
 'rebuttal-guidance': {'label': '审稿意见分析',
                       'required_refs': ['references/concern-classification.md',
                                         'references/strategy-dimensions.md'],
                       'max_papers': 8,
                       'language_policy': 'user'},
 'research-organizer': {'label': '资料与证据分析', 'required_refs': [], 'max_papers': 8, 'language_policy': 'user'}}

NAME = re.compile(r'[a-z][a-z0-9-]{0,62}\Z')
REFERENCE = re.compile(r'references/[A-Za-z0-9_.-]+\.md')
RESERVED = {'con','prn','aux','nul',*[f'{prefix}{number}' for prefix in ('com','lpt') for number in range(1,10)]}
DASHBOARD_USAGE = 'skills:dashboard-usage'
MAIN_FILES = ('SKILL.md','SKILL.disabled.md')


def validate_name(name):
    if not isinstance(name,str) or not NAME.fullmatch(name) or name in RESERVED:
        raise ValueError('技能ID应为1–63位小写字母、数字或短横线，且不能使用系统保留名称。')
    return name


def safe_path(relative):
    """Only real workspace paths: no directory junction or symlink traversal."""
    root=w.ROOT.resolve();candidate=root/relative
    try:
        relative_path=candidate.relative_to(root)
    except ValueError as error:
        raise ValueError('技能文件路径无效。') from error
    if any(part in ('.','..') for part in relative_path.parts):raise ValueError('技能文件路径无效。')
    current=root
    for part in relative_path.parts:
        current=current/part
        if current.is_symlink() or current.exists() and getattr(current.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('技能文件不能经目录链接访问。')
    if not candidate.resolve().is_relative_to(root):raise ValueError('技能文件不能超出当前工作区。')
    return candidate


def main_paths(name):
    folder=Path('.agents/skills')/validate_name(name)
    return tuple(safe_path(folder/file) for file in MAIN_FILES)


def path_for(name,relative='SKILL.md'):
    if relative=='SKILL.md':
        active,disabled=main_paths(name)
        if disabled.exists():
            if active.exists():raise ValueError('同一个技能存在两个主文件，请核对原稿。')
            return disabled
        return active
    if not isinstance(relative,str) or not REFERENCE.fullmatch(relative):
        raise ValueError('只允许技能主文或已声明的Markdown参考。')
    return safe_path(Path('.agents/skills')/validate_name(name)/relative)


def local_names():
    root=safe_path('.agents/skills')
    return {path.parent.name for file in MAIN_FILES for path in root.glob('*/'+file)} if root.is_dir() else set()


def dashboard_usage():
    from research_store import Store
    return Store().cursor(DASHBOARD_USAGE,{})


def frontmatter(text, *, strict=False):
    match=re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)',text,re.S)
    if not match:
        if strict:raise ValueError('技能需要含name和description的YAML开头。')
        return {}
    try:meta=yaml.safe_load(match[1])
    except yaml.YAMLError as error:raise ValueError('技能开头的YAML格式无效。') from error
    if not isinstance(meta,dict):raise ValueError('技能开头必须是字段对象。')
    return meta


def metadata(name, *, main=None, include_disabled=False, usage=None):
    validate_name(name)
    if main is None:
        path=path_for(name)
        main=path.read_text('utf-8-sig') if path.is_file() else ''
    meta=frontmatter(main)
    row=dict(SKILLS.get(name,{}))
    registration=meta.get('workbench')
    if registration is not None and not isinstance(registration,dict):raise ValueError('workbench需要字段对象。')
    if registration is not None:
        unknown=set(registration)-{'enabled','label','max_papers','language_policy','required_refs'}
        if unknown:raise ValueError('workbench包含不支持的登记字段。')
        if 'enabled' in registration and not isinstance(registration['enabled'],bool):raise ValueError('技能enabled必须为布尔值。')
        row.update(registration)
    if not row:return None
    usage=dashboard_usage() if usage is None else usage
    enabled=usage.get(name,row.get('enabled',True))
    if not enabled and not include_disabled:return None
    row.setdefault('label',meta.get('name') or name)
    row.setdefault('max_papers',8);row.setdefault('language_policy','user');row.setdefault('required_refs',[])
    if not isinstance(row['label'],str) or not 1<=len(row['label'].strip())<=120:raise ValueError('技能显示名称需要1–120字。')
    if isinstance(row['max_papers'],bool) or not isinstance(row['max_papers'],int) or not 1<=row['max_papers']<=8:
        raise ValueError('一次分析只支持1–8篇论文。')
    if row['language_policy'] not in ('user','target'):raise ValueError('技能语言约定只能为user或target。')
    refs=row['required_refs']
    if not isinstance(refs,list) or any(not isinstance(ref,str) or not REFERENCE.fullmatch(ref) for ref in refs):
        raise ValueError('必需参考只能使用当前技能references目录的Markdown文件。')
    return {**row,'enabled':enabled,'description':str(meta.get('description') or ''),'builtin':name in SKILLS}


def registered():
    result={}
    candidates=set(SKILLS)|local_names()
    usage=dashboard_usage()
    for name in sorted(candidates):
        try:row=metadata(name,usage=usage)
        except (ValueError,OSError):continue
        if row is not None:result[name]=row
    return result


def limit(name):return required(name)['max_papers']


def label(name):return required(name)['label']


def required(name, *, main=None, include_disabled=False):
    row=metadata(name,main=main,include_disabled=include_disabled)
    if row is None:raise ValueError('此技能在看板内未启用或未登记。')
    return row


def menu():return [{'id':name,'label':row['label'],'max_papers':row['max_papers']} for name,row in registered().items()]

REVIEW_ACTION = (
    r'(?:审稿(?!人|意见|语气|风格|流程|机制|规则|工具|标准)'
    r'|投稿前(?:的)?(?:审稿)?(?:检查|核查|审查)'
    r'|(?:检查|核查|审查)(?:一下)?(?:这篇|这份|我的|当前)?(?:论文|稿件|初稿|手稿))'
)


def review_requested(instruction):
    modifiers=r'(?:(?:先|再|认真|仔细|严格|全面|系统地?|分别)\s*)*'
    subject=r'(?:对[^，,。；;\n]{1,120}?\s*)?'
    action=r'(?:(?:做|进行|开展)(?:一次)?\s*)?'+REVIEW_ACTION
    if re.search(r'(?:请|帮我|替我|麻烦你)\s*'+modifiers+subject+action,instruction):return True
    if re.search(r'(?:^|[.!?\n])\s*(?:please\s+|(?:can|could)\s+you\s+)?(?:review|audit|proofread|check)\s+(?:this|my|the)\s+(?:paper|manuscript|draft)\b',instruction,re.I):return True
    # Bare task names also describe procedures; questions about them stay discussion.
    if re.search(r'哪些|什么|如何|怎么|包括|步骤|流程|语气|风格',instruction):return False
    return bool(re.search(r'(?:^|[。！？!?，,；;\n])\s*'+modifiers+subject+action,instruction))


ROUTES = [('回复.*审稿|回应.*审稿|rebuttal|response to reviewers', 'rebuttal-guidance'), ('润色|翻译', 'paper-polish'), ('引言|introduction', 'intro-drafter'), ('图表|画图|图设计', 'figure-designer'), (REVIEW_ACTION, 'pre-submission-reviewer'), ('综述|文献分析|领域现状', 'deep-research'), ('benchmark|评测', 'benchmark-paper-template'), ('论文结构|逻辑链|研究结构', 'tech-paper-template'), ('写正文|(?:写|起草|撰写).*(?:论文|摘要)', 'paper-writer'), ('评估.*想法|想法.*可行|方向.*评估|评估.*方向|评价.*想法|novelty|feasibility', 'idea-evaluator')]

def select(selected,instruction):
    if selected!='auto':
        required(selected)
        return selected
    # A declined task is not a request, even when it names a registered skill.
    instruction=re.sub(r'(?:不要|不用|无需|不必|不需要|暂不|(?:^|[，,。；;\n])\s*(?:(?:请|麻烦你|先|暂时|这次|本次)\s*)*别)[^，,。；;\n]*','',instruction)
    for pattern,name in ROUTES:
        matched=review_requested(instruction) if name=='pre-submission-reviewer' else re.search(pattern,instruction,re.I)
        if matched and metadata(name) is not None:return name
    return None

def read(name,references=(), *, overrides=None, include_disabled=False):
    if name is None:return ''
    overrides=overrides or {}
    try:main=overrides['SKILL.md'] if 'SKILL.md' in overrides else path_for(name).read_text('utf-8-sig')
    except OSError as error:raise ValueError('技能主文缺失或不可读。') from error
    row=required(name,main=main,include_disabled=include_disabled)
    allowed=set(REFERENCE.findall(main))
    if not isinstance(references,(list,tuple)) or len(references)>2 or any(not isinstance(r,str) or r not in allowed for r in references):
        raise ValueError('每次只能选择当前技能明确引用的 0–2 份参考资料。')
    if any(ref not in allowed for ref in row['required_refs']):raise ValueError('技能登记包含主文未声明的必需参考。')
    optional=0;text=main
    for relative in dict.fromkeys(row['required_refs']+list(references)):
        path=path_for(name,relative)
        if not path.is_file() and relative not in overrides:raise ValueError('技能必需参考缺失或路径无效：'+relative)
        content=overrides[relative] if relative in overrides else path.read_text('utf-8-sig')
        if relative not in row['required_refs']:optional+=len(content)
        text+='\n\n--- '+relative+' ---\n'+content
    if optional>12000 or len(text)>48000:raise ValueError('参考材料超过本任务预算，请缩小或拆分任务；未发送模型请求。')
    return text

def language(name,instruction):
    if re.search(r'英文|英语|\bEnglish\b',instruction,re.I):return '按用户要求输出英文正文；说明语言服从明确要求。'
    if re.search(r'中文|汉语|\bChinese\b',instruction,re.I):return '按用户要求输出中文。'
    return '正文语言依目标稿件、提供的原稿和技能约定；解释跟随用户语言。' if required(name)['language_policy']=='target' else '输出语言跟随用户明确要求，否则沿当前对话语言。'
