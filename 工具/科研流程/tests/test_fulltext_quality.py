"""Unreadable text is never model evidence; repairs keep earlier cache versions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import workflow as w
import paper_evidence

BAD = ('\x96\x97\x98 xyz{|}~\x80 }.-*+$%& ' * 90)
GOOD = 'Terahertz spectroscopy measures absorption in controlled samples. ' * 15


class FulltextQualityTests(unittest.TestCase):
    def test_simultaneous_cold_reads_assess_the_same_body_only_once(self):
        import fulltext_parser as parser
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/('a'*64+'.json')
            path.write_text(json.dumps({'pages':[{'page':1,'text':GOOD}]}),encoding='utf-8')
            parser._read_assessed.cache_clear()
            assess=parser.assess_cache;ready=threading.Barrier(3)
            def delayed(value):time.sleep(.05);return assess(value)
            def read():ready.wait();return parser.read_cache(path)
            with patch.object(parser,'assess_cache',side_effect=delayed) as evaluate:
                with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda _:read(),range(3)))
                self.assertTrue(all(result['status']=='ready' for result in results))
                self.assertEqual(evaluate.call_count,1)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.data = self.root/'data'
        self.enterContext(patch.object(w, 'DATA', self.data))
        self.original = self.root/'paper.xml'; self.original.write_text('<article/>', encoding='utf-8')
        self.sha = w.digest(self.original.read_bytes())
        self.record = {'id':'P1', 'artifacts':[{'kind':'jats_xml', 'path':str(self.original)}]}
        self.state = {'papers':{'P1':{'sha256':self.sha}}}
        self.cache = self.data/'正文'/(self.sha+'.json')

    def cached(self, text):
        w.write_json(self.cache, {'sha256':self.sha, 'kind':'jats_xml',
                                 'pages':[{'section':'body', 'text':text, 'method':'jats_xml'}]})

    def test_long_garbled_cache_is_not_ready_or_exposed_as_evidence(self):
        self.cached(BAD)
        result = paper_evidence.fulltext_sources(self.record, self.state)
        self.assertEqual(result['status'], 'low_quality_text')
        self.assertEqual(result['units'], [])

    def test_reading_a_normal_legacy_cache_is_read_only_and_keeps_its_progress_compatibility(self):
        self.cached(GOOD); before = self.cache.read_bytes()
        result = paper_evidence.fulltext_sources(self.record, self.state)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(result.get('text_fingerprint'))
        self.assertEqual(self.cache.read_bytes(), before)
        self.assertFalse((self.cache.parent/(self.sha+'.current.json')).exists())

    def test_explicit_pdf_repair_ocr_is_versioned_and_old_cache_is_preserved(self):
        import fulltext_parser as parser
        self.record['artifacts'][0]['kind'] = 'pdf'; self.cached(BAD)
        old = self.cache.read_bytes()
        page = MagicMock(); page.get_text.return_value = BAD
        pdf = MagicMock(); pdf.__enter__.return_value.__iter__.return_value = iter([page])
        with patch('document_parser.configured', return_value=False), patch('pymupdf.open', return_value=pdf), patch.object(parser, 'ocr_page', return_value=(GOOD, .98)) as ocr:
            result = w.extract(self.record, self.record['artifacts'][0], repair=True)
        self.assertEqual(result['pages'][0]['method'], 'local_ocr')
        self.assertEqual(result['status'], 'ready'); self.assertEqual(ocr.call_count, 1)
        self.assertEqual(self.cache.read_bytes(), old)
        self.assertTrue((self.cache.parent/(self.sha+'.current.json')).exists())
        self.assertEqual(parser.read_cache(self.cache)['text_fingerprint'], result['text_fingerprint'])

    def test_cached_garbage_needs_explicit_repair_and_never_starts_ocr_on_sync(self):
        self.cached(BAD)
        with patch('pymupdf.open', side_effect=AssertionError('cache read must not parse')):
            result = w.extract(self.record, self.record['artifacts'][0])
        self.assertEqual(result['status'], 'low_quality_text')

    def test_scanned_pdf_fallback_reads_text_with_bundled_models_offline(self):
        import cv2
        import fulltext_parser as parser
        import numpy as np
        import pymupdf

        image = np.full((160, 720, 3), 255, dtype=np.uint8)
        cv2.putText(image, 'SCAN TEXT 12345', (32, 102), cv2.FONT_HERSHEY_SIMPLEX,
                    2.2, (0, 0, 0), 4, cv2.LINE_AA)
        success, encoded = cv2.imencode('.png', image)
        self.assertTrue(success)
        path = self.root/'scan.pdf'
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=360, height=80)
            page.insert_image(page.rect, stream=encoded.tobytes())
            pdf.new_page(width=360, height=80)
            pdf.save(path)
        artifact = {'kind': 'pdf', 'path': str(path)}
        original = path.read_bytes()
        with patch('document_parser.configured', return_value=False), \
                patch.object(parser, '_OCR', None), \
                patch('socket.socket.connect', side_effect=AssertionError('OCR must work offline')):
            result = w.extract(self.record, artifact)
        self.assertEqual(result['status'], 'ready')
        text, blank = result['pages']
        self.assertEqual(text['method'], 'local_ocr')
        for word in ('SCAN', 'TEXT', '12345'):
            self.assertIn(word, text['text'])
        self.assertGreaterEqual(text['ocr_mean_confidence'], .75)
        self.assertEqual(blank['text'], '')
        self.assertEqual(blank['ocr_mean_confidence'], 0)
        self.assertEqual(path.read_bytes(), original)

    def test_reading_notes_relations_and_indexing_cannot_bypass_quality_gate(self):
        import paper_notes, relation_discovery
        self.cached(BAD);w.write_json(self.data/'state.json',self.state)
        self.assertIsNone(paper_notes.original_text(self.record)[1])
        item=relation_discovery.paper_input(self.record,self.state)
        self.assertFalse(any(s['kind']=='fulltext_excerpt' for s in item['sources']))
        with self.assertRaises(ValueError): w.indexed_text({'id':'P1','title':'P1'},w.read_json(self.cache,{}))

    def test_repaired_text_cannot_validate_an_old_semantic_index_until_reindexed(self):
        import fulltext_parser as parser
        self.assertFalse(parser.text_changed({}, {'legacy_cache':True,'text_fingerprint':'old'}))
        self.assertTrue(parser.text_changed({}, {'legacy_cache':False,'text_fingerprint':'new','previous_text_fingerprint':'old'}))
        self.assertFalse(parser.text_changed({'text_fingerprint':'new'}, {'text_fingerprint':'new'}))

    def test_ocr_confidence_and_formula_characters_are_distinguished(self):
        import fulltext_parser as parser
        self.assertEqual(parser.text_quality(GOOD)['status'], 'ready')
        self.assertEqual(parser.text_quality('The fitted relation is α = β² + γ; μm 10−3. '*15)['status'], 'ready')
        self.assertEqual(parser.text_quality(GOOD, method='local_ocr', confidence=.35)['status'], 'low_quality_text')
        self.assertEqual(parser.text_quality('')['status'], 'empty')


if __name__ == '__main__': unittest.main()
