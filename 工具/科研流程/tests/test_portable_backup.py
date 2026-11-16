"""Portable copies of isolated backups restore without Windows account keys."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
import zipfile

import pymupdf

import backup_crypto
import portable_backup


PASSPHRASE = '隔离测试用 synthetic migration phrase'
LIBRARY = '科研知识库/文献/library.json'
PAPER = '原文/PAPER-fixture/0-paper.pdf'


class PortableBackup(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.source = self.root / '旧电脑.zip.dpapi'
        self.carrier = self.root / '便携迁移.research-backup'
        self.destination = self.root / '新电脑 资料'
        former = self.root / '旧路径' / 'PDF'
        self.library = {'records': [{'id': 'PAPER-fixture', 'artifacts': [
            {'path': str(former / 'paper.pdf'), 'kind': 'pdf'},
            {'path': str(former / 'missing.pdf'), 'kind': 'pdf'},
        ]}]}
        database = self.root / 'research.sqlite3'
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE records(id TEXT PRIMARY KEY)')
            db.execute("INSERT INTO records VALUES ('NOTE-fixture')")
            db.commit()
        with pymupdf.open() as document:
            document.new_page().insert_text((48, 64), 'Portable PDF fixture')
            paper = document.tobytes()
        self.files = {LIBRARY: json.dumps(self.library).encode('utf-8'),
                      PAPER: paper,
                      '科研知识库/项目/测试项目/状态.md': '隔离项目记录'.encode('utf-8'),
                      '科研知识库/知识/笔记.md': '隔离知识笔记'.encode('utf-8'),
                      '数据库/open-notebook.surql': (
                          b'-- TABLE: reference\n'
                          b'DEFINE TABLE reference TYPE RELATION IN source OUT notebook SCHEMALESS;\n'
                          b'DEFINE FIELD in ON reference TYPE record<source>;\n'),
                      '数据库/research.sqlite3': database.read_bytes()}

    def make_zip(self, files):
        raw = self.root / 'workspace.zip'
        manifest = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                    for name, data in files.items()}
        with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            archive.writestr('备份清单.json', json.dumps({'schema': 3, 'files': manifest}))
        return raw

    def export(self):
        backup_crypto.protect(self.make_zip(self.files), self.source)
        self.source_digest = backup_crypto.file_digest(self.source)
        portable_backup.export(self.source, self.carrier, PASSPHRASE)

    def test_portable_archive_restores_to_new_directory_without_dpapi(self):
        self.export()
        unrelated = Path(self.library['records'][0]['artifacts'][1]['path'])
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b'unrelated same-name PDF on the destination system')
        with patch.object(backup_crypto.win32crypt, 'CryptUnprotectData',
                          side_effect=AssertionError('destination machine cannot decrypt DPAPI')):
            result = portable_backup.restore(self.carrier, self.destination, PASSPHRASE)
        for name, content in self.files.items():
            if name != LIBRARY:
                self.assertEqual((self.destination / name).read_bytes(), content)
        original = self.destination / '迁移记录/原文献登记.json'
        self.assertEqual(original.read_bytes(), self.files[LIBRARY])
        self.assertEqual(result['relinked_artifacts'], 1)
        self.assertEqual(result['missing_artifacts'], 1)
        self.assertTrue(result['open_notebook_import_prepared'])
        self.assertIn(b'DEFINE FIELD OVERWRITE in ON reference',
                      (self.destination / portable_backup.SURREAL_IMPORT).read_bytes())
        records = json.loads((self.destination / LIBRARY).read_bytes())['records']
        self.assertEqual(records[0]['id'], 'PAPER-fixture')
        self.assertEqual(Path(records[0]['artifacts'][0]['path']), self.destination / PAPER)
        missing = records[0]['artifacts'][1]
        self.assertTrue(Path(missing['path']).is_relative_to(self.destination / portable_backup.MISSING_ORIGINALS))
        self.assertFalse(Path(missing['path']).exists())
        self.assertTrue(unrelated.exists())
        from workflow import chosen_artifact
        self.assertIsNone(chosen_artifact({'artifacts': [missing]}))
        with pymupdf.open(records[0]['artifacts'][0]['path']) as paper:
            self.assertEqual(paper[0].get_text().strip(), 'Portable PDF fixture')
        restored = self.destination / '数据库/research.sqlite3'
        with closing(sqlite3.connect(restored.as_uri() + '?mode=ro', uri=True)) as db:
            self.assertEqual(db.execute('SELECT id FROM records').fetchone(), ('NOTE-fixture',))
        self.assertEqual(backup_crypto.file_digest(self.source), self.source_digest)

    def test_decrypted_working_archive_stays_in_private_local_temp(self):
        destination_disk = self.root / 'external-storage'
        destination_disk.mkdir()
        self.carrier = destination_disk / self.carrier.name
        self.destination = destination_disk / self.destination.name
        private_temp = portable_backup._private_temp()
        with patch.object(backup_crypto, 'opened', wraps=backup_crypto.opened) as opened:
            self.export()
            portable_backup.restore(self.carrier, self.destination, PASSPHRASE)
        self.assertEqual(opened.call_count, 3)
        for request in opened.call_args_list:
            staging_root = Path(request.args[1])
            self.assertTrue(staging_root.is_relative_to(private_temp))
            self.assertFalse(staging_root.is_relative_to(destination_disk))
            self.assertFalse(staging_root.exists())

    def test_wrong_passphrase_and_modified_archive_leave_no_destination(self):
        self.export()
        with self.assertRaisesRegex(ValueError, '认证失败'):
            portable_backup.restore(self.carrier, self.destination, 'wrong synthetic password')
        self.assertFalse(self.destination.exists())
        changed = bytearray(self.carrier.read_bytes())
        changed[-17] ^= 1
        self.carrier.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, '认证失败'):
            portable_backup.restore(self.carrier, self.destination, PASSPHRASE)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob('portable-restore-*')), [])

    def test_existing_target_and_archive_are_preserved(self):
        self.export()
        original = self.carrier.read_bytes()
        with self.assertRaisesRegex(ValueError, '已存在'):
            portable_backup.export(self.source, self.carrier, PASSPHRASE)
        self.assertEqual(self.carrier.read_bytes(), original)
        self.destination.mkdir()
        sentinel = self.destination / '既有笔记.md'
        sentinel.write_bytes(b'existing research')
        with self.assertRaisesRegex(ValueError, '已存在'):
            portable_backup.restore(self.carrier, self.destination, PASSPHRASE)
        self.assertEqual(list(self.destination.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'existing research')

    def test_authenticated_archives_cannot_create_crossing_or_colliding_paths(self):
        for illegal in ('../outside.md', '科研知识库/CON.md',
                        '科研知识库/项目/测试项目/状态.md/nested',
                        '科研知识库/项目/测试项目/状态.MD',
                        '科研知识库/项目/测试项目/A.md:stream',
                        '科研知识库/项目/测试项目/状态.md '):
            with self.subTest(illegal=illegal):
                raw = self.make_zip({**self.files, illegal: b'hostile member'})
                backup_crypto.protect(raw, self.carrier, passphrase=PASSPHRASE)
                with self.assertRaises(ValueError):
                    portable_backup.restore(self.carrier, self.destination, PASSPHRASE)
                self.assertFalse(self.destination.exists())
                self.carrier.unlink()


if __name__ == '__main__':
    unittest.main()
