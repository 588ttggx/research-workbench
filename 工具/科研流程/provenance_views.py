"""Six evidence views over recorded edges; stage order never invents an edge."""
ALIASES={'ExperimentIndex':'Experiment','SampleIndex':'Sample','BatchIndex':'Batch',
         'InstrumentIndex':'Instrument','CalibrationIndex':'Calibration','PipelineIndex':'Pipeline','ModelIndex':'Model'}
CHAINS=[
 ('logic','科研逻辑',[('文献',{'Paper'}),('研究缺口',{'Gap'}),('研究问题',{'Question'}),('假设',{'Hypothesis'}),('实验或分析',{'Experiment','RUN'}),('证据结果',{'Evidence','Result'}),('论断',{'Claim'})]),
 ('experiment','实验条件',[('原料与批次',{'Material','Batch'}),('样品',{'Sample'}),('处理',{'Treatment'}),('规程',{'SOP'}),('仪器',{'Instrument'}),('校准',{'Calibration'}),('实验',{'Experiment'})]),
 ('data','数据流转',[('实验',{'Experiment'}),('原始数据',{'RawData','Dataset'}),('质量检查',{'QC'}),('处理后数据',{'ProcessedData'}),('数据集',{'Dataset'}),('结果',{'Result'})]),
 ('computation','计算来源',[('输入数据',{'Dataset'}),('参数',{'Parameters'}),('代码',{'Code'}),('环境',{'Environment'}),('流程或运行',{'Pipeline','RUN'}),('模型（按需）',{'Model'}),('结果与图',{'Result','Figure'})]),
 ('decision','决策依据',[('证据',{'Evidence','Paper','Result'}),('决定',{'Decision'}),('实施变化',{'Change'}),('实际结果',{'Outcome','Result'}),('教训',{'Lesson'})]),
 ('experience','经验复用',[('失败',{'Failure'}),('解决方案',{'Solution'}),('教训',{'Lesson'}),('长期经验',{'Experience'}),('规程更新',{'SOP'}),('复用项目',{'Project'})]),
]


def views(nodes,relations):
    result=[]
    for key,label,stages in CHAINS:
        rows=[];selected=set()
        for title,types in stages:
            found=[n['id'] for n in nodes if ALIASES.get(n['kind'],n['kind']) in types]
            embedded=[]
            if types=={'Parameters'}:
                embedded=[n['id'] for n in nodes if n['kind']=='RUN' and isinstance(n['data'].get('parameters'),dict)]
            selected.update(found+embedded)
            rows.append({'label':title,'ids':found,'embedded_in':embedded,'optional':types in ({'Model'},{'Treatment'},{'ProcessedData'})})
        result.append({'id':key,'label':label,'stages':rows,'nodes':sorted(selected),
                       'relations':[e['id'] for e in relations if e['source'] in selected and e['target'] in selected],
                       'missing':[r['label'] for r in rows if not r['ids'] and not r['embedded_in'] and not r['optional']]})
    return result
