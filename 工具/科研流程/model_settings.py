"""DeepSeek selection and interactive thinking preferences, without credentials."""
import copy
import re
import workspace_runtime as w

DEFAULTS={'text_model':'deepseek-flash','image_model':'deepseek-flash','thinking':False,'effort':'high'}
FALLBACK=[{'id':'deepseek-flash','name':'DeepSeek Flash','input_modalities':['text','image'],'effort':{'supported_levels':['low','high','max']}},
          {'id':'deepseek-v4-pro','name':'DeepSeek V4 Pro','input_modalities':['text'],'effort':{'supported_levels':['low','high','max']}}]


def available():
    return w.read_json(w.DATA/'DeepSeek模型列表.json',{}).get('models') or FALLBACK


def store_catalog(data):
    rows=[]
    for row in data.get('data',[]):
        if not isinstance(row,dict) or not re.fullmatch(r'deepseek-[a-z0-9.-]{1,60}',str(row.get('id',''))):continue
        modalities=[s for s in row.get('input_modalities',['text']) if s in ('text','image')]
        levels=[s for s in row.get('effort',{}).get('supported_levels',['high']) if s in ('low','high','max')]
        rows.append({'id':row['id'],'name':str(row.get('name') or row['id'])[:100],'input_modalities':modalities,'effort':{'supported_levels':levels}})
    if not rows:raise ValueError('服务没有返回可用的 DeepSeek 模型。原配置保留。')
    result={'models':rows,'checked':w.now()};w.write_json(w.DATA/'DeepSeek模型列表.json',result);return result


def settings():
    return {**DEFAULTS,**w.read_json(w.DATA/'DeepSeek偏好.json',{})}


def save(values):
    current=settings();models={m['id']:m for m in available()}
    for key in ('text_model','image_model'):
        if key in values:
            value=values[key]
            if not isinstance(value,str) or value not in models:raise ValueError('请从可用 DeepSeek 模型中选择。')
            if key=='image_model' and 'image' not in models[value]['input_modalities']:raise ValueError('此模型不支持论文图片输入，请选择支持图片的模型。')
            current[key]=value
    if 'thinking' in values:
        if type(values['thinking']) is not bool:raise ValueError('思考开关无效。')
        current['thinking']=values['thinking']
    if 'effort' in values:
        if values['effort'] not in ('low','high','max'):raise ValueError('思考强度无效。')
        current['effort']=values['effort']
    if current['thinking'] and current['effort'] not in models.get(current['text_model'],{}).get('effort',{}).get('supported_levels',[]):raise ValueError('所选模型不支持该思考强度。')
    w.write_json(w.DATA/'DeepSeek偏好.json',current);return current


def decorate(payload):
    result=copy.deepcopy(payload)
    if result.get('_action'):return result
    current=settings()
    image=any(isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content'] if isinstance(p,dict)) for m in result.get('messages',[]))
    result['model']=current['image_model' if image else 'text_model']
    interactive=result.pop('_interactive',False)
    if interactive and current['thinking']:
        result['thinking']={'type':'enabled'};result['reasoning_effort']=current['effort'];result['max_tokens']=max(16000,result.get('max_tokens',4000))
    return result


def refresh_catalog():
    from model_gateway import call_deepseek
    response=call_deepseek({'_action':'list_models'})
    if response.get('error'):raise ValueError(response['error'])
    return store_catalog(response)
