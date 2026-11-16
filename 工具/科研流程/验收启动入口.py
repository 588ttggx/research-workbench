"""用 Windows 注册表中的普通用户 PATH 验证双击入口，不继承 Codex 运行时。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import winreg
import requests
import workflow as w

parts=[]
for hive,key in [(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),(winreg.HKEY_CURRENT_USER,'Environment')]:
    with winreg.OpenKey(hive,key) as handle:
        parts.append(winreg.QueryValueEx(handle,'Path')[0])
environment=os.environ.copy()
environment['PATH']=os.path.expandvars(';'.join(parts))
commands=['打开科研区.cmd']
if '--all' in sys.argv:
    commands.extend(['备份科研区.cmd','检查科研区更新.cmd'])
results=[]
for name in commands:
    command='"'+str(Path(environment['SYSTEMROOT'])/'System32/cmd.exe')+'" /d /s /c ""'+str(w.ROOT/name)+'" <nul"'
    # Windows PowerShell 5 background children can retain pipe handles after cmd exits.
    # Wait for cmd itself, storing output in files instead of waiting for inherited pipe EOF.
    stdout_path=w.ROOT/'工具/日志'/('启动入口-'+name+'.stdout.log')
    stderr_path=w.ROOT/'工具/日志'/('启动入口-'+name+'.stderr.log')
    with stdout_path.open('wb') as stdout_log,stderr_path.open('wb') as stderr_log:
        process=subprocess.run(command,cwd=w.ROOT/'_临时/科研区维护',env=environment,stdout=stdout_log,stderr=stderr_log,timeout=180)
    output=stdout_path.read_text('utf-8',errors='replace')
    error=stderr_path.read_text('utf-8',errors='replace')
    if process.returncode or 'not recognized' in output.lower() or 'not recognized' in error.lower():
        raise RuntimeError(name+' 失败：\n'+output+error)
    if name=='打开科研区.cmd' and 'Research dashboard is ready:' not in output:
        raise RuntimeError('启动没有达到就绪状态：\n'+output+error)
    if name=='备份科研区.cmd':
        receipts=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
        assert receipts and receipts[-1].get('verification',{}).get('verified'),output+error
    if name=='检查科研区更新.cmd' and 'Component' not in output:
        raise RuntimeError('更新入口未完成：'+output+error)
    results.append({'entry':name,'exit_code':process.returncode})
status=requests.get('http://127.0.0.1:8503/api/status',timeout=20).json()
assert all(status['services'].values()),status['services']
result={'time':w.now(),'environment':'Windows 注册表用户/系统 PATH，未加入 Codex 运行时','entries':results,'services':status['services'],'papers':len(status['papers'])}
w.write_json(w.ROOT/'工具/日志/启动入口验收.json',result)
print(json.dumps(result,ensure_ascii=False))
