"""Reproducible local CSV calculations; Plotly renders the resulting scientific plots."""
import csv
import html
import io
import json
import re
from contextlib import contextmanager
from pathlib import Path
import numpy as np
import knowledge as k
import workflow as w

KINDS = {'line':'光谱与曲线', 'scatter':'散点图', 'pca':'PCA 得分图', 'regression':'线性拟合', 'heatmap':'相关性热图','classification':'按独立样品验证分类','thz':'THz 配对波形与质量检查'}


def columns(text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>4*1024*1024:raise ValueError('CSV 最多 4 MB')
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    if not 3<=len(rows)<=10001 or not 2<=len(rows[0])<=100 or len(set(rows[0]))!=len(rows[0]) or any(len(row)!=len(rows[0]) for row in rows):raise ValueError('请提供列名唯一、列数一致且至少两行数据的 CSV')
    numeric=[]
    for index,name in enumerate(rows[0]):
        try:
            if np.isfinite(np.asarray([float(row[index]) for row in rows[1:]])).all():numeric.append(name)
        except (ValueError,TypeError):pass
    return {'columns':rows[0],'numeric':numeric,'rows':len(rows)-1}


def _classification(rows,options):
    headers=rows[0]
    if len(set(headers))!=len(headers):raise ValueError('列名重复，请先核对 CSV')
    label=options.get('label_column');sample=options.get('sample_column');batch=options.get('batch_column');features=options.get('feature_columns');split=options.get('split_by','sample')
    if label not in headers or sample not in headers or label==sample:raise ValueError('请明确选择不同的类别和独立样品 ID 列')
    if split=='batch' and batch not in headers:raise ValueError('按批次划分必须选择材料批次列')
    if not isinstance(features,list) or not features or len(set(features))!=len(features) or any(f not in headers or f in (label,sample,batch) for f in features):raise ValueError('请选择真实数值特征，身份、批次和类别列不能作为预测特征')
    if (len(rows)-1)*len(features)>200000:raise ValueError('本轮模型验证最多 20 万个特征值，请按研究问题分批')
    try:matrix=np.asarray([[float(row[headers.index(f)]) for f in features] for row in rows[1:]],dtype=float)
    except (ValueError,TypeError):raise ValueError('所选特征需为完整数值，不能含空值') from None
    from scientific_validation import classify
    metrics=classify(matrix,[r[headers.index(label)] for r in rows[1:]],[r[headers.index(sample)] for r in rows[1:]],
                     batch_ids=[r[headers.index(batch)] for r in rows[1:]] if batch in headers else None,split_by=split,seed=options.get('seed',42),resamples=options.get('bootstrap_resamples',2000))
    metrics.update(rows=len(rows)-1,feature_columns=features,sample_column=sample,label_column=label,batch_column=batch,model='scikit-learn LogisticRegression + StandardScaler inside training folds',baseline='DummyClassifier most_frequent')
    clean=lambda value:html.escape(str(value)[:180]);labels=[clean(c) for c in metrics['classes']]
    figure={'data':[{'type':'heatmap','z':metrics['confusion_matrix'],'x':labels,'y':labels,'zmin':0,'colorscale':'Blues','colorbar':{'title':{'text':'Independent samples'}}}],
            'layout':{'title':{'text':clean(options.get('title') or 'Grouped hold-out · independent samples')},'xaxis':{'title':{'text':clean(options.get('xlabel') or 'Predicted class')}},'yaxis':{'title':{'text':clean(options.get('ylabel') or 'Observed class')}}}}
    return {'kind':'classification','figure':figure,'metrics':metrics}


def compute(text, kind, options=None):
    options = options or {}
    if kind not in KINDS or not isinstance(text, str) or len(text.encode('utf-8')) > 4*1024*1024:
        raise ValueError('请选择支持的分析类型，CSV 最多 4 MB。')
    rows = list(csv.reader(io.StringIO(text.lstrip('\ufeff'))))
    if not 3 <= len(rows) <= 10001 or not 2 <= len(rows[0]) <= 100 or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError('CSV 需有标题行、2–100 列、2–10000 行数据，且每行列数相同。')
    if kind=='classification':return _classification(rows,options)
    if kind=='thz':return __import__('thz_domain').compute(text,options)
    headers = [html.escape(str(s)[:120]) for s in rows[0]]
    numeric = []
    for column in range(len(headers)):
        try: values = np.asarray([float(row[column]) for row in rows[1:]], dtype=float)
        except ValueError:
            if any(row[column].strip().lower() in ('nan','inf','-inf','infinity','') for row in rows[1:]):
                raise ValueError('包含空值或非有限值，请先核对数据。') from None
            continue
        if not np.isfinite(values).all(): raise ValueError('数据包含 NaN 或无穷值，请先核对。')
        numeric.append((column, values))
    if len(numeric) < 2: raise ValueError('至少需要两个完整数值列；文字列仅用作样本标签。')
    matrix = np.column_stack([values for _, values in numeric])
    if matrix.size > 300000: raise ValueError('单次分析最多 30 万个数值，请按实验批次分开。')
    names = [headers[column] for column, _ in numeric]
    labels = [str(row[0])[:120] for row in rows[1:]] if numeric[0][0] != 0 else [str(i+1) for i in range(len(matrix))]
    metrics = {'rows':len(matrix), 'numeric_columns':names}; traces = []
    xname, yname = names[:2]
    if kind == 'line':
        for index, name in enumerate(names[1:]): traces.append({'type':'scatter','mode':'lines','name':name,'x':matrix[:,0].tolist(),'y':matrix[:,index+1].tolist()})
        yname = '测量值（单位请填写）'
    elif kind in ('scatter','regression'):
        x, y = matrix[:,:2].T
        traces = [{'type':'scatter','mode':'markers','x':x.tolist(),'y':y.tolist(),'text':labels,'name':'输入数据'}]
        if kind == 'regression':
            if np.ptp(x) == 0 or np.ptp(y) == 0: raise ValueError('线性拟合需要变化的 X 与 Y。')
            slope, intercept = np.linalg.lstsq(np.column_stack([x,np.ones_like(x)]), y, rcond=None)[0]
            predicted = slope*x+intercept
            metrics.update(slope=float(slope), intercept=float(intercept), r2_fit=float(1-np.sum((y-predicted)**2)/np.sum((y-y.mean())**2)), rmse_fit=float(np.sqrt(np.mean((y-predicted)**2))))
            endpoints=[float(x.min()),float(x.max())]
            traces.append({'type':'scatter','mode':'lines','name':'同一批数据的拟合','x':endpoints,'y':[float(slope*value+intercept) for value in endpoints]})
    elif kind == 'pca':
        if len(matrix) < 3: raise ValueError('PCA 至少需要 3 个样本。')
        deviations = matrix.std(axis=0, ddof=1); variable = deviations > 0
        if sum(variable) < 2: raise ValueError('PCA 至少需要两个有变化的数值特征。')
        centered = matrix[:,variable]-matrix[:,variable].mean(axis=0)
        if options.get('standardize', True): centered /= deviations[variable]
        u, singular, _ = np.linalg.svd(centered, full_matrices=False)
        scores = u[:,:2]*singular[:2]; ratio = singular**2/np.sum(singular**2)
        metrics.update(explained_variance=ratio[:2].tolist(), standardized=bool(options.get('standardize',True)), excluded_constant_columns=[name for name, used in zip(names,variable) if not used])
        traces = [{'type':'scatter','mode':'markers','x':scores[:,0].tolist(),'y':scores[:,1].tolist(),'text':labels,'name':'样本'}]
        xname, yname = f'PC1 ({ratio[0]:.1%})', f'PC2 ({ratio[1]:.1%})'
    else:
        variable=matrix.std(axis=0)>0
        if sum(variable)<2: raise ValueError('相关性需要两个有变化的数值列。')
        selected=[name for name,used in zip(names,variable) if used]
        traces=[{'type':'heatmap','z':np.corrcoef(matrix[:,variable],rowvar=False).tolist(),'x':selected,'y':selected,'zmin':-1,'zmax':1,'colorscale':'RdBu','reversescale':True,'colorbar':{'title':{'text':'Pearson r'}}}]
        xname = yname = '特征'
    clean = lambda value: html.escape(str(value)[:180])
    layout={'title':{'text':clean(options.get('title') or KINDS[kind])},'xaxis':{'title':{'text':clean(options.get('xlabel') or xname)}},'yaxis':{'title':{'text':clean(options.get('ylabel') or yname)}},'font':{'family':'Arial, Microsoft YaHei','size':14},'paper_bgcolor':'#ffffff','plot_bgcolor':'#ffffff','margin':{'l':80,'r':40,'t':70,'b':80},'height':520}
    return {'kind':kind,'figure':{'data':traces,'layout':layout},'metrics':metrics}


def save(data):
    return _save(data)


@contextmanager
def _project_write(project, revision=None):
    import project_profiles as profiles
    with profiles.lifecycle_lock(project):
        current=profiles.get(project)
        if current['archived']:raise ValueError('项目已归档，请恢复后新增或修订分析。')
        if revision is not None and revision!=current['lifecycle_revision']:raise ValueError('项目状态已变化，请重新打开分析。')
        yield current['lifecycle_revision']


def _save(data,inherited_method=None):
    project=data.get('project') or '山药'
    with _project_write(project,data.get('lifecycle_revision')) as revision:pass
    k.lines(project)
    text=data.get('csv'); kind=data.get('kind'); options=data.get('options') or {}
    if not isinstance(options,dict): raise ValueError('绘图参数无效。')
    if kind=='thz':
        if inherited_method is None:
            method=__import__('method_registry').approved(options.get('method_id'),options.get('method_fingerprint'))
            options={**options,'method_snapshot':method['policy']}
    result=compute(text,kind,options)
    with _project_write(project,revision),k.editing():
        return _commit(data,result,options,inherited_method,method if kind=='thz' and inherited_method is None else None)


def _commit(data,result,options,inherited_method,method):
    project=data.get('project') or '山药';text=data.get('csv');kind=data.get('kind')
    import inspect
    method_revision=w.digest(inspect.getsource(compute)+inspect.getsource(_classification)+(w.HERE/'scientific_validation.py').read_text('utf-8')+np.__version__+(w.HERE/'scientific_figures.py').read_text('utf-8')+(w.HERE/'uv.lock').read_text('utf-8')+((w.HERE/'thz_domain.py').read_text('utf-8') if kind=='thz' else ''))
    identifier=w.digest(json.dumps([project,text,kind,options,method_revision],ensure_ascii=False,sort_keys=True))[:24]
    previous=w.read_json(w.DATA/'数据分析'/(identifier+'.json'),{})
    if previous and previous.get('provenance'):return previous
    import dataset_store
    dataset=dataset_store.store_input(text,project,str(data.get('filename') or '输入数据.csv')[:200])
    path=w.KB/'项目'/project/'数据分析'/('分析_'+identifier+'.md')
    result.update(id=identifier,project=project,filename=str(data.get('filename') or '输入数据.csv')[:200],created=w.now(),path=path.relative_to(w.KB).as_posix(),source=dataset['uri'],source_root='workspace',source_sha256=w.digest(text),dataset=dataset,options=options,method_revision=method_revision)
    if kind=='thz':result['method_document']=inherited_method or {'id':method['id'],'title':method['data']['title'],'uri':method['uri'],'fingerprint':method['fingerprint'],'text':k.path_for(method['uri']).read_text('utf-8-sig')}
    explanation='身份与类别由所选列提供；重复扫描按独立样品归组，训练折内拟合标准化并调参，留出结果按独立样品计分。' if kind=='classification' else '曲线每行一个坐标点，以首个数值列为 X，其余列为 Y；PCA 每行一个观测，独立性需按实验设计核对；拟合使用前两个数值列。'
    summary_metrics={key:value for key,value in result['metrics'].items() if key not in ('train_rows','test_rows','train_groups','test_groups','test_samples','test_predictions','test_truth','cv_folds','tuning')} if kind=='classification' else result['metrics']
    if kind=='thz':
        explanation='按已核对方法的物理条件处理配对波形；保留样品相对参考的真实时延，可信频段、相位分支、厚度和所有阈值均记录于 RUN。'
        summary_metrics={key:value for key,value in result['metrics'].items() if key not in ('frequency_thz','refractive_index','absorption_cm_inverse','transmission_field_magnitude','phase_radians')}
    details='\n\n[查看运行、完整数据划分与调参记录](http://127.0.0.1:8503/#run?id='+identifier+')' if kind=='classification' else ''
    body=k.properties('',{'type':'data_analysis','project':project,'title':KINDS[kind]+' · '+result['filename'],'status':'本地计算结果'})+'# '+KINDS[kind]+' · '+result['filename']+'\n\n来源：'+result['source']+'\n\n原始文本 SHA256：'+result['source_sha256']+'\n\n## 分析参数\n\n'+explanation+'\n\n'+json.dumps(options,ensure_ascii=False)+'\n\n## 计算摘要\n\n'+json.dumps(summary_metrics,ensure_ascii=False,indent=2)+details+'\n\n同一批数据的拟合指标不能代替独立验证；PCA 与相关性不证明因果或分类有效性。数据与计算在本机完成，没有发送给 AI。\n'
    # An interrupted registration may already have a user-edited analysis note.
    # Resume the machine ledger without replacing that Markdown original.
    if not path.exists():w.atomic_text(path,body)
    import analysis_runs
    result['provenance']=analysis_runs.register(result,options)
    w.write_json(w.DATA/'数据分析'/(identifier+'.json'),result)
    return result


def view(identifier):
    if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{24}',identifier): raise ValueError('分析记录不存在。')
    result=w.read_json(w.DATA/'数据分析'/(identifier+'.json'),{})
    if not result: raise ValueError('分析记录不存在。')
    from dataset_store import source_file
    try:
        source=source_file(result)
        locations={'input_available':True,'input_location':str(source)}
    except (ValueError,OSError,KeyError):
        locations={'input_available':False,'input_location':result.get('source') or '未登记'}
    try:locations['note_location']=str(k.path_for(result['path']))
    except (ValueError,OSError,KeyError):locations['note_location']=None
    return {**result,**locations}


def input_file(identifier):
    from dataset_store import source_file
    return source_file(view(identifier))


def history(project):
    k.lines(project)
    entries=[w.read_json(path,{}) for path in (w.DATA/'数据分析').glob('*.json')]
    grouped={}
    for item in sorted(entries,key=lambda item:item.get('created',''),reverse=True):
        if item.get('project')!=project:continue
        identity=(item.get('dataset',{}).get('id') or item.get('source_sha256') or item['id'],item['kind'])
        if identity in grouped:
            grouped[identity]['previous'].append({key:item[key] for key in ('id','created','filename')})
            grouped[identity]['versions']+=1
        else:grouped[identity]={**{key:item[key] for key in ('id','filename','kind','created','path')},'versions':1,'previous':[]}
    return list(grouped.values())[:20]


def revise(data):
    old=view(data.get('id'))
    if data.get('source_sha256')!=old['source_sha256']:raise ValueError('来源版本不一致，请重新打开分析记录')
    from dataset_store import source_file
    text=source_file(old).read_bytes().decode('utf-8')
    if old['kind']=='thz':
        from research_store import Store,encode
        import analysis_runs
        node=Store().node(old['provenance']['run_id']);options=data.get('options') or {}
        if not isinstance(options,dict) or encode(node['data']['parameters'])!=encode(old['options']):raise ValueError('原运行参数已变化，请核查保存来源')
        cosmetic={'title','xlabel','ylabel','thz_plot'}
        if any(key not in cosmetic and value!=old['options'].get(key) for key,value in options.items()):raise ValueError('图表修订沿用原方法；改变物理方法或实验条件请重新导入并核对')
        if analysis_runs.artifact(node['id'],'method.md').read_text('utf-8-sig')!=old['method_document']['text']:raise ValueError('原方法版本不一致')
        return _save({'project':old['project'],'kind':'thz','filename':old['filename'],'csv':text,'options':{**old['options'],**options},**({'lifecycle_revision':data['lifecycle_revision']} if 'lifecycle_revision' in data else {})},inherited_method=old['method_document'])
    return save({'project':old['project'],'kind':old['kind'],'filename':old['filename'],'csv':text,'options':data.get('options'),**({'lifecycle_revision':data['lifecycle_revision']} if 'lifecycle_revision' in data else {})})
