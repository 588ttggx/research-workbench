"""Publishing must preserve originals and fail closed before copying private data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from distribution import publish_source as public


class DistributionSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='distribution-source-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'workspace'
        self.root.mkdir()
        self.target = self.root / 'output' / 'release' / 'source'
        self.write('工具/科研流程/dashboard.py', 'print("workbench")\n')

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_allowlist_copies_source_and_licenses_but_no_runtime_data(self):
        selected = [
            '工具/科研流程/frontend/src/app.jsx',
            '工具/科研流程/frontend/package-lock.json',
            '工具/科研流程/frontend/dist/app.js.LICENSE.txt',
            '工具/科研流程/vendor/library/LICENSE',
            '工具/科研流程/r/analysis.R',
            '工具/科研流程/distribution/setup.iss',
            '.agents/rules/research/common.md',
            '.agents/skills/scholarly-paper-collector/scripts/collect_papers.py',
            '.agents/skills/research-organizer/SKILL.md',
        ]
        excluded = [
            'AGENTS.md', '科研知识库/项目/private.md',
            '工具/科研流程/README.md', '工具/科研流程/.env',
            '工具/科研流程/.env.production', '工具/科研流程/数据/research.sqlite3',
            '工具/科研流程/.git/config', '工具/科研流程/tests/legacy/old.py',
            '工具/科研流程/frontend/node_modules/package/index.js',
            '工具/科研流程/frontend/src/nested/.env.local',
            '工具/科研流程/frontend/assets/private.sqlite3',
            '工具/科研流程/verify_locked_environment.py',
            '工具/科研流程/provision_science_tools.py',
            '.agents/skills/private-custom-skill/SKILL.md',
            '工具/n8n/data/local-credentials.dpapi',
        ]
        for relative in selected + excluded:
            self.write(relative, '{}\n')
        report = public.publish_source(self.root, self.target)
        self.assertTrue(report['ready'])
        for relative in selected:
            self.assertTrue((self.target / relative).is_file(), relative)
        for relative in excluded:
            self.assertFalse((self.target / relative).exists(), relative)
        self.assertTrue((self.root / '工具/科研流程/.env').is_file())

    def test_secret_blocks_publish_without_creating_target(self):
        secret = 'gh' + 'p_' + 'a' * 36
        self.write('工具/科研流程/connection.py', 'TOKEN = "' + secret + '"\n')
        with self.assertRaises(public.PublicationBlocked) as caught:
            public.publish_source(self.root, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(caught.exception.findings,
                         [{'path': '工具/科研流程/connection.py', 'line': 1, 'rule': 'github-token'}])
        self.assertNotIn(secret, str(caught.exception))

    def test_generic_credentials_and_private_paths_are_reported_without_values(self):
        secret = 'aRealLookingCredential12345'
        private_path = 'C:' + '/' + 'Users/Alice/Documents/private'
        text = 'api_key = "' + secret + '"\nroot = "' + private_path + '"\n'
        findings = public.scan_text(text, 'sample.py')
        self.assertEqual({item['rule'] for item in findings},
                         {'credential-literal', 'personal-absolute-path'})
        self.assertEqual({item['line'] for item in findings}, {1, 2})
        self.assertNotIn(secret, json.dumps(findings))
        self.assertNotIn(private_path, json.dumps(findings))

    def test_fixed_test_placeholders_do_not_hide_provider_tokens(self):
        self.assertEqual(public.scan_text('api_key="fixture-credential"\npassword="example-password"',
                                          'tests/test_example.py'), [])
        secret = 'gh' + 'p_' + 'f' * 36
        self.assertEqual(public.scan_text('api_key="' + secret + '" # fixture', 'tests/test_example.py')[0]['rule'],
                         'github-token')

    def test_redaction_applies_only_to_published_copy(self):
        private_path = 'D:' + '/Research/private'
        relative = '工具/科研流程/paths.py'
        original = self.write(relative, 'PATH = "' + private_path + '"\n')
        report = public.publish_source(self.root, self.target,
                                       replacements={relative: {private_path: './runtime'}})
        self.assertTrue(report['ready'])
        self.assertIn(private_path, original.read_text('utf-8'))
        self.assertIn('./runtime', (self.target / relative).read_text('utf-8'))
        self.assertNotIn(private_path, json.dumps(report))

    def test_redaction_must_target_selected_file_and_existing_text(self):
        for changes in ({'../escape.py': {'x': 'y'}},
                        {'工具/科研流程/dashboard.py': {'not-present': 'replacement'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                public.publish_source(self.root, self.target, replacements=changes)
        self.assertFalse(self.target.exists())

    def test_source_and_ancestor_targets_are_rejected_without_changes(self):
        before = (self.root / '工具/科研流程/dashboard.py').read_bytes()
        for target in (self.root, self.root.parent, self.root / '工具/科研流程',
                       self.root / '科研知识库', self.root / 'output/../tools'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                public.publish_source(self.root, target)
        self.assertEqual((self.root / '工具/科研流程/dashboard.py').read_bytes(), before)

    def test_existing_unowned_target_is_not_overwritten(self):
        self.target.mkdir(parents=True)
        existing = self.target / 'user.txt'
        existing.write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            public.publish_source(self.root, self.target)
        self.assertEqual(existing.read_text('utf-8'), 'keep')

    def test_repeated_publish_updates_owned_files_and_removes_only_owned_stale_files(self):
        self.write('工具/科研流程/obsolete.py', '# old\n')
        public.publish_source(self.root, self.target)
        (self.root / '工具/科研流程/obsolete.py').unlink()
        self.write('工具/科研流程/dashboard.py', '# updated\n')
        public.publish_source(self.root, self.target)
        self.assertFalse((self.target / '工具/科研流程/obsolete.py').exists())
        self.assertEqual((self.target / '工具/科研流程/dashboard.py').read_text('utf-8'), '# updated\n')

    def test_repeated_publish_preserves_user_edits_and_unknown_files(self):
        public.publish_source(self.root, self.target)
        published = self.target / '工具/科研流程/dashboard.py'
        published.write_text('# user edit\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            public.publish_source(self.root, self.target)
        self.assertEqual(published.read_text('utf-8'), '# user edit\n')

    def test_unknown_hidden_data_blocks_repeat_and_final_scan_reports_it(self):
        public.publish_source(self.root, self.target)
        hidden = self.target / 'data/private.sqlite3'
        hidden.parent.mkdir()
        hidden.write_bytes(b'private data must not be read')
        with self.assertRaises(ValueError):
            public.publish_source(self.root, self.target)
        self.assertEqual(public.scan_tree(self.target),
                         [{'path': 'data/private.sqlite3', 'line': 0, 'rule': 'forbidden-published-file'}])

    def test_scanner_distinguishes_code_expressions_from_credentials_and_paths(self):
        self.assertEqual(public.scan_text('x=flag?e:/regex/.test(x);\n'
                                          'text="MARIADB_ROOT_PASSWORD="+secrets.token_urlsafe(32)\n'
                                          'PREFIX = "/users/0"', 'source.js'), [])

    def test_translated_api_labels_are_not_credentials_but_provider_tokens_still_are(self):
        path='third_party/open-notebook/frontend/src/lib/locales/es-ES/index.ts'
        self.assertEqual(public.scan_text('    apiKey: "API key label",',path),[])
        self.assertEqual(public.scan_text('    apiKey: "Clau de l\'API",',path),[])
        self.assertEqual(public.scan_text('  "Invalid password": "apiErrors.invalidPassword",','errors.ts'),[])
        token='gh'+'p_'+'a'*36
        self.assertEqual(public.scan_text('    apiKey: "'+token+'",',path)[0]['rule'],'github-token')
        self.assertEqual(public.scan_text('apiKey: "API key label"','configuration.ts')[0]['rule'],'credential-literal')

    def test_standard_distribution_replacements_are_strict_and_preserve_originals(self):
        drive = 'E:' + '/fixture-cache'
        content = {
            '工具/科研流程/dataset_store.py': "env.setdefault('DVC_SITE_CACHE_DIR','" + drive + "')\n",
            '工具/科研流程/document_parser.py': "cache = Path(config.get('cache', '" + drive + "'))\n",
            '工具/科研流程/professional_tools.py': "temporary = Path('" + drive + "')\n",
            '工具/科研流程/rspace_runtime.py': "allowed=Path('" + drive + "').absolute()\n",
            '工具/科研流程/scientific_figures.py': "os.environ.setdefault('MPLCONFIGDIR','" + drive + "')\n",
            '.agents/skills/scholarly-paper-collector/scripts/scholarly_collector/config.py':
                'def default_cache(run_dir: Path) -> Path:\n'
                '    configured_root = Path("' + drive + '")\n'
                '    return configured_root / "cache" if os.name == "nt" and configured_root.is_dir() else run_dir / ".spc_cache"\n',
            '.agents/skills/scholarly-paper-collector/references/workspace-workflow.md':
                '- `SPC_CACHE_DIR` 可指定缓存；本机默认沿 `' + drive + '`。\n',
        }
        for path, value in content.items():
            self.write(path, value)
        replacements = public.default_replacements(self.root)
        self.assertEqual(set(replacements), set(content))
        report = public.publish_source(self.root, self.target, replacements=replacements)
        self.assertTrue(report['ready'])
        for path, value in content.items():
            self.assertEqual((self.root / path).read_text('utf-8'), value)
            self.assertNotIn(drive, (self.target / path).read_text('utf-8'))
            if path.endswith('.py'):
                compile((self.target / path).read_text('utf-8'), path, 'exec')
        self.write('工具/科研流程/dataset_store.py', content['工具/科研流程/dataset_store.py'] * 2)
        with self.assertRaises(ValueError):
            public.default_replacements(self.root)

    def test_tampered_marker_cannot_delete_outside_target(self):
        public.publish_source(self.root, self.target)
        marker = self.target / public.MARKER_NAME
        document = json.loads(marker.read_text('utf-8'))
        document['files']['../outside.txt'] = '0' * 64
        marker.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(ValueError):
            public.publish_source(self.root, self.target)

    def test_existing_hardlinks_are_rejected_before_copy_can_change_originals(self):
        public.publish_source(self.root, self.target)
        relative = '工具/科研流程/dashboard.py'
        original = self.root / relative
        published = self.target / relative
        published.unlink()
        os.link(original, published)
        with self.assertRaises(ValueError):
            public.publish_source(self.root, self.target,
                                   replacements={relative: {'workbench': 'changed'}})
        self.assertIn('workbench', original.read_text('utf-8'))

    def test_windows_device_and_alias_paths_are_rejected(self):
        for relative in ('CON', 'folder/NUL.txt', 'safe.txt:alternate', 'path./file.py',
                         'folder//file.py', 'folder/file.py '):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                public._relative(relative)

    def test_source_or_destination_directory_links_are_rejected(self):
        linked = self.root / '工具/科研流程/frontend/src'
        linked.mkdir(parents=True)
        (linked / 'app.js').write_text('public', encoding='utf-8')
        original = public._is_link
        with patch.object(public, '_is_link', side_effect=lambda path: path == linked or original(path)):
            with self.assertRaises(ValueError):
                public.publish_source(self.root, self.target)
        self.target.mkdir(parents=True)
        with patch.object(public, '_is_link', side_effect=lambda path: path == self.target or original(path)):
            with self.assertRaises(ValueError):
                public.publish_source(self.root, self.target)


if __name__ == '__main__':
    unittest.main()
