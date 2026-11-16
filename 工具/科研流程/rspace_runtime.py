"""Lifecycle of the explicitly provisioned local RSpace, not arbitrary hosts."""
import json
import subprocess
import time
from pathlib import Path
import requests
import win32crypt
from filelock import FileLock
import workflow as w


def deployment():
    value=w.read_json(w.DATA/'RSpace部署.json',{})
    return {key:value.get(key) for key in ('installed','version','url','runtime','war_sha256','scientific_acceptance')}


def account():
    path=w.DATA/'rspace-bootstrap.dpapi'
    if not deployment().get('installed') or not path.is_file():raise ValueError('本机实例尚未建立日常账号')
    value=json.loads(win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1])
    return {'username':value['user_username'],'initial_password':value['user_password'],
            'url':deployment()['url'],'scope':'本机初始化的日常账号；若已在 RSpace 改过密码，请使用原平台的新密码。管理员账号独立保管，不用于科研记录。'}


def start():
    value=deployment()
    if not value.get('installed'):return {'status':'not_deployed'}
    with FileLock(str(w.DATA/'rspace-runtime.lock'),timeout=30):
        import professional_tools as p
        old=w.read_json(w.DATA/'rspace-process.json',{})
        try:
            if requests.get(value['url'].rstrip('/')+'/login',timeout=3).ok:
                return {'status':'running','url':value['url'],'message':'本机 RSpace 已响应；科研验证范围沿原记录。'}
        except requests.RequestException:
            pass
        if old.get('owner')=='service-manager' and old.get('stamp') and p._process_stamp(old['pid'])==old['stamp']:
            return {'status':'starting','url':value['url'],'message':'RSpace 由统一启动管理器接续；尚未响应时请查看原生启动记录。'}
        if not old.get('stamp') or p._process_stamp(old['pid'])!=old['stamp']:
            # A live WSL invocation keeps systemd services from being suspended
            # when its last interactive shell exits. Dashboard owns this helper.
            with (w.DATA/'rspace-runtime.log').open('ab') as log:
                process=subprocess.Popen(['wsl.exe','-d','Ubuntu-24.04','--exec','sleep','2147483647'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                                         creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)
            w.write_json(w.DATA/'rspace-process.json',{'pid':process.pid,'stamp':p._process_stamp(process.pid),'started':w.now()})
        runtime=Path(value['runtime']).resolve()
        allowed=(w.ROOT/'runtime/RSpace').resolve()
        if not runtime.is_relative_to(allowed) or not (runtime/'compose.yaml').is_file():raise ValueError('已登记 RSpace 配置位置不符，未启动其他程序')
        linux='/mnt/'+runtime.drive[0].lower()+'/'+runtime.relative_to(runtime.anchor).as_posix()
        ready=False
        for attempt in range(15):
            try:
                probe=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','-u','root','--exec','docker','info','--format','{{.ServerVersion}}'],
                                     capture_output=True,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
                if probe.returncode==0:
                    ready=True
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(1)
        if not ready:raise ValueError('RSpace 等待 WSL/Docker 就绪超时（阶段：container-runtime）；原数据卷保留。')
        result=subprocess.run(['wsl.exe','-d','Ubuntu-24.04','-u','root','--exec','docker','compose','-p','yanxu-rspace','-f',linux+'/compose.yaml','up','-d'],
                              capture_output=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('RSpace 容器启动未完成（阶段：compose，退出码 '+str(result.returncode)+'）；原数据卷保留。')
        return {'status':'starting','url':value['url'],'message':'原生服务启动中，首次打开可能需要等待数据库检查完成。'}


def autostart():
    import threading
    if deployment().get('installed'):
        def run():
            try:w.write_json(w.DATA/'rspace-startup.json',{**start(),'time':w.now()})
            except Exception as exc:w.write_json(w.DATA/'rspace-startup.json',{'status':'failed','message':str(exc),'time':w.now()})
        threading.Thread(target=run,daemon=True,name='rspace-startup').start()
