"""End-to-end temporary note test. Does not edit any real research note."""
import json
from pathlib import Path
import uuid
import time
import workflow as w

token=uuid.uuid4().hex[:10]
notebook=w.notebooks()['山药课题']
note=w.api('POST','/notes',json={'title':'同步验收临时_'+token,'content':'初始测试内容','note_type':'human','notebook_id':notebook})
identifier=note['id']
path=w.KB/'笔记/OpenNotebook'/(identifier.replace(':','-')+'.md')
relative=str(path.relative_to(w.KB)).replace('\\','/')
results={}
try:
    w.sync()
    assert path.exists()
    results['new_note_export']=True
    path.write_text('# 临时测试\n\n本地修改 '+token,'utf-8')
    w.sync()
    assert w.api('GET','/notes/'+identifier)['content']==w.clean_markdown(path.read_text('utf-8'))
    results['local_to_remote']=True
    w.api('PUT','/notes/'+identifier,json={'content':'# 临时测试\n\n远端修改 '+token})
    w.sync()
    assert '远端修改' in path.read_text('utf-8')
    results['remote_to_local']=True
    path.write_text('# 临时测试\n\n本地同时修改 '+token,'utf-8')
    last_update=w.api('PUT','/notes/'+identifier,json={'content':'# 临时测试\n\n远端同时修改 '+token})
    w.sync()
    entry=w.load_state()['notes'][relative]
    conflict=w.KB/entry['conflict']
    assert '本地同时修改' in path.read_text('utf-8')
    assert '远端同时修改' in conflict.read_text('utf-8')
    assert '本地同时修改' in conflict.read_text('utf-8')
    results['conflict_preserves_both']=True
finally:
    # Wait for this fixture's async embedding jobs before deleting it.
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        command=last_update.get('command_id') if 'last_update' in locals() else note.get('command_id')
        if not command:
            break
        status=w.api('GET','/commands/jobs/'+command)['status']
        if status.lower() in ('completed','failed','error','cancelled'):
            break
        time.sleep(.5)
    else:
        raise RuntimeError('Fixture embedding still running; retaining note for safe cleanup')
    with w.process_lock() as acquired:
        if not acquired:
            raise RuntimeError('Cleanup waiting for another sync; retain temporary fixture')
        w.api('DELETE','/notes/'+identifier)
        state=w.load_state()
        state['events']=[e for e in state.get('events',[]) if identifier.replace(':','-') not in e.get('message','')]
        entry=state['notes'].pop(relative,{})
        if entry.get('conflict'):
            (w.KB/entry['conflict']).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        w.write_json(w.STATE,state)
w.write_json(w.ROOT/'工具/日志/科研同步验收.json',results)
print(json.dumps(results,ensure_ascii=True))
