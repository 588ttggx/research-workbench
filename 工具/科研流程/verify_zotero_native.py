"""Exercise the supported Zotero write API in an isolated temporary collection.

Uses the saved native authorization. A process lock prevents automatic indexing
of test objects; an independent ledger keeps them out of research records. Only
objects bearing this run's marker are removed, including on a failed test.
"""
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
from unittest.mock import patch
import requests
import workflow as w
from research_store import Store
import zotero_bridge as z


def verify():
    connection=z.status()
    if not connection.get('remembered'):raise ValueError('请先完成 Zotero 的“总是允许”授权')
    temporary=w.ROOT/'_临时/科研区维护';temporary.mkdir(parents=True,exist_ok=True)
    marker='isolated-software-validation:'+secrets.token_hex(12)
    collection=z.key_for(marker);created=[];writes=[];cleanup=[]
    server=z._server();native_create=z._create
    with w.process_lock() as acquired:
        if not acquired:raise ValueError('同步正在运行，待其完成后再进行隔离验收')
        with tempfile.TemporaryDirectory(prefix='zotero-validation-',dir=temporary) as directory:
            folder=Path(directory)
            record={'id':'QA-ZOTERO-'+secrets.token_hex(12),
                    'title':'隔离软件验收：非科研文献，验收后清理','doi':None}
            try:
                if z._request('GET',z.PREFIX+'/collections/'+collection,server).status_code==200:
                    raise ValueError('验收集合标识已存在，未修改')
            except requests.HTTPError as exc:
                if exc.response.status_code!=404:raise
            saved=z._request('POST',z.PREFIX+'/collections',server,
                       json=[{'key':collection,'version':0,'name':'隔离软件验收（非科研资料） '+marker,
                              'parentCollection':False}]).json()
            if saved.get('failed'):raise ValueError('Native validation collection: '+json.dumps(saved['failed'],ensure_ascii=True))
            try:
                fail_once=True
                def create(item,remote):
                    nonlocal fail_once
                    item=dict(item)
                    if item['itemType']!='attachment':item['collections']=[collection]
                    writes.append(item['key']);created.append(item['key'])
                    native_create(item,remote)
                    if fail_once:
                        fail_once=False
                        raise requests.Timeout('Isolated test: response lost after native commit')
                with (patch.object(z,'Store',return_value=Store(folder/'intake.sqlite3')),
                      patch.object(z,'_create',side_effect=create)):
                    identifier=z.enqueue(record)
                    first=z.process(identifier)
                    if first['status']!='retry':raise ValueError('未知写入结果未进入待核实状态')
                    recovered=z.process(identifier,force=True)
                    if recovered['status']!='completed' or len(writes)!=1:
                        raise ValueError('原生未知写入未能无重复接续')
                    if z.enqueue(record)!=identifier or z.process(identifier,force=True)['item_key']!=recovered['item_key']:
                        raise ValueError('重复提交未复用正式条目')
                    artifact=folder/'isolated-software-validation.xml'
                    artifact.write_text('<?xml version="1.0"?><software-validation purpose="not-research">API attachment checksum test</software-validation>',encoding='utf-8')
                    attached=z.process(z.enqueue(record,{'path':str(artifact),'kind':'jats_xml'}),force=True)
                    if attached['status']!='completed':raise ValueError('原生附件接续未完成：'+str(attached.get('error')))
                    item=z._get_item(attached['attachment_key'],server)
                    if item.get('md5')!=hashlib.md5(artifact.read_bytes()).hexdigest():
                        raise ValueError('原生附件 MD5 不一致')
                    actual=z.attachment_path(attached['attachment_key'])
                    if actual is None or not actual.is_file() or w.digest(actual.read_bytes())!=w.digest(artifact.read_bytes()):
                        raise ValueError('原生附件内容未通过 SHA256 检查')
                    if len(writes)!=2:raise ValueError('重复创建了原生条目或附件')
                    result={'checked':w.now(),'status':'passed','remembered_authorization':True,
                            'no_doi_metadata':True,'unknown_write_reconciled':True,
                            'repeat_without_duplicate':True,'native_attachment_md5_sha256':True,
                            'original_library_edited':False,'isolated_ledger':True,
                            'native_objects_created':len(writes)}
            finally:
                parent=z._get_item(z.key_for(record['id']),server)
                if parent and not z._identity(parent,record):raise ValueError('验收标识冲突，未清理其他条目')
                for key in reversed(list(dict.fromkeys(created))):
                    item=z._get_item(key,server)
                    if item is None:continue
                    if not (z._identity(item,record) or item.get('parentItem')==z.key_for(record['id'])):
                        raise ValueError('验收对象身份变化，未清理其他条目')
                    z._request('DELETE',z.PREFIX+'/items/'+key,server,
                               headers={'If-Unmodified-Since-Version':str(item['version'])})
                    cleanup.append(key)
                try:remote=z._request('GET',z.PREFIX+'/collections/'+collection,server).json()['data']
                except requests.HTTPError as exc:
                    if exc.response.status_code!=404:raise
                    remote=None
                if remote:
                    if marker not in remote.get('name',''):raise ValueError('验收集合身份变化，未清理')
                    z._request('DELETE',z.PREFIX+'/collections/'+collection,server,
                               headers={'If-Unmodified-Since-Version':str(remote['version'])})
                result_cleanup=len(cleanup)
            result.update(native_objects_cleaned=result_cleanup,test_collection_removed=True,
                          scope='原生 Zotero 隔离写入验收；未导入测试资料到科研知识库，不代表已选取新的真实雷达文献')
    w.write_json(w.ROOT/'output/科研工作区重构/Zotero收录验收.json',result)
    return result


if __name__=='__main__':
    import sys
    if '--isolated-write' not in sys.argv:raise SystemExit('Use --isolated-write to exercise native writes')
    print(json.dumps(verify(),ensure_ascii=True))
