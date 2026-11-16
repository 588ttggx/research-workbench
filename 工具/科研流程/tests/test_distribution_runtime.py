"""Runtime archives retain executable dependencies without copying live state."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from distribution import build_runtime as runtime


class RuntimeArchives(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'workspace'
        self.root.mkdir()
        self.output = self.root / 'output/release'
        self.workflow = self.root / '工具/科研流程'
        self.notebook = self.root / '工具/OpenNotebook/open-notebook-1.15.0'
        self.py313 = Path(self.tmp.name) / 'python313'
        self.py312 = Path(self.tmp.name) / 'python312'
        for base, app, version in ((self.py313, self.workflow, '3.13.13'),
                                   (self.py312, self.notebook, '3.12.13')):
            self.put(base/'python.exe', b'python fixture')
            self.put(base/'LICENSE.txt', 'Python license fixture')
            self.put(base/'Lib/os.py', 'stdlib fixture')
            self.put(base/'Lib/site-packages/private.py', 'unrelated global package')
            self.put(base/'Scripts/old.exe', 'absolute launcher')
            self.put(base/'Doc/manual.txt', 'unnecessary docs')
            self.put(app/'.venv/pyvenv.cfg', f'home = {base}\nversion_info = {version}\n')
            sp = app/'.venv/Lib/site-packages'
            self.put(sp/'dependency/__init__.py', 'dependency code')
            self.put(sp/'dependency-1.0.dist-info/METADATA',
                     'Name: dependency\nVersion: 1.0\nLicense-Expression: MIT\nHome-page: https://example.org/dependency\n')
            self.put(sp/'dependency-1.0.dist-info/LICENSE', 'preserve full license')
            self.put(sp/'dependency-1.0.dist-info/direct_url.json', '{"url":"file:///private"}')
            self.put(sp/'dependency/__pycache__/module.pyc', b'compiled private path')
            self.put(sp/'__editable__fixture.pth', 'import private_finder')
            self.put(sp/'__editable__fixture_finder.py', 'private path')
            self.put(sp/'pywin32.pth', 'win32\nwin32/lib\n')
        for folder in ('api', 'open_notebook', 'commands', 'prompts'):
            self.put(self.notebook/folder/'fixture.py', f'{folder} fixture')
        self.put(self.notebook/'open_notebook/database/migrations/1.surql', 'migration fixture')
        self.put(self.notebook/'LICENSE', 'MIT license fixture')
        self.put(self.notebook/'pyproject.toml', '[project]\nname="open-notebook"\nversion="1.15.0"\n')
        self.put(self.notebook/'.env', 'DO_NOT_READ=private')
        self.put(self.notebook/'data/private.sqlite', b'private database')
        self.put(self.notebook/'frontend/.next/standalone/server.js', 'standalone fixture')
        self.put(self.notebook/'frontend/.next/standalone/node_modules/next/LICENSE', 'next license')
        self.put(self.notebook/'frontend/.next/static/chunk.js', 'static fixture')
        self.put(self.notebook/'frontend/public/icon.svg', '<svg/>')
        self.put(self.notebook/'frontend/node_modules/unneeded/index.js', 'not standalone')
        self.node = Path(self.tmp.name)/'node/node.exe'
        self.node_license = self.node.parent/'LICENSE'
        self.put(self.node, b'node fixture')
        self.put(self.node_license, 'node license fixture')
        self.put(self.root/'工具/OpenNotebook/bin/surreal.exe', b'surreal fixture')
        self.surreal_license = Path(self.tmp.name)/'surreal-LICENSE'
        self.put(self.surreal_license, 'surreal license fixture')
        self.overrides = {'node': self.node, 'node_license': self.node_license,
                          'surreal_license': self.surreal_license}

    @staticmethod
    def put(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))

    def build(self, components=runtime.CORE_COMPONENTS, **kwargs):
        return runtime.build_runtime(self.root, self.output, components,
                                     source_overrides=self.overrides, **kwargs)

    def archive(self, item):
        return zipfile.ZipFile(self.output/item['archive'])

    def test_core_archives_have_installer_paths_hashes_and_complete_licenses(self):
        items = self.build()
        self.assertEqual([item['id'] for item in items], list(runtime.CORE_COMPONENTS))
        for item in items:
            archive = self.output/item['archive']
            self.assertEqual(item['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertEqual(item['size_bytes'], archive.stat().st_size)
            self.assertEqual(item['extract_to'], '.')
            self.assertIs(item['required'], True)
            with self.archive(item) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(item['file_count'], len(z.namelist()))
                self.assertTrue(all(not n.startswith('/') and '\\' not in n and ':' not in n for n in z.namelist()))
        with self.archive(items[0]) as z:
            names = z.namelist()
            self.assertIn('runtime/python313/python.exe', names)
            self.assertIn('工具/科研流程/.venv/Lib/site-packages/dependency-1.0.dist-info/LICENSE', names)
            self.assertIn('工具/科研流程/.venv/Lib/site-packages/pywin32.pth', names)
            self.assertFalse(any(x in n for n in names for x in ('__editable__', 'direct_url.json', '__pycache__', 'Scripts/', 'private.py', 'Doc/')))
        with self.archive(items[2]) as z:
            names = z.namelist()
            prefix = '工具/OpenNotebook/open-notebook-1.15.0/'
            self.assertIn(prefix+'frontend/server.js', names)
            self.assertIn(prefix+'frontend/.next/static/chunk.js', names)
            self.assertIn(prefix+'open_notebook/database/migrations/1.surql', names)
            self.assertFalse(any('.env' in n or 'private.sqlite' in n or 'unneeded' in n for n in names))
        inventory = json.loads((self.output/'runtime_inventory.json').read_text('utf-8'))
        dependency = next(x for x in inventory['packages'] if x['name']=='dependency')
        self.assertEqual(dependency['version'], '1.0')
        self.assertEqual(dependency['license'], 'MIT')
        self.assertNotIn(str(self.root), json.dumps(inventory))

    def test_env_and_live_database_are_never_opened(self):
        real_open = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == '.env' or path.suffix == '.sqlite':
                raise AssertionError('private file was opened')
            return real_open(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            self.build(('open-notebook',))

    def test_inventory_prefers_official_source_repository_for_license_review(self):
        metadata = self.workflow/'.venv/Lib/site-packages/dependency-1.0.dist-info/METADATA'
        self.put(metadata, 'Name: dependency\nVersion: 1.0\nLicense: AGPL-3.0\n'
                 'Project-URL: Documentation, https://example.org/docs\n'
                 'Project-URL: Source, https://github.com/example/dependency\n')
        self.build(('python313',))
        inventory = json.loads((self.output/'runtime_inventory.json').read_text('utf-8'))
        dependency = next(x for x in inventory['packages'] if x['name']=='dependency')
        self.assertEqual(dependency['source'], 'https://github.com/example/dependency')
        self.assertTrue(any('dependency' in x for x in inventory['warnings']))

    def test_missing_dependency_or_license_fails_before_any_zip_is_published(self):
        self.node_license.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.build()
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_links_inside_selected_source_are_rejected(self):
        target = self.py313/'Lib/os.py'
        link = self.py313/'Lib/linked.py'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('OS does not grant symlink creation')
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            self.build(('python313',))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction boundary')
    def test_junction_inside_selected_source_is_rejected_and_target_preserved(self):
        original = Path(self.tmp.name)/'original'
        self.put(original/'keep.txt', 'preserve')
        junction = self.py313/'Lib/junction'
        import _winapi
        _winapi.CreateJunction(str(original), str(junction))
        try:
            with self.assertRaisesRegex(ValueError, '[Ll]ink'):
                self.build(('python313',))
            self.assertEqual((original/'keep.txt').read_text('utf-8'), 'preserve')
        finally:
            junction.rmdir()

    def test_missing_standalone_server_is_not_published_as_runtime(self):
        (self.notebook/'frontend/.next/standalone/server.js').unlink()
        with self.assertRaises(FileNotFoundError):
            self.build(('open-notebook',))
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_enumeration_failure_is_not_silently_ignored(self):
        real_scandir = os.scandir
        def guarded(path):
            if Path(path).name == 'dependency':
                raise PermissionError('isolated unreadable dependency')
            return real_scandir(path)
        with patch.object(runtime.os, 'scandir', guarded):
            with self.assertRaises(PermissionError):
                self.build(('python313',))
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_invalid_home_unknown_component_and_output_outside_project_are_rejected(self):
        self.put(self.workflow/'.venv/pyvenv.cfg', 'home = relative-path\nversion_info=3.13.13\n')
        with self.assertRaises(ValueError):
            self.build(('python313',))
        with self.assertRaises(ValueError):
            self.build(('unexpected',))
        with self.assertRaises(ValueError):
            runtime.build_runtime(self.root, self.root/'工具/release', ('node',), source_overrides=self.overrides)

    def test_archive_limit_failure_never_publishes_partial_files(self):
        with self.assertRaisesRegex(ValueError, '[Ll]imit|[Ll]arge'):
            self.build(('node',), max_archive_bytes=100)
        self.assertEqual(list(self.output.glob('*.zip')), [])
        self.assertEqual(list(self.output.glob('*.partial')), [])

    def test_existing_archive_is_preserved(self):
        self.output.mkdir(parents=True)
        old = self.output/'runtime-node.zip'
        old.write_bytes(b'user existing archive')
        with self.assertRaises(FileExistsError):
            self.build(('node',))
        self.assertEqual(old.read_bytes(), b'user existing archive')

    def test_prepared_frontend_replaces_only_owned_notebook_component(self):
        first = self.build(('python313', 'open-notebook'))
        original_python = (self.output/first[0]['archive']).read_bytes()
        prepared = self.root/'output/prepared-frontend'
        self.put(prepared/'.next/standalone/server.js', 'security-fixed frontend')
        self.put(prepared/'.next/static/new.js', 'new static')
        self.put(prepared/'public/icon.svg', '<svg>new</svg>')
        self.overrides['notebook_frontend'] = prepared
        changed = self.build(('open-notebook',), replace_existing=True)
        with self.archive(changed[0]) as archive:
            self.assertEqual(archive.read('工具/OpenNotebook/open-notebook-1.15.0/frontend/server.js'), b'security-fixed frontend')
        self.assertEqual((self.output/first[0]['archive']).read_bytes(), original_python)
        report = json.loads((self.output/'runtime_inventory.json').read_text('utf-8'))
        self.assertEqual({x['id'] for x in report['components']}, {'python313', 'open-notebook'})
        self.assertEqual(next(x['sha256'] for x in report['components'] if x['id']=='open-notebook'), changed[0]['sha256'])
        self.assertTrue(any(x['name']=='CPython' for x in report['packages']))

    def test_replacement_refuses_a_changed_existing_archive(self):
        items = self.build(('node',))
        archive = self.output/items[0]['archive']
        archive.write_bytes(b'user changed archive')
        with self.assertRaises(ValueError):
            self.build(('node',), replace_existing=True)
        self.assertEqual(archive.read_bytes(), b'user changed archive')


if __name__ == '__main__':
    unittest.main()
