"""Read the six live areas; exercise version writes only in a disposable lab."""
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import os
import tempfile
import threading
from urllib.parse import urljoin
from unittest.mock import patch
from playwright.sync_api import sync_playwright
import workflow as w
import dashboard as d
import research_store as rs
import dataset_store as data
import analysis_runs
import data_analysis


def verify():
    stage=w.ROOT/'output/科研工作区重构/_临时';stage.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='delivery-browser-',dir=stage) as temporary,patch.dict(os.environ,{'TEMP':temporary,'TMP':temporary}):
        return _verify()


def _verify():
    root=w.ROOT;checks={};errors=[]
    with sync_playwright() as browser_runtime:
        browser=browser_runtime.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1060})
        page.on('pageerror',lambda error:errors.append(str(error)))
        for route in ['discover','knowledge','projects','lab','analyze','outputs']:
            response=page.goto('http://127.0.0.1:8503/#'+route,wait_until='networkidle')
            page.wait_for_function("()=>typeof S!=='undefined'&&S.workspace&&document.querySelector('#view h1')")
            assert response is None or response.status==200
            checks[route]=page.locator('#view h1').inner_text()
        page.evaluate('()=>showSettings()')
        page.get_by_text('旧同步迁移已完成',exact=True).wait_for(timeout=30000)
        assert page.get_by_role('button',name='核对原稿并取消旧双向同步',exact=True).count()==0
        checks['native_note_migration']='completed; no duplicate action'
        native=page.request.get('http://127.0.0.1:8503/api/note-sync/boundary').json()
        assert native['status']=='ready' and native['last']['status']=='completed'
        checks['native_note_remaining']=native['last']['remaining_workspace_registrations']
        assert len(native['history'])==6 and all(r['status']=='retired_history' for r in native['history'])
        page.get_by_text('查看已保留的旧同步稿',exact=True).click()
        page.get_by_role('button',name=native['history'][0]['title'],exact=True).click()
        page.get_by_role('button',name='打开当前知识主稿',exact=True).wait_for()
        assert page.get_by_role('button',name='以当前主稿为准，完成核对',exact=True).count()==0
        checks['retired_sync_history']='6 records readable; no repeated review control'
        page.locator('#overlay').evaluate('(dialog)=>dialog.close()')
        page.evaluate('()=>showSettings()')
        page.get_by_text('旧同步迁移已完成',exact=True).wait_for()
        page.set_viewport_size({'width':780,'height':1000})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        checks['narrow_settings']='passed'
        page.screenshot(path=str(root/'output/科研工作区重构/原生软件维护入口.png'))
        page.close()

        stage=root/'_临时/科研区维护';stage.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='version-ui-',dir=stage) as temporary,ExitStack() as scope:
            isolated=Path(temporary).resolve()
            for target,value in [('ROOT',isolated),('KB',isolated/'科研知识库'),('DATA',isolated/'state'),('LIBRARY',isolated/'科研知识库/文献/library.json')]:
                scope.enter_context(patch.object(w,target,value))
            scope.enter_context(patch.object(rs,'DEFAULT_DB',w.DATA/'research.sqlite3'))
            scope.enter_context(patch.object(d,'model_status',return_value={'configured':False}))
            scope.enter_context(patch.dict(os.environ,{'DVC_SITE_CACHE_DIR':str(isolated/'cache/dvc'),'MPLCONFIGDIR':str(isolated/'cache/matplotlib')}))
            w.write_json(w.LIBRARY,{'records':[]})
            w.atomic_text(w.KB/'项目/山药/当前课题状态.md','# SOFTWARE_TEST_ONLY\n\n仅用于软件界面验收。\n')
            w.atomic_text(w.KB/'项目/山药/研究主线.md','---\nresearch_lines: []\n---\n# SOFTWARE_TEST_ONLY\n')
            repository=w.ROOT/'数据/数据版本';repository.mkdir(parents=True)
            data.command(['git','init','-q'],repository)
            data.command([__import__('sys').executable,'-m','dvc','init','-q'],repository)
            csv='x,y\n1,3\n2,5\n3,7\n';dataset=data.store_input(csv,'山药','SOFTWARE_TEST_ONLY.csv')
            result=data_analysis.compute(csv,'regression')
            result.update(project='山药',id='f'*24,created=w.now(),filename='SOFTWARE_TEST_ONLY.csv',
                path='项目/山药/test.md',source_root='workspace',source=dataset['uri'],source_sha256=dataset['sha256'],dataset=dataset)
            identifier=analysis_runs.register(result,{})['run_id']
            server=ThreadingHTTPServer(('127.0.0.1',0),d.Handler)
            url='http://127.0.0.1:'+str(server.server_port)
            scope.enter_context(patch.object(d,'ORIGIN',url))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                page=browser.new_page(viewport={'width':1440,'height':1060})
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(url+'/#analyze',wait_until='networkidle')
                page.wait_for_function("()=>typeof S!=='undefined'&&S.workspace!==null")
                try:page.get_by_role('button',name='选择分析文件',exact=True).wait_for(timeout=10000)
                except Exception:
                    diagnostics=[]
                    for endpoint in ('/api/data-analysis/history?project=山药','/api/research?project=山药','/api/analysis-automation'):
                        response=page.request.get(url+endpoint);diagnostics.append((endpoint,response.status,response.text()[:300] if response.status!=200 else 'ok'))
                    raise AssertionError(page.locator('#view').inner_text()+'; '+str(errors)+'; '+str(diagnostics))
                assert page.get_by_role('button',name='选择分析文件',exact=True).count()==1
                assert '实战' not in page.locator('#view').inner_text()
                rejected=page.request.post(url+'/api/validation/run',data={},headers={'Origin':url})
                assert rejected.status==410
                checks['removed_demo']='no UI, no background entry, old write endpoint returns 410'
                page.locator('#view input[type=file]').set_input_files({'name':'SOFTWARE_TEST_ONLY.csv','mimeType':'text/csv','buffer':csv.encode()})
                page.get_by_role('heading',name='分析设置',exact=True).wait_for()
                page.get_by_text('3 行 · 2 个数值列；列名：x、y',exact=True).wait_for()
                page.get_by_role('button',name='分析并保存',exact=True).click()
                page.get_by_role('heading',name='输入文件与分析说明',exact=True).wait_for(timeout=60000)
                assert page.get_by_role('button',name='编辑分析说明',exact=True).count()==1
                assert str(repository/'datasets') in page.locator('#view').inner_text()
                download=page.get_by_role('link',name='下载本次输入文件',exact=True)
                input_url=urljoin(url,download.get_attribute('href'))
                assert input_url.startswith(url+'/api/data-analysis/input?')
                assert page.request.get(input_url).body()==csv.encode()
                assert page.get_by_role('button',name='调整图表',exact=True).count()==1
                checks['file_import']='select file, inspect columns, calculate, locate saved input, download exact bytes, edit note and chart'
                page.set_viewport_size({'width':780,'height':1000})
                page.wait_for_function("()=>{const host=document.querySelector('.analysis-figure'),svg=host?.querySelector('.main-svg');return svg&&svg.getBoundingClientRect().width<=host.getBoundingClientRect().width+1}")
                assert page.evaluate("()=>{const host=document.querySelector('.analysis-figure'),svg=host.querySelector('.main-svg');return svg.getBoundingClientRect().height<=host.getBoundingClientRect().height+1}")
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                page.screenshot(path=str(root/'output/科研工作区重构/分析文件入口.png'))
                page.evaluate('(id)=>showRunTrace(id)',identifier)
                page.get_by_role('button',name='冻结这次运行的版本',exact=True).click()
                page.get_by_role('link',name='查看冻结清单',exact=True).wait_for(timeout=30000)
                assert page.get_by_role('button',name='冻结这次运行的版本',exact=True).count()==0
                seal=page.request.get(url+'/api/research/version-seal?id='+identifier)
                assert seal.ok and seal.json()['run_id']==identifier
                assert rs.Store().node(identifier)['data']['formal'] is False
                assert len(data.command(['git','tag','--list','run/*'],repository).splitlines())==1
                checks['version_freeze']='native Git/DVC, UI, download, research approval unchanged'
                page.set_viewport_size({'width':780,'height':1000})
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                checks['narrow_version_details']='passed'
                page.screenshot(path=str(root/'output/科研工作区重构/版本冻结界面.png'))
                page.close()
            finally:server.shutdown();server.server_close();thread.join(timeout=5)
        browser.close()
    assert not errors,errors
    receipt_path=root/'output/科研工作区重构/本轮验收汇总.json'
    receipt=w.read_json(receipt_path)
    receipt.setdefault('maintenance_completion',{})['delivery_ui']={'checked':w.now(),'checks':checks,'page_errors':errors,
        'scientific_record_writes':'disposable directory only; temporary database and native Git/DVC removed'}
    w.write_json(receipt_path,receipt)
    return checks


if __name__=='__main__':print(json.dumps(verify(),ensure_ascii=True))
