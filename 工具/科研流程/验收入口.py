"""Check actual one-click native entry points without exposing a debugging port."""
import json
import subprocess
import time
import requests
import workflow as w

headers={'Origin':'http://127.0.0.1:8503'}
config=w.read_json(w.ROOT/'工具/工具版本.json')
cli=(w.ROOT/config['obsidian']['executable']).with_suffix('.com')
for name in ['knowledge','history']:
    response=requests.post('http://127.0.0.1:8503/api/open-tool',headers=headers,json={'tool':name},timeout=10);response.raise_for_status()
    for _ in range(20):
        check=subprocess.run([str(cli),'vault=科研知识库','vault','info=name'],capture_output=True,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        if check.returncode==0:break
        time.sleep(1)
    if check.returncode:raise ValueError('知识库入口未完成')
    time.sleep(2)
check=subprocess.run([str(cli),'vault=科研知识库','eval',"code=app.workspace.getLeavesOfType('git-history-view').length"],capture_output=True,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
assert check.returncode==0 and check.stdout.strip().removeprefix('=>').strip()=='1',check.stdout
result={'time':w.now(),'knowledge':True,'history':True,'method':'原生 CLI，本轮未启用远程调试端口'}
w.write_json(w.ROOT/'工具/日志/科研入口验收.json',result)
print(json.dumps(result,ensure_ascii=True))
