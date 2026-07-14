import unittest

from browser_hit_effects import HIT_EFFECT_CSS, HIT_EFFECT_HTML, HIT_EFFECT_JS


class BrowserHitEffectsTests(unittest.TestCase):
    def test_uses_single_logical_canvas(self):
        self.assertIn('id="impactCanvas" width="1920" height="1080"', HIT_EFFECT_HTML)
        self.assertIn("width: 1920px", HIT_EFFECT_CSS)
        self.assertIn("height: 1080px", HIT_EFFECT_CSS)

    def test_effect_is_directional_not_circular_dom(self):
        source = HIT_EFFECT_CSS + HIT_EFFECT_HTML + HIT_EFFECT_JS
        self.assertNotIn("screenImpact", source)
        self.assertNotIn("radial-gradient", source)
        self.assertNotIn("border-radius:999px", source)
        self.assertIn("impactAngle", source)
        self.assertIn("impactBlade", source)
        self.assertIn("impactChevrons", source)

    def test_strength_and_special_hit_classes_are_distinct(self):
        for class_name in ("low", "mid", "high", "weak", "stun", "down"):
            self.assertIn(class_name, HIT_EFFECT_JS)
        self.assertIn("impactCracks", HIT_EFFECT_JS)

    def test_existing_settings_remain_connected(self):
        for setting in (
            "hitFxBaseSize",
            "hitFxDamageScale",
            "hitFxDurationMs",
            "hitFxPopMs",
            "hitFxOpacity",
            "hitFxGlow",
            "hitFxFillOpacity",
            "hitFxRingWidth",
            "hitFxTextScale",
            "hitFxShowText",
            "hitFxSpriteEnabled",
            "hitFxRingEnabled",
            "hitFxColorPreset",
        ):
            self.assertIn(setting, HIT_EFFECT_JS)

    def test_animation_runs_only_while_effects_are_active(self):
        self.assertIn("if(active.length)impactState.raf=requestAnimationFrame", HIT_EFFECT_JS)
        self.assertIn("if(!impactState.raf)impactState.raf=requestAnimationFrame", HIT_EFFECT_JS)
        self.assertIn("desynchronized:true", HIT_EFFECT_JS)


if __name__ == "__main__":
    unittest.main()
