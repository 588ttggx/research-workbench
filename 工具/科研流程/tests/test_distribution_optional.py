"""Optional native tools and verified model assembly use isolated fixtures."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from distribution import build_optional as optional
from distribution import prepare_model


class OptionalTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'workspace'
        self.root.mkdir()
        self.output = self.root/'output/release'
        self.put('工具/R/4.6.1/bin/x64/Rscript.exe', b'R fixture')
        self.put('工具/R/4.6.1/COPYING', 'GNU GENERAL PUBLIC LICENSE Version 2')
        self.put('工具/R/library/example/DESCRIPTION', 'Package: example\nVersion: 1.2\nLicense: MIT\nURL: https://example.org/package\n')
        self.put('工具/R/library/example/LICENSE', 'MIT fixture')
        self.put('工具/Graphviz/16.1.0/Graphviz-16.1.0-win64/bin/dot.exe', b'graphviz fixture')
        self.put('工具/PowerShell/7.6.9/pwsh.exe', b'pwsh fixture')
        self.put('工具/PowerShell/7.6.9/LICENSE.txt', 'MIT fixture')
        self.put('工具/PowerShell/7.6.9/ThirdPartyNotices.txt', 'Third-party fixture')
        self.put('工具/模型/Ollama/ollama.exe', b'ollama fixture')
        self.put('工具/模型/Ollama/lib/cpu.dll', b'library fixture')
        self.put('output/licenses/graphviz-LICENSE.txt', 'Eclipse Public License - v 2.0')
        self.put('output/licenses/ollama-LICENSE.txt', 'MIT License')
        self.put('output/licenses/qwen4b-LICENSE.txt', 'Apache License Version 2.0')
        self.licenses = {name: self.root/f'output/licenses/{name}-LICENSE.txt'
                         for name in ('graphviz', 'ollama', 'qwen4b')}

    def put(self, relative, data):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        return path

    def build(self, components=('r', 'graphviz', 'powershell'), **kwargs):
        return optional.build_optional(self.root, self.output, components,
                                       license_overrides=self.licenses, **kwargs)

    def model(self):
        blobs = [b'config', b'model data'*25, b'metadata']
        descriptors = []
        for index, data in enumerate(blobs):
            digest = hashlib.sha256(data).hexdigest()
            self.put('工具/模型/weights/blobs/sha256-'+digest, data)
            descriptors.append({'digest': 'sha256:'+digest, 'size': len(data),
                                'mediaType': 'application/test'})
        manifest = {'schemaVersion': 2, 'config': descriptors[0], 'layers': descriptors[1:]}
        self.put('工具/模型/weights/manifests/registry.ollama.ai/library/qwen3-embedding/4b', json.dumps(manifest))
        self.put('工具/模型/weights/manifests/registry.ollama.ai/library/qwen3-embedding/0.6b', 'must not copy')
        return descriptors

    def extract(self, items):
        target = self.root/'output/installed'
        target.mkdir()
        for item in items:
            with zipfile.ZipFile(self.output/item['archive']) as z:
                z.extractall(target)
        return target

    def test_small_tools_are_optional_and_retain_license_and_library(self):
        items = self.build()
        self.assertEqual([x['id'] for x in items], ['r', 'graphviz', 'powershell'])
        for item in items:
            self.assertIs(item['required'], False)
            self.assertEqual(item['extract_to'], '.')
            with zipfile.ZipFile(self.output/item['archive']) as z:
                self.assertIsNone(z.testzip())
                self.assertTrue(any('LICENSE' in n or 'COPYING' in n for n in z.namelist()))
        with zipfile.ZipFile(self.output/items[0]['archive']) as z:
            self.assertIn('工具/R/library/example/DESCRIPTION', z.namelist())
        report = json.loads((self.output/'optional_runtime_inventory.json').read_text('utf-8'))
        self.assertEqual(report['native_acceptance'], 'not_tested')
        self.assertTrue(any(p['name']=='R package example' for p in report['packages']))

    def test_missing_required_native_license_blocks_publication(self):
        self.licenses['graphviz'].unlink()
        with self.assertRaises(FileNotFoundError):
            self.build(('graphviz',))
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_hardlinked_native_source_is_not_packaged(self):
        source = self.root/'工具/R/4.6.1/bin/x64/Rscript.exe'
        os.link(source, self.root/'another-name-for-executable')
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            self.build(('r',))
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_model_chunks_reassemble_hashes_and_reuse_existing_blobs(self):
        descriptors = self.model()
        items = self.build(('qwen4b',), chunk_bytes=64)
        self.assertGreater(len(items), 2)
        self.assertTrue(all(x['group']=='qwen4b' and not x['required'] for x in items))
        for item in items:
            with zipfile.ZipFile(self.output/item['archive']) as z:
                self.assertFalse(any('0.6b' in n for n in z.namelist()))
                self.assertTrue(all(i.file_size<=64 for i in z.infolist() if i.filename.endswith('.part')))
        installed = self.extract(items)
        result = prepare_model.prepare_model(installed)
        self.assertEqual(result['status'], 'ready')
        for descriptor in descriptors:
            blob = installed/'工具/模型/weights/blobs'/descriptor['digest'].replace(':', '-')
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), descriptor['digest'][7:])
        self.assertEqual(list((installed/'runtime/model-parts').glob('*.part')), [])
        self.assertEqual(prepare_model.prepare_model(installed)['status'], 'ready')

    def test_bad_chunk_keeps_all_parts_and_does_not_publish_any_blob(self):
        self.model()
        installed = self.extract(self.build(('qwen4b',), chunk_bytes=64))
        chunk = next((installed/'runtime/model-parts').glob('*.part'))
        chunk.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, '[Hh]ash|[Ss]ize'):
            prepare_model.prepare_model(installed)
        self.assertTrue(chunk.exists())
        self.assertEqual(list((installed/'工具/模型/weights/blobs').glob('*')), [])

    def test_existing_different_blob_is_preserved(self):
        descriptors = self.model()
        installed = self.extract(self.build(('qwen4b',), chunk_bytes=64))
        target = installed/'工具/模型/weights/blobs'/descriptors[0]['digest'].replace(':', '-')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'user existing blob')
        with self.assertRaises(ValueError):
            prepare_model.prepare_model(installed)
        self.assertEqual(target.read_bytes(), b'user existing blob')

    def test_model_source_hash_mismatch_is_not_packaged(self):
        descriptors = self.model()
        self.put('工具/模型/weights/blobs/'+descriptors[1]['digest'].replace(':', '-'), b'changed')
        with self.assertRaises(ValueError):
            self.build(('qwen4b',), chunk_bytes=64)
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_model_changed_after_preflight_even_with_restored_mtime_is_rejected(self):
        self.model()
        original = optional._model_sources
        def changed(root):
            manifest, raw, sources = original(root)
            source, _, size, stamp = sources[1]
            source.write_bytes(b'X'*size)
            os.utime(source, ns=(source.stat().st_atime_ns, stamp[3]))
            return manifest, raw, sources
        with patch.object(optional, '_model_sources', changed):
            with self.assertRaises(ValueError):
                self.build(('qwen4b',), chunk_bytes=64)
        self.assertEqual(list(self.output.glob('*.zip')), [])

    def test_manifest_path_traversal_and_hardlinked_part_are_rejected(self):
        self.model()
        items = self.build(('qwen4b',), chunk_bytes=64)
        installed = self.extract(items)
        manifest = installed/'runtime/model-parts/qwen3-embedding-4b.json'
        original = manifest.read_text('utf-8')
        data = json.loads(original)
        data['blobs'][0]['parts'][0]['path'] = '../outside.part'
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            prepare_model.prepare_model(installed)
        manifest.write_text(original, encoding='utf-8')
        part = installed/data['blobs'][1]['parts'][0]['path']
        linked = installed/'outside-hardlink'
        os.link(part, linked)
        with self.assertRaisesRegex(ValueError, '[Ll]ink'):
            prepare_model.prepare_model(installed)
        self.assertTrue(linked.exists())


if __name__ == '__main__':
    unittest.main()
