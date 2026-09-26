import os
import unittest
from pathlib import Path

from browser_overlay import BrowserOverlayServer


class BrowserOverlayResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = BrowserOverlayServer()._html()

    def test_ko_latency_probe_beacon_is_available_to_settings(self):
        server = BrowserOverlayServer()
        self.assertIsNone(server.latency_beacon("probe"))
        server.record_latency_beacon("ko_probe_show", "probe", "1234", "1200")
        self.assertEqual(server.latency_beacon("probe")["browser_ms"], "1234")
        self.assertIn("overlayBeacon('ko_probe_show'", self.html)

    def test_overlay_uses_single_logical_stage(self):
        self.assertIn("OVERLAY_BASE_WIDTH=1920", self.html)
        self.assertIn("OVERLAY_BASE_HEIGHT=1080", self.html)
        self.assertIn("Math.min(vw/OVERLAY_BASE_WIDTH,vh/OVERLAY_BASE_HEIGHT)", self.html)
        self.assertIn("--stage-scale", self.html)

    def test_overlay_rejects_out_of_order_state_snapshots(self):
        self.assertIn("let newestOverlayStateSeq=-1", self.html)
        self.assertIn("incomingSeq<=newestOverlayStateSeq", self.html)
        self.assertIn("const renderInStateOrder=render", self.html)

    def test_all_overlay_layers_use_stage_dimensions(self):
        self.assertIn("width:1920px!important;height:1080px!important", self.html)
        self.assertIn('id="impactCanvas" width="1920" height="1080"', self.html)
        self.assertIn("#impactCanvas", self.html)
        self.assertIn(".roundReport{position:absolute!important;width:1920px!important;height:1080px!important", self.html)

    def test_report_reserves_vitals_row(self):
        self.assertIn('grid-template-areas:"player" "style" "accent" "highlight" "details" "vitals"!important', self.html)
        self.assertIn("grid-area:vitals", self.html)
        self.assertIn("minmax(270px,2.25fr)", self.html)
        self.assertIn("grid-template-rows:repeat(2,minmax(0,1fr))!important", self.html)

    def test_sp_bar_layout_is_runtime_configurable(self):
        state = BrowserOverlayServer().snapshot()
        self.assertEqual(state["spBarX"], 0)
        self.assertEqual(state["spBarY"], 0)
        self.assertEqual(state["spBarLengthPct"], 100)
        self.assertEqual(state["spBarThickness"], 10)
        self.assertEqual(state["spBarColor"], "#1876d3")
        self.assertIn("function applySpBarLayout", self.html)
        self.assertIn("spBarLengthPct", self.html)
        self.assertIn("spBarThickness", self.html)
        self.assertIn("spBarColor", self.html)

    def test_name_bar_layout_is_runtime_configurable(self):
        state = BrowserOverlayServer().snapshot()
        self.assertEqual(state["nameBarX"], 0)
        self.assertEqual(state["nameBarY"], 0)
        self.assertIn("function applyNameBarLayout", self.html)
        self.assertIn("applyNameBarLayout(s)", self.html)

    def test_final_report_has_korean_fight_style_badge(self):
        self.assertIn("경기 스타일", self.html)
        self.assertIn("rrFightStyle", self.html)
        self.assertIn("styleLabel!=='분석 중'", self.html)
        self.assertIn("grid-area:style", self.html)
        self.assertIn("grid-template-rows:minmax(48px,.58fr) minmax(74px,1fr)", self.html)
        self.assertIn("font-size:clamp(28px,1.65vw,33px)", self.html)

    def test_report_sequence_rejects_late_stale_stage(self):
        self.assertIn("roundReportFlow", self.html)
        self.assertIn("reportSequenceId", self.html)
        self.assertIn("pos.stage>0", self.html)
        self.assertIn("rrResetReportFlow", self.html)

    def test_round_intro_respects_round_visibility_setting(self):
        self.assertIn("function hideRoundIntro()", self.html)
        self.assertIn("s.showRound===false||s.showCinematic===false", self.html)
        self.assertIn("if(s.showRound===false)hideRoundIntro()", self.html)

    def test_combat_event_director_uses_central_engine_metadata(self):
        self.assertIn("function directCombatEvent(e)", self.html)
        self.assertIn("eventTags", self.html)
        self.assertIn("counterReason", self.html)
        self.assertIn("comboHits", self.html)
        self.assertIn("comboDamage", self.html)
        self.assertIn("kind==='combat_event'", self.html)

    def test_combat_event_director_has_priority_and_minimum_dwell(self):
        self.assertIn("function showDirectedCombat(", self.html)
        self.assertIn("state.minUntil=now+1200", self.html)
        self.assertIn("priority<state.priority", self.html)
        self.assertIn("syncDirectedCombat('blue'", self.html)
        self.assertIn("syncDirectedCombat('red'", self.html)
        self.assertIn("lastCombo[side]=state.label+'|'+state.detail", self.html)
        self.assertIn("combo(side,'','',false)", self.html)
        self.assertNotIn("const rrSyncDirectedCombatBase=syncDirectedCombat", self.html)
        self.assertNotIn("rrCombatSyncPending", self.html)
        self.assertIn("eventRound!==knownRound", self.html)
        self.assertIn("combatDirector.chains={blue:[],red:[]}", self.html)
        self.assertIn("'counter');", self.html)
        self.assertNotIn("'counter-combo');", self.html)
        self.assertNotIn("'signature:'+hits", self.html)

    def test_combat_event_director_supports_adaptive_labels(self):
        for label in (
            "WHIFF PUNISH",
            "addLabel(counterDisplay?'HIT '+hits:hits+' HIT COMBO')",
            "SIGNATURE BLOW",
            "HEAVY BLOW",
            "KNOCKDOWN",
            "'TKO'",
            "ANSWER BACK",
            "MOMENTUM",
            "TARGET LOCK",
        ):
            self.assertIn(label, self.html)
        self.assertIn("if(!labels.length&&tags.has('answer_back'))", self.html)
        self.assertIn("if(!labels.length&&tags.has('heavy')&&damage>=60)", self.html)
        self.assertIn("else if(!labels.length&&tags.has('momentum'))", self.html)
        self.assertIn("else if(!labels.length&&tags.has('target_lock'))", self.html)
        self.assertNotIn("targetTriggered", self.html)
        self.assertNotIn("replyTo&&", self.html)
        self.assertNotIn("if(tags.has('decisive'))return", self.html)
        self.assertIn("priority=110;holdMs=2600", self.html)

    def test_combat_event_merges_labels_and_blocks_legacy_resurrection(self):
        self.assertIn("labels.join('\\n')", self.html)
        self.assertIn("details.join('\\n')", self.html)
        self.assertIn("function combatWeakLabel(value)", self.html)
        self.assertIn("if(weakLabel)addDetail(weakLabel)", self.html)
        self.assertIn("Central combat events are the only browser presentation authority", self.html)
        self.assertNotIn("combo(side,stateHit,stateDamage,false)", self.html)

    def test_combat_event_card_uses_compact_vertical_layout(self):
        self.assertIn("width:228px!important", self.html)
        self.assertIn("max-width:210px!important", self.html)
        self.assertIn("white-space:pre-line!important", self.html)
        self.assertIn("word-break:keep-all!important", self.html)

    def test_counter_followup_grows_the_same_card(self):
        self.assertIn("let counterFollowup=hits>=2", self.html)
        self.assertIn("startsWith('counter:')", self.html)
        self.assertIn("let counterDisplay=isCounter||counterFollowup", self.html)
        self.assertIn("'counter:'+semanticKey", self.html)
        self.assertIn("counterFollowup?String(directedState.key)", self.html)

    def test_combat_event_director_logs_show_update_suppression_and_hide(self):
        for event in (
            "combat_show",
            "combat_update",
            "combat_suppressed",
            "combat_hide",
        ):
            self.assertIn(event, self.html)
        self.assertIn("semanticKey", self.html)

    def test_health_bar_does_not_use_expiring_damage_prediction(self):
        self.assertIn("optimisticGaugeHit=function(_side,_dmg){}", self.html)
        self.assertNotIn("const rrPredictedHp", self.html)
        self.assertNotIn("Date.now()+950", self.html)

    def test_portrait_impacts_distinguish_stun_kd_ko_and_tko(self):
        self.assertIn("portrait(side,'tko',260,dmg)", self.html)
        self.assertIn("portrait(side,'kd',260,dmg)", self.html)
        self.assertIn("portrait(side,'ko',260,dmg)", self.html)
        self.assertIn("cls==='tko'?6:cls==='ko'?5:cls==='kd'?4", self.html)
        self.assertIn("if(fx==='tko')return 900", self.html)
        self.assertIn("if(fx==='ko')return 1100", self.html)
        self.assertIn("if(fx==='kd')return 800", self.html)
        self.assertIn("if(fx==='stun')return 550", self.html)

    def test_portrait_impacts_have_local_fx_and_event_specific_motion(self):
        for name in (
            "bluePortraitImpactStun58",
            "redPortraitImpactStun58",
            "bluePortraitImpactKd58",
            "redPortraitImpactKd58",
            "bluePortraitImpactKo58",
            "redPortraitImpactKo58",
            "bluePortraitImpactTko58",
            "redPortraitImpactTko58",
        ):
            self.assertIn(name, self.html)
        self.assertIn(".portraitFxLayer.kd", self.html)
        self.assertIn(".portraitFxLayer.tko", self.html)
        self.assertIn("alignPortraitFxLayer(side,img,layer)", self.html)
        self.assertIn("allFx=['hit','heavy','stun','kd','ko','tko']", self.html)

    def test_knockdown_uses_preloaded_image_impact_pipeline(self):
        state = BrowserOverlayServer().snapshot()
        self.assertEqual(state["koImageScalePct"], 100)
        self.assertEqual(state["koMotionBlurPct"], 100)
        self.assertEqual(state["koFlashIntensityPct"], 100)
        self.assertEqual(state["koTrailIntensityPct"], 100)
        self.assertEqual(state["koShakeIntensityPct"], 100)
        self.assertEqual(state["koPerspectivePx"], 1400)
        self.assertEqual(state["koStartZPx"], 760)
        self.assertEqual(state["koImpactDepthPx"], 34)
        self.assertEqual(state["koReboundPx"], 20)
        self.assertEqual(state["koEntryMs"], 500)
        self.assertEqual(state["koDropYPx"], 190)
        self.assertEqual(state["koKdHoldMs"], 2200)
        self.assertEqual(state["koTkoHoldMs"], 2600)
        self.assertIn('id="koTrailFar"', self.html)
        self.assertIn('id="koTrailNear"', self.html)
        self.assertIn('id="koArt"', self.html)
        self.assertIn("function syncKoAssets(s)", self.html)
        self.assertIn("function showKO(mode,s)", self.html)
        self.assertIn("let koRunToken=0", self.html)
        self.assertIn("timers.koSettle=setTimeout", self.html)
        self.assertIn("el.classList.add('settled')", self.html)
        self.assertIn("showKO('tko',s)", self.html)
        self.assertIn("showKO('kd',s)", self.html)
        self.assertIn("let baseWidth=mode==='tko'?540:490", self.html)
        self.assertIn("let depthFrames=mode==='tko'?", self.html)
        self.assertIn("{transform:'translateZ('+startZ+'px)'", self.html)
        self.assertIn("let dropY=Math.max(0,Math.min(500", self.html)
        self.assertIn("let impactMs=Math.round(entryDuration*impactRatio)", self.html)
        self.assertIn("translate(0,'+(-dropY)+'px)", self.html)
        self.assertIn("duration:entryDuration+(mode==='tko'?180:140)", self.html)
        self.assertIn("delay:impactMs", self.html)
        self.assertIn("trailStrength", self.html)
        self.assertIn("shakeStrength", self.html)
        self.assertIn("depth.style.transform='translateZ(0)'", self.html)
        self.assertNotIn("translateZ(-1180px) scale(.28)", self.html)
        self.assertNotIn("depth.style.transform='translateZ(0) scale(1)'", self.html)
        self.assertNotIn('id="koShockA"', self.html)
        self.assertNotIn('id="koShockB"', self.html)
        self.assertNotIn(".koShock{", self.html)
        self.assertNotIn("{transform:'translate(0,0)',offset:0},{transform:'translate(0,0)',offset:.35}", self.html)
        self.assertNotIn('class="koPanel"', self.html)

    def test_knockdown_assets_are_registered_with_revisions(self):
        root = Path(__file__).resolve().parents[1]

        def resolve(path):
            raw = Path(str(path))
            return str(raw if raw.is_absolute() else root / raw)

        server = BrowserOverlayServer(path_resolver=resolve)
        server.set_asset_path("kd", "assets/images/overlays/KD.png")
        server.set_asset_path("tko", "assets/images/overlays/TKO.png")
        state = server.snapshot()
        self.assertTrue(os.path.isfile(server.asset_path("kd")))
        self.assertTrue(os.path.isfile(server.asset_path("tko")))
        self.assertGreater(state["kdRev"], 0)
        self.assertGreater(state["tkoRev"], 0)


if __name__ == "__main__":
    unittest.main()
