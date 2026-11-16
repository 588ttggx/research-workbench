"""Inspect one authorized note response without saving notes or logging input/key/content."""
import json
from unittest.mock import patch
import dashboard as dashboard
import paper_notes
import workflow as w

original=dashboard.call_deepseek
result={'time':w.now(),'scope':'已有资料的一批笔记，最多三篇；无正文写入、无密钥或内容日志'}
def inspect(payload):
    response=original(payload);answer=response.get('answer')
    result.update(finish_reason=response.get('finish_reason'),characters=len(answer) if isinstance(answer,str) else 0,error=response.get('error'),usage=response.get('usage'))
    try:json.loads(answer);result['valid_json']=True
    except (ValueError,TypeError) as error:
        result.update(valid_json=False,parse_error=str(error),fenced=isinstance(answer,str) and answer.strip().startswith('```'))
        if isinstance(error,json.JSONDecodeError):result.update(invalid_character=answer[error.pos:error.pos+1],previous_character=answer[:error.pos].rstrip()[-1:])
    raise ValueError('诊断结束，未写入笔记。')
with patch.object(dashboard,'call_deepseek',inspect):
    try:paper_notes.generate({'project':'山药'})
    except ValueError:pass
w.write_json(w.ROOT/'output/科研工作区体验诊断/管理员模型返回核查.json',result)
print(json.dumps(result,ensure_ascii=True))
