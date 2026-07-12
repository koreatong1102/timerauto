import unittest

from browser_overlay import BrowserOverlayServer


class BrowserOverlayResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = BrowserOverlayServer()._html()

    def test_overlay_uses_single_logical_stage(self):
        self.assertIn("OVERLAY_BASE_WIDTH=1920", self.html)
        self.assertIn("OVERLAY_BASE_HEIGHT=1080", self.html)
        self.assertIn("Math.min(vw/OVERLAY_BASE_WIDTH,vh/OVERLAY_BASE_HEIGHT)", self.html)
        self.assertIn("--stage-scale", self.html)

    def test_all_overlay_layers_use_stage_dimensions(self):
        self.assertIn("width:1920px!important;height:1080px!important", self.html)
        self.assertIn(".screenImpact{left:calc(var(--ix,.5) * 1920px)!important", self.html)
        self.assertIn(".roundReport{position:absolute!important;width:1920px!important;height:1080px!important", self.html)

    def test_report_reserves_vitals_row(self):
        self.assertIn("grid-template-rows:156px 2px 78px minmax(0,1fr) 94px!important", self.html)
        self.assertIn("height:94px!important;min-height:94px!important", self.html)


if __name__ == "__main__":
    unittest.main()
