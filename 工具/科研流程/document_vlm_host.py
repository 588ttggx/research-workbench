"""Linux process ownership for the optional, managed WSL document service.

The service manager owns the Windows relay and this Linux process group. A
receipt is a technical process handle, never another task or research ledger.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


def identity(pid, *, proc=Path('/proc')):
    try:
        directory=proc/str(int(pid))
        fields=(directory/'stat').read_text().rsplit(')',1)[1].split()
        command=(directory/'cmdline').read_bytes()
        if fields[0] == 'Z' or not command:return None
        return {'pid':int(pid),'pgid':int(fields[2]),'start_ticks':int(fields[19]),
                'command_sha256':hashlib.sha256(command).hexdigest(),
                'command':command.rstrip(b'\0').decode('utf-8','replace').split('\0')}
    except (OSError,ValueError,IndexError):return None


def matches(saved, *, proc=Path('/proc')):
    if not isinstance(saved,dict):return False
    current=identity(saved.get('pid',0),proc=proc)
    return bool(current and all(current.get(key)==saved.get(key)
                for key in ('pid','pgid','start_ticks','command_sha256')))


def read_receipt(path, nonce):
    value=json.loads(Path(path).read_text('utf-8'))
    if not nonce or value.get('nonce')!=nonce:raise ValueError('Document process receipt owner changed.')
    return value


def status(path, nonce):
    value=read_receipt(path,nonce)
    saved=value.get('server')
    return {'running':matches(saved),'listening':owns_listener(saved),'server':saved}


def owns_listener(saved, *, port=8118, proc=Path('/proc')):
    if not matches(saved,proc=proc):return False
    try:
        sockets=set()
        for line in (proc/'net/tcp').read_text().splitlines()[1:]:
            fields=line.split()
            if len(fields)>9 and fields[1]==f'0100007F:{port:04X}' and fields[3]=='0A':sockets.add(fields[9])
        return any(os.readlink(fd) in {'socket:['+inode+']' for inode in sockets}
                   for fd in (proc/str(saved['pid'])/'fd').iterdir())
    except (OSError,ValueError,KeyError):return False


def signal_group(pgid, action):
    os.killpg(pgid,action)


def stop(path, nonce):
    if not Path(path).exists():return False
    value=read_receipt(path,nonce); server=value.get('server')
    return _stop_owned(server)


def _stop_owned(server):
    if not matches(server):return False
    if server['pid']<=1 or server['pgid']!=server['pid']:
        raise ValueError('Document service does not own its process group.')
    signal_group(server['pgid'],signal.SIGTERM)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if not matches(server):return True
        time.sleep(.1)
    if matches(server):signal_group(server['pgid'],signal.SIGKILL)
    deadline=time.monotonic()+5
    while matches(server) and time.monotonic()<deadline:time.sleep(.1)
    if matches(server):raise RuntimeError('Owned document process did not exit.')
    return True


def supervise(script, receipt, nonce):
    script=Path(script).resolve(strict=True)
    receipt=Path(receipt)
    from runtime_logs import append_bytes
    logs=[receipt.parent/('document-parser.'+name+'.log') for name in ('stdout','stderr')]
    for path in logs:append_bytes(path,b'',log_root=receipt.parent)
    process=subprocess.Popen(['/bin/bash',str(script)],start_new_session=True,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    server=None
    failures=[]
    def drain(stream,path):
        try:
            while data:=stream.read1(16384):append_bytes(path,data,log_root=receipt.parent)
        except Exception as error:
            failures.append(type(error).__name__)
            if process.poll() is None:process.terminate()
        finally:stream.close()
    readers=[threading.Thread(target=drain,args=pair,daemon=True)
             for pair in zip((process.stdout,process.stderr),logs)]
    for reader in readers:reader.start()
    def interrupted(signum,frame):raise InterruptedError('Managed document host stopped.')
    for name in ('SIGTERM','SIGINT','SIGHUP'):
        if hasattr(signal,name):signal.signal(getattr(signal,name),interrupted)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and process.poll() is None:
            candidate=identity(process.pid)
            if candidate and 'vllm.entrypoints.openai.api_server' in candidate['command']:
                server=candidate;break
            time.sleep(.05)
        if server is None:raise RuntimeError('Document inference entrypoint did not start.')
        value={'nonce':nonce,'supervisor':identity(os.getpid()),'server':server}
        receipt.parent.mkdir(parents=True,exist_ok=True)
        temporary=receipt.with_suffix('.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temporary.replace(receipt)
        code=process.wait()
        for reader in readers:reader.join(timeout=3)
        if failures:raise RuntimeError('Bounded document log capture failed.')
        return code
    finally:
        if server is not None and matches(server):
            _stop_owned(server)
            process.wait(timeout=5)
        elif process.poll() is None:
            # Popen returned this exact child in this invocation, before exec.
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('action',choices=('supervise','status','stop'))
    cli.add_argument('--receipt',type=Path,required=True);cli.add_argument('--nonce',required=True)
    cli.add_argument('--script',type=Path)
    args=cli.parse_args()
    if args.action=='supervise':
        if not args.script:cli.error('--script is required')
        raise SystemExit(supervise(args.script,args.receipt,args.nonce))
    result=status(args.receipt,args.nonce) if args.action=='status' else {'stopped':stop(args.receipt,args.nonce)}
    print(json.dumps(result,ensure_ascii=False))
