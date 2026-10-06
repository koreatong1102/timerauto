import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from browser_overlay import BrowserOverlayServer
from config_model import AppConfig, REPORT_WEAK_POINT_PARTS


class ReportWeakPointOptionsTests(unittest.TestCase):
    def test_settings_preserve_empty_and_subset_selections(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "config.json")
            cfg = AppConfig()
            self.assertEqual(cfg.report_weak_point_parts, REPORT_WEAK_POINT_PARTS)
            for selection in ([], ["턱", "간"]):
                cfg.report_weak_point_parts = selection
                cfg.to_json(path)
                self.assertEqual(AppConfig.from_json(path).report_weak_point_parts, selection)

    @unittest.skipUnless(shutil.which("node"), "Node.js required for browser function execution")
    def test_browser_filters_before_top_four_and_keeps_original_statistics(self):
        html = BrowserOverlayServer()._html()
        function = re.search(r"function rrVisibleWeakHits\(data,s\)\{.*?\n\}", html, re.S).group(0)
        hits = [{"label": label, "count": 20 - index} for index, label in enumerate(REPORT_WEAK_POINT_PARTS[:-1])]
        program = function + "\nconst data=" + json.dumps({"weakHitAll": hits}, ensure_ascii=False) + ";\n"
        program += "const before=JSON.stringify(data);console.log(JSON.stringify({selected:rrVisibleWeakHits(data,{reportWeakPointParts:['간','명치']}),empty:rrVisibleWeakHits(data,{reportWeakPointParts:[]}),defaults:rrVisibleWeakHits(data,{}),unchanged:before===JSON.stringify(data)}));"
        result = subprocess.run([shutil.which("node")], input=program, text=True, encoding="utf-8", capture_output=True, check=True)
        rendered = json.loads(result.stdout)
        self.assertEqual([item["label"] for item in rendered["selected"]], ["간", "명치"])
        self.assertEqual(rendered["empty"], [])
        self.assertEqual(len(rendered["defaults"]), 4)
        self.assertTrue(rendered["unchanged"])
