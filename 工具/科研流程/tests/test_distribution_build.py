"""Release assembly must bind selected files and runtime hashes to one manifest."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

FOLDER=Path(__file__).resolve().parents[1]/'distribution'
sys.path.insert(0,str(FOLDER))

class DistributionBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_release
        cls.module=build_release

    def test_rejects_invalid_repository_or_tag_before_write(self):
        for repository,tag in [('bad/../../secret','v1'),('owner/repo','../tag')]:
            with self.assertRaises(ValueError): self.module.release_url(repository,tag,'core.zip')

    def test_runtime_manifest_detects_changed_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);(folder/'runtime.zip').write_bytes(b'changed')
            component={'archive':'runtime.zip','size_bytes':7,'sha256':'0'*64}
            with self.assertRaises(ValueError):self.module.verify_components(folder,[component])

    def test_config_template_contains_no_author_paths_or_accounts(self):
        value=self.module.versions_template()
        text=json.dumps(value)
        self.assertNotIn('E:',text);self.assertNotIn('Administrator',text)
        self.assertEqual(value['open_notebook']['runtime'],'工具/OpenNotebook/open-notebook-1.15.0')

    def test_manager_adapter_changes_only_release_specific_root(self):
        text="$allowed = [IO.Path]::GetFullPath('"+'X:'+"/fixture/RSpace')\nunchanged\n"
        value=self.module.release_manager(text)
        self.assertIn("Join-Path $workspaceRoot 'runtime/RSpace'",value)
        self.assertIn('unchanged',value)

    def workspace(self,parent):
        root=parent/'workspace'; module=root/'工具/科研流程/distribution'; module.mkdir(parents=True)
        for name,content in {'release_readme.md':'# Public release\n','AGPL-3.0.txt':'fixture license',
                             'Install.ps1':'Write-Output "fixture"\n','Install.cmd':'@echo off\n'}.items():
            (module/name).write_text(content,encoding='utf-8')
        (module.parent/'dashboard.py').write_text('print("fixture")\n',encoding='utf-8')
        service=root/'工具/OpenNotebook'; service.mkdir(parents=True)
        (service/'管理服务.ps1').write_text("$allowed = [IO.Path]::GetFullPath('"+'X:'+"/fixture/RSpace')\n",encoding='utf-8')
        output=root/'output/task/release'; output.mkdir(parents=True)
        (output/'runtime_inventory.json').write_text(json.dumps({'components':[]}),encoding='utf-8')
        return root,output

    def assemble(self,root,output):
        with patch.object(self.module,'default_replacements',return_value={}):
            return self.module.build(root,output,repository='example/workbench',tag='v1')

    def test_scan_failure_does_not_write_repository_or_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary))
            (output/'runtime_inventory.json').write_text(json.dumps({'components':[],'note':'gh'+'p_'+'a'*36}),encoding='utf-8')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertFalse((output.parent/'repository').exists())
            self.assertFalse((output/'core.zip').exists())

    def test_existing_repository_requires_exact_owned_file_set_before_any_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary)); self.assemble(root,output)
            repository=output.parent/'repository'; before=(repository/'README.md').read_bytes()
            (repository/'private.txt').write_text('user original',encoding='utf-8')
            (root/'工具/科研流程/distribution/release_readme.md').write_text('# changed\n',encoding='utf-8')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual((repository/'README.md').read_bytes(),before)
            self.assertEqual((repository/'private.txt').read_text('utf-8'),'user original')

    def test_repository_hardlink_cannot_modify_external_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary); root,output=self.workspace(parent); self.assemble(root,output)
            repository=output.parent/'repository'; readme=repository/'README.md'
            outside=parent/'outside.txt'; outside.write_bytes(readme.read_bytes()); before=outside.read_bytes()
            readme.unlink(); os.link(outside,readme)
            (root/'工具/科研流程/distribution/release_readme.md').write_text('# changed\n',encoding='utf-8')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual(outside.read_bytes(),before)

    def test_repository_directory_junction_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary); root,output=self.workspace(parent); outside=parent/'outside';outside.mkdir()
            environment={**os.environ,'WORKBENCH_TEST_JUNCTION_PATH':str(output.parent/'repository'),
                         'WORKBENCH_TEST_JUNCTION_TARGET':str(outside)}
            result=subprocess.run([os.environ.get('WORKBENCH_TEST_POWERSHELL','powershell.exe'),'-NoProfile','-NonInteractive','-Command',
                                   "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:WORKBENCH_TEST_JUNCTION_PATH -Target $env:WORKBENCH_TEST_JUNCTION_TARGET | Out-Null"],
                                  env=environment,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual(list(outside.iterdir()),[])

    def test_tampered_ownership_paths_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary)); self.assemble(root,output)
            ownership=output.parent/'repository-build.json'; saved=json.loads(ownership.read_text('utf-8'))
            outside=output.parent/'outside.txt'; outside.write_text('preserve',encoding='utf-8')
            saved['files']['../outside.txt']=hashlib.sha256(outside.read_bytes()).hexdigest()
            ownership.write_text(json.dumps(saved),encoding='utf-8')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual(outside.read_text('utf-8'),'preserve')

    def test_repeat_preserves_git_and_zip_contains_only_current_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary))
            obsolete=root/'工具/科研流程/obsolete.py';obsolete.write_text('# old',encoding='utf-8')
            self.assemble(root,output)
            repository=output.parent/'repository';git=repository/'.git';git.mkdir()
            (git/'config').write_text('private git state',encoding='utf-8')
            obsolete.unlink();self.assemble(root,output)
            self.assertEqual((git/'config').read_text('utf-8'),'private git state')
            self.assertFalse((repository/'工具/科研流程/obsolete.py').exists())
            saved=json.loads((output.parent/'repository-build.json').read_text('utf-8'))
            with zipfile.ZipFile(output/'core.zip') as archive:
                self.assertEqual(set(archive.namelist()),set(saved['files']))
                self.assertNotIn('.workbench-source-staging.json',archive.namelist())
                self.assertFalse(any(name.startswith('.git/') for name in archive.namelist()))
                self.assertEqual(archive.read('工具/科研流程/distribution/Install.ps1'),(output/'Install.ps1').read_bytes())

    def frontend(self,folder):
        folder.mkdir()
        for name in ('next.config.ts','next-env.d.ts','tsconfig.json','postcss.config.mjs','components.json',
                     'eslint.config.mjs','start-server.js','vitest.config.ts','LICENSE'):
            (folder/name).write_text('// fixture source',encoding='utf-8')
        package={'dependencies':{'next':'16.4.1','zod':'4.6.6'},'overrides':{'follow-redirects':'1.16.2'}}
        lock={'packages':{'node_modules/'+name:{'version':value}
                          for name,value in {'next':'16.4.1','zod':'4.6.6','follow-redirects':'1.16.2'}.items()}}
        (folder/'package.json').write_text(json.dumps(package),encoding='utf-8')
        (folder/'package-lock.json').write_text(json.dumps(lock),encoding='utf-8')
        source=folder/'src/lib/data/example.ts';source.parent.mkdir(parents=True);source.write_text('export const value=1',encoding='utf-8')
        public=folder/'public/logo.svg';public.parent.mkdir();public.write_text('<svg/>',encoding='utf-8')

    def test_corresponding_frontend_source_keeps_code_and_licenses_without_build_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'frontend';self.frontend(folder)
            (folder/'.env.local').write_text('private configuration',encoding='utf-8')
            (folder/'node_modules').mkdir();(folder/'node_modules/private.js').write_text('private',encoding='utf-8')
            files=self.module.frontend_files(folder,{'sha256':'a'*64})
            prefix='third_party/open-notebook/frontend/'
            self.assertIn(prefix+'src/lib/data/example.ts',files)
            self.assertIn(prefix+'LICENSE',files)
            self.assertNotIn(prefix+'.env.local',files)
            self.assertFalse(any('node_modules/' in name for name in files))
            manifest=json.loads(files['third_party/open-notebook/frontend-source-manifest.json'])
            self.assertEqual(manifest['binary_sha256'],'a'*64)
            self.assertEqual(manifest['files']['package.json'],hashlib.sha256(files[prefix+'package.json']).hexdigest())

    def test_frontend_lock_and_source_dependency_pins_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'frontend';self.frontend(folder)
            lock=json.loads((folder/'package-lock.json').read_text('utf-8'))
            lock['packages']['node_modules/next']['version']='16.4.0'
            (folder/'package-lock.json').write_text(json.dumps(lock),encoding='utf-8')
            with self.assertRaises(ValueError):self.module.frontend_files(folder,{'sha256':'a'*64})

    def test_changed_core_blocks_repository_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary));self.assemble(root,output)
            repository=output.parent/'repository';before=(repository/'README.md').read_bytes()
            (root/'工具/科研流程/distribution/release_readme.md').write_text('# changed',encoding='utf-8')
            (output/'core.zip').write_bytes(b'user archive')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual((repository/'README.md').read_bytes(),before)
            self.assertEqual((output/'core.zip').read_bytes(),b'user archive')

    def test_changed_generated_manifest_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary));self.assemble(root,output)
            manifest=output/'manifest.json';manifest.write_text('user original',encoding='utf-8')
            with self.assertRaises(ValueError):self.assemble(root,output)
            self.assertEqual(manifest.read_text('utf-8'),'user original')

    def test_optional_runtime_inventory_preserves_optional_selection_and_model_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary))
            archive=output/'runtime-ollama.zip';archive.write_bytes(b'isolated optional runtime')
            component={'id':'ollama','archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                       'size_bytes':archive.stat().st_size,'required':False,'extract_to':'.','group':'ollama'}
            inventory=output/'optional_runtime_inventory.json';inventory.write_text(json.dumps({'components':[component]}),encoding='utf-8')
            self.assemble(root,output)
            manifest=json.loads((output/'manifest.json').read_text('utf-8'))
            selected=next(item for item in manifest['components'] if item['id']=='ollama')
            self.assertFalse(selected['required']);self.assertEqual(selected['group'],'qwen4b')
            self.assertEqual(json.loads(inventory.read_text('utf-8'))['components'][0]['group'],'ollama')

    def test_atomic_file_replace_failure_keeps_original_and_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root,output=self.workspace(Path(temporary));self.assemble(root,output)
            repository=output.parent/'repository';readme=repository/'README.md'; before=readme.read_bytes()
            ownership=output.parent/'repository-build.json';owned_before=ownership.read_bytes()
            (root/'工具/科研流程/distribution/release_readme.md').write_text('# changed',encoding='utf-8')
            replace=os.replace
            def interrupt(source,destination):
                if Path(destination)==readme:raise OSError('fixture interrupted replacement')
                return replace(source,destination)
            with patch.object(self.module.os,'replace',side_effect=interrupt),self.assertRaises(OSError):
                self.assemble(root,output)
            self.assertEqual(readme.read_bytes(),before)
            self.assertEqual(ownership.read_bytes(),owned_before)

if __name__=='__main__':unittest.main()
