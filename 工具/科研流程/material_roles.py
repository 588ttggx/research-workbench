"""Content identity and knowledge admission, independent of archive/membership."""
from pathlib import PurePosixPath

RULES_VERSION='knowledge-admission-v6'
ROLES={'knowledge','project_process','project_reference','system_record','unclassified'}
PROCESS_TYPES={'Stage','Project','DailyLog','Meeting','Decision','Issue','Failure','Solution','Review','Closure','Task','Milestone','Risk','ExperimentPlan','StatisticalPlan','ExperimentIndex','SampleIndex','InstrumentIndex','CalibrationIndex','Result','Figure','QC','ModelIndex','PipelineIndex','NextExperiment','Report'}
KNOWLEDGE_TYPES={'note','personal_note','method_note','ai_paper_note','reading_card','evidence_note','literature_note','learning_note'}
KNOWLEDGE_RECORD_TYPES={'PaperNote','Idea','Gap','Question','Hypothesis','Lesson','Experience','SOP','Method','Claim','Concept'}
SYSTEM_TYPES={'workspace_index','maintenance_record','workspace_review'}
PROCESS_CATEGORIES={'ai_analysis','ai_administrator_chat','weekly_brief','data_analysis','report','ai_reading_record','writing_revision_record','task'}
# Older API snapshots may only carry a display kind, without source metadata.
PROCESS_KINDS={'项目过程','项目记录','阅读记录','AI 阅读记录','讨论笔记','报告','分析报告','分析记录','历史讨论',
               '研究日志','会议','决策日志','项目复盘','项目关闭','任务','里程碑','风险','实验设计','统计计划',
               '实验索引','样品索引','仪器索引','校准索引','结果','图与谱系','质量控制','模型索引','流程索引','下一步实验'}


def restricted_role(meta,relative='',visibility='active'):
    """Structural records and references cannot be relabelled as knowledge."""
    relative=(relative or '').replace('\\','/');parts=PurePosixPath(relative).parts
    kb_relative=relative.removeprefix('科研知识库/')
    kb_parts=PurePosixPath(kb_relative).parts
    category=meta.get('type');record_type=meta.get('record_type');kind=meta.get('kind');note_category=meta.get('note_category')
    if (any(p in {'修改前','修改后','编辑备份','正文历史','备份','_临时'} for p in parts)
            or visibility=='system' or meta.get('content_role')=='system_record' or category in SYSTEM_TYPES
            or kind in {'维护资料','维护记录','系统记录'} or note_category in {'维护资料','维护记录','系统记录'}):
        return 'system_record'
    project_background=len(kb_parts)==3 and kb_parts[0]=='项目' and kb_parts[2]=='方向背景.md'
    if (kb_relative.startswith('背景/') or project_background or category in {'field_background','reference_note'}
            or kind in {'背景','共享背景','项目背景','参考资料'} or note_category in {'背景','共享背景','项目背景','参考资料'}):
        return 'project_reference'
    if (record_type in PROCESS_TYPES or category in PROCESS_TYPES or category in PROCESS_CATEGORIES
            or meta.get('question_id') or PurePosixPath(relative).name in {'当前课题状态.md','任务.md','研究主线.md','方向选择.md'}
            or note_category in PROCESS_KINDS or kind in PROCESS_KINDS
            or (kb_relative.startswith('文献/AI阅读记录/') and category!='ai_paper_note' and kind not in {'阅读笔记','AI 阅读笔记'})
            or kb_relative.startswith('笔记/共享/每周研究简报/') or relative.startswith(('output/','research/'))):
        return 'project_process'
    if record_type and record_type not in KNOWLEDGE_RECORD_TYPES:
        return 'project_reference'
    if category and category not in KNOWLEDGE_TYPES and not (category=='research_record' and record_type in KNOWLEDGE_RECORD_TYPES):
        return 'unclassified'
    return None


def interpret(meta,relative,visibility='active'):
    explicit=meta.get('content_role')
    role=restricted_role(meta,relative,visibility) or (explicit if explicit in ROLES else 'knowledge')
    published=meta.get('global_knowledge',role=='knowledge')
    return {'content_role':role,'global_knowledge':bool(published) if role=='knowledge' else False,
            'knowledge_sources':meta.get('knowledge_sources',[]) if isinstance(meta.get('knowledge_sources',[]),list) else [],
            'stage_removed':bool(meta.get('stage_removed')),'record_type':meta.get('record_type')}


def knowledge(document,*,global_scope=False,history=False):
    return (document.get('content_role')=='knowledge'
            and restricted_role(document,document.get('path') or document.get('kb_path',''),document.get('visibility','active')) is None
            and (not global_scope or document.get('global_knowledge',True))
            and document.get('visibility')!='system' and (history or not document.get('archived')))
