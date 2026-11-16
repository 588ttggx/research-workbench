"""Keep retired settings inactive when loading an older client's request."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import administrator
import workflow


class RetiredSettingsTests(unittest.TestCase):
    def test_retired_auto_maintain_cannot_be_enabled_or_write_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = '示例项目'
            source = root / '项目' / project / '当前课题状态.md'
            source.parent.mkdir(parents=True)
            source.write_text('# 示例项目\n\n保留用户原稿。\n', encoding='utf-8')
            original = source.read_bytes()

            with patch.object(workflow, 'KB', root), patch.object(workflow, 'DATA', root / 'data'):
                workflow.write_json(workflow.DATA / '科研管理员.json', {'project': project})
                result = administrator.configure({'project': project, 'enabled': True, 'auto_maintain': True})
                self.assertFalse(result['auto_maintain'])
                saved = administrator.settings(project)
                self.assertTrue(saved['enabled'])
                self.assertFalse(saved['auto_maintain'])

            self.assertEqual(source.read_bytes(), original)
