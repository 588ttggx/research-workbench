"""First install must create blank state without touching an existing user's files."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'distribution/initialize.py'


class DistributionInitializeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('release_initialize', SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def workspace(self, root):
        (root / '.research-workbench-release.json').write_text(
            json.dumps({'schema_version': 1, 'release_id': 'test'}), encoding='utf-8')
        folder = root / '工具/科研流程/distribution'
        folder.mkdir(parents=True)
        (folder / 'versions.template.json').write_text(json.dumps({
            'schema': 1, 'open_notebook': {'runtime': '工具/OpenNotebook/open-notebook-1.15.0'}}), encoding='utf-8')

    def junction(self, link, target):
        environment={**os.environ,'WORKBENCH_TEST_JUNCTION_PATH':str(link),'WORKBENCH_TEST_JUNCTION_TARGET':str(target)}
        result=subprocess.run([os.environ.get('WORKBENCH_TEST_POWERSHELL','powershell.exe'),'-NoProfile','-NonInteractive','-Command',
                               "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:WORKBENCH_TEST_JUNCTION_PATH -Target $env:WORKBENCH_TEST_JUNCTION_TARGET | Out-Null"],
                              env=environment,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def test_creates_blank_library_and_disabled_automation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.workspace(root)
            self.module.create_workspace(root)
            self.assertEqual(json.loads((root/'科研知识库/文献/library.json').read_text('utf-8'))['records'], [])
            self.assertEqual(list((root/'科研知识库/项目').iterdir()), [])
            saved = json.loads((root/'工具/科研流程/数据/流程设置.json').read_text('utf-8'))
            self.assertFalse(any(saved['values'][key] for key in ('sync_enabled','daily_enabled','ai_enabled','discover_enabled','acquire_enabled')))

    def test_repeat_preserves_user_library_settings_and_generated_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root); self.module.create_workspace(root)
            library=root/'科研知识库/文献/library.json'; library.write_text('user original',encoding='utf-8')
            env=root/'工具/OpenNotebook/open-notebook-1.15.0/.env'; before=env.read_bytes()
            self.module.create_workspace(root)
            self.assertEqual(library.read_text('utf-8'), 'user original')
            self.assertEqual(env.read_bytes(), before)

    def test_refuses_arbitrary_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError): self.module.create_workspace(Path(temporary))

    def test_refuses_template_path_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            template=root/'工具/科研流程/distribution/versions.template.json'
            template.write_text(json.dumps({'open_notebook':{'runtime':'../outside'}}),encoding='utf-8')
            with self.assertRaises(ValueError): self.module.create_workspace(root)

    def test_distinct_installations_have_distinct_database_passwords(self):
        with tempfile.TemporaryDirectory() as temporary:
            first=Path(temporary)/'one';second=Path(temporary)/'two'
            for root in (first,second): root.mkdir();self.workspace(root);self.module.create_workspace(root)
            self.assertNotEqual((first/'工具/OpenNotebook/open-notebook-1.15.0/.env').read_bytes(),
                                (second/'工具/OpenNotebook/open-notebook-1.15.0/.env').read_bytes())

    def test_hardlinked_receipt_is_rejected_before_initialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary); root=parent/'release'; root.mkdir(); self.workspace(root)
            original=parent/'outside.txt'; original.write_text('user original',encoding='utf-8')
            os.link(original,root/'installation.json')
            with patch.object(self.module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{}',stderr='')) as run, self.assertRaises(ValueError):
                self.module.initialize(root)
            run.assert_not_called()
            self.assertEqual(original.read_text('utf-8'),'user original')

    def test_unowned_receipt_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            receipt=root/'installation.json'; receipt.write_text('user original',encoding='utf-8')
            with patch.object(self.module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{}',stderr='')) as run, self.assertRaises(ValueError):
                self.module.initialize(root)
            run.assert_not_called()
            self.assertEqual(receipt.read_text('utf-8'),'user original')

    def test_broken_file_and_directory_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            outside=root/'absent-directory'; outside.mkdir()
            self.junction(root/'broken-directory',outside); outside.rmdir()
            with self.assertRaises(ValueError): self.module.contained(root,'broken-directory')
            original_lstat=Path.lstat
            def broken_lstat(path,*args,**kwargs):
                if path==root/'broken-file':
                    return SimpleNamespace(st_mode=stat.S_IFLNK,st_file_attributes=0x400,st_nlink=1)
                return original_lstat(path,*args,**kwargs)
            # Windows file symlink creation requires an unavailable OS privilege;
            # emulate its lstat result while the dangling directory test is native.
            with patch.object(Path,'lstat',broken_lstat), self.assertRaises(ValueError):
                self.module.contained(root,'broken-file')

    def test_environment_junction_or_symlink_is_rejected_before_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent=Path(temporary); root=parent/'release'; root.mkdir(); self.workspace(root)
            outside=parent/'external-env'; (outside/'Lib/site-packages').mkdir(parents=True)
            self.junction(root/'工具/科研流程/.venv',outside)
            with patch.object(self.module.venv,'EnvBuilder') as builder, self.assertRaises(ValueError):
                self.module.repair_environment(root,'workflow')
            builder.assert_not_called()
            self.assertFalse((outside/'pyvenv.cfg').exists())

    def test_environment_tree_hardlinks_and_pth_are_rejected_before_builder(self):
        for leaf in ('arbitrary-package/file.dat','research_workbench_source.pth'):
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as temporary:
                parent=Path(temporary); root=parent/'release'; root.mkdir(); self.workspace(root)
                site=root/'工具/OpenNotebook/open-notebook-1.15.0/.venv/Lib/site-packages'; site.mkdir(parents=True)
                original=parent/'outside.txt'; original.write_text('user original',encoding='utf-8')
                target=site/leaf; target.parent.mkdir(parents=True,exist_ok=True); os.link(original,target)
                with patch.object(self.module.venv,'EnvBuilder') as builder, self.assertRaises(ValueError):
                    self.module.repair_environment(root,'open-notebook')
                builder.assert_not_called()
                self.assertEqual(original.read_text('utf-8'),'user original')

    def test_broken_link_inside_environment_is_rejected_before_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            site=root/'工具/科研流程/.venv/Lib/site-packages'; site.mkdir(parents=True)
            missing=root/'missing-external-directory'; missing.mkdir()
            self.junction(site/'broken-package',missing); missing.rmdir()
            with patch.object(self.module.venv,'EnvBuilder') as builder, self.assertRaises(ValueError):
                self.module.repair_environment(root,'workflow')
            builder.assert_not_called()

    def owned_receipt(self,root):
        receipt={'schema_version':1,'release_id':'test','status':'initialized','environments':[],
                 'created':[],'existing_files_preserved':True}
        path=root/'installation.json'; path.write_text(json.dumps(receipt),encoding='utf-8')
        return path

    def test_failed_atomic_receipt_publish_preserves_previous_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root); path=self.owned_receipt(root); before=path.read_bytes()
            with patch.object(self.module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{}',stderr='')), \
                 patch.object(self.module.os,'replace',side_effect=OSError('fixture interrupted save')), \
                 self.assertRaises(OSError):
                self.module.initialize(root)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(root.glob('.installation.json.*.tmp')),[])

    def test_concurrent_receipt_change_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root); path=self.owned_receipt(root)
            def change_receipt(*args,**kwargs):
                path.write_text('concurrent user change',encoding='utf-8')
                return subprocess.CompletedProcess([],0,stdout='{}',stderr='')
            with patch.object(self.module.subprocess,'run',side_effect=change_receipt), self.assertRaises(ValueError):
                self.module.initialize(root)
            self.assertEqual(path.read_text('utf-8'),'concurrent user change')

    def test_new_and_owned_repeat_receipts_are_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            with patch.object(self.module.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout='{}',stderr='')):
                self.module.initialize(root)
                result=self.module.initialize(root)
            self.assertEqual(json.loads((root/'installation.json').read_text('utf-8')),result)
            self.assertEqual(result['status'],'initialized')
            self.assertEqual(result['embedding_model']['status'],'not_installed')

    def test_invalid_optional_model_stops_before_environment_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); self.workspace(root)
            with patch.object(self.module,'prepare_model',side_effect=ValueError('Invalid model hash')), \
                 patch.object(self.module.subprocess,'run') as run, self.assertRaises(ValueError):
                self.module.initialize(root)
            run.assert_not_called()
            self.assertFalse((root/'installation.json').exists())

if __name__ == '__main__': unittest.main()
