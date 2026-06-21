import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Window 2.15
import QtQuick.Particles 2.15
import QtQuick.Effects

ApplicationWindow {
    id: root
    width: 920
    height: 250
    minimumWidth: 450
    minimumHeight: 120
    visible: true
    visibility: Window.Windowed
    color: "transparent"
    title: "Box Timer (Output)"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    property bool editMode: false
    property bool showControls: true
    property bool qmlPreviewEnabled: backend ? backend.qmlPreviewEnabled : true
    property int gridSize: 5
    property int snapThreshold: 6
    property int topBarHeight: 32
    property real uiScale: backend ? backend.overlayUiScale : 1.0
    property var activeDragItem: null
    property var lastDragItem: null
    property var selectedItem: null
    property int overlayTopPad: 40
    property int overlayLeftPad: 50
    property int overlayPad: 60
    property real overlayLeftExtra: 0
    property bool topBarHover: false
    property var layoutHistory: []
    property var layoutHistoryJson: []
    property int historyIndex: -1
    property bool historyBusy: false
    property int historyMax: 30
    property string profileMenuSide: "blue"
    property bool tekkenPreset: backend && backend.overlayPreset === "tekken8"
    property real _tekkenBlueShakeX: 0
    property real _tekkenBlueShakeY: 0
    property real _tekkenRedShakeX: 0
    property real _tekkenRedShakeY: 0
    property real _tekkenBlueFlash: 0
    property real _tekkenRedFlash: 0
    property real _tekkenKoOpacity: 0
    property real _tekkenKoScale: 0.8
    property real _tekkenKoY: -180
    property real _tekkenKoShakeX: 0
    property real _tekkenKoFlash: 0
    property real _tekkenKoLineScale: 0
    property real _tekkenKoRot: -3
    property string _tekkenKoText: ""
    property real _tekkenIntroOpacity: 0
    property real _tekkenIntroScale: 0.9
    property string _tekkenIntroText: ""
    property string _tekkenIntroSubText: ""
    property real _tekkenVsOpacity: 0
    property real _tekkenVsScale: 0.9
    property real _tekkenVsFlash: 0
    property real _tekkenVsShakeX: 0
    property real _tekkenVsShakeY: 0
    property real _tekkenVsBlueX: -620
    property real _tekkenVsRedX: 620
    property real _tekkenVsBlueRot: -8
    property real _tekkenVsRedRot: 8
    property real _tekkenVsNameY: 80
    property real _tekkenVsStageY: 110
    property string _tekkenVsKey: ""
    property string _tekkenRoundIntroKey: ""
    property real _tekkenBlueComboX: -180
    property real _tekkenRedComboX: 180
    property real _tekkenBlueComboScale: 1
    property real _tekkenRedComboScale: 1
    property real _tekkenBlueComboShakeX: 0
    property real _tekkenBlueComboShakeY: 0
    property real _tekkenRedComboShakeX: 0
    property real _tekkenRedComboShakeY: 0
    property real _tekkenBlueComboRot: 0
    property real _tekkenRedComboRot: 0
    property real _tekkenBlueRecentScale: 1
    property real _tekkenRedRecentScale: 1
    property real _tekkenBlueRecentShakeX: 0
    property real _tekkenBlueRecentShakeY: 0
    property real _tekkenRedRecentShakeX: 0
    property real _tekkenRedRecentShakeY: 0
    property real _tekkenBlueRecentRot: 0
    property real _tekkenRedRecentRot: 0
    property bool _tekkenBlueComboVisible: false
    property bool _tekkenRedComboVisible: false
    property bool _tekkenBlueRecentVisible: false
    property bool _tekkenRedRecentVisible: false
    property bool mainCaptureFullscreen: tekkenPreset && backend && backend.overlayShowCinematic

    function clamp01(v) {
        return Math.max(0.0, Math.min(1.0, Number(v) || 0.0))
    }

    function maybeStartTekkenVsIntro() {
        if (!root.tekkenPreset || !backend || !backend.overlayShowCinematic)
            return
        var key = String(backend.blueName || "") + "\u001f" + String(backend.redName || "")
        if (key === "\u001f" || key === root._tekkenVsKey)
            return
        root._tekkenVsKey = key
        backend.press_vs_intro_backspace()
        tekkenVsIntroAnim.restart()
    }

    function maybeStartTekkenRoundIntro(force) {
        if (!root.tekkenPreset || !backend || !backend.overlayShowCinematic)
            return
        var key = String(backend.roundText || "")
        if (key === "" || (!force && key === root._tekkenRoundIntroKey))
            return
        root._tekkenRoundIntroKey = key
        root._tekkenIntroText = root.tekkenRoundTitle(key)
        root._tekkenIntroSubText = "READY"
        tekkenRoundIntroAnim.restart()
    }

    function tekkenRoundTitle(raw) {
        var s = String(raw || "")
        var m = s.match(/RD\s*(\d+)/i)
        if (m && m.length > 1)
            return "ROUND " + m[1]
        return s.replace("\n", " ").toUpperCase()
    }

    function tekkenKoIsTko() {
        return String(root._tekkenKoText || "").indexOf("TECHNICAL") >= 0
    }

    function tekkenKoDisplayText() {
        return root.tekkenKoIsTko() ? "TECHNICAL\nKNOCKOUT" : root._tekkenKoText
    }

    function tekkenKoFontSize() {
        return root.tekkenKoIsTko()
            ? Math.max(22, Math.min(39, root.width / 43.0))
            : Math.max(27, Math.min(48, root.width / 31.0))
    }

    function tekkenKoPanelWidth(parentWidth) {
        return root.tekkenKoIsTko()
            ? Math.min(parentWidth * 0.29, 380)
            : Math.min(parentWidth * 0.22, 310)
    }

    function hpBaseRatio(side) {
        var l = side === "blue" ? (backend ? backend.bluePunishmentLong : 0) : (backend ? backend.redPunishmentLong : 0)
        return clamp01((100.0 - l) / 100.0)
    }

    function hpCurrentRatio(side) {
        var m = side === "blue" ? (backend ? backend.bluePunishmentMid : 0) : (backend ? backend.redPunishmentMid : 0)
        return clamp01(hpBaseRatio(side) * (1.0 - clamp01(m / 100.0)))
    }

    function hpGhostRatio(side) {
        return Math.max(0.0, hpBaseRatio(side) - hpCurrentRatio(side))
    }

    function hpBarColor(side) {
        var hp = hpCurrentRatio(side)
        if (hp <= 0.25) return "#ef4444"
        if (hp <= 0.55) return "#14b8a6"
        return "#22c55e"
    }

    function hpMidDamageColor(side) {
        return side === "blue" ? "#f97316" : "#fb923c"
    }

    function spRatio(side) {
        return clamp01(side === "blue" ? (backend ? backend.blueSpRatio : 1.0) : (backend ? backend.redSpRatio : 1.0))
    }

    function tekkenRecentRaw(side) {
        if (!backend)
            return ""
        return side === "blue" ? String(backend.blueRecentHitText || "") : String(backend.redRecentHitText || "")
    }

    function tekkenRecentDamage(side) {
        var s = tekkenRecentRaw(side).split("\n")[0]
        var matches = s.match(/\d+(?:\.\d+)?/g)
        return matches && matches.length > 0 ? Number(matches[matches.length - 1]) : 0
    }

    function tekkenRecentHasWeakPoint(side) {
        var s = tekkenRecentRaw(side)
        var parts = s.split("\n")
        return parts.length > 1 && String(parts[1] || "").replace(/^\s+|\s+$/g, "") !== ""
    }

    function tekkenRecentImpactScore(side) {
        var damage = tekkenRecentDamage(side)
        return damage * (tekkenRecentHasWeakPoint(side) ? 1.2 : 1.0)
    }

    function tekkenRecentColor(side) {
        var score = tekkenRecentImpactScore(side)
        if (score >= 60) return "#ff3b30"
        if (score >= 45) return "#ff8a00"
        if (score >= 30) return "#ffd84d"
        if (score >= 18) return "#8be9ff"
        return "#f8fafc"
    }

    function tekkenRecentOutline(side) {
        var score = tekkenRecentImpactScore(side)
        if (score >= 60) return "#4c0519"
        if (score >= 45) return "#7c2d12"
        if (score >= 30) return "#713f12"
        if (score >= 18) return "#083344"
        return "#020617"
    }

    function matchPairSize(kind, mode) {
        var a = (kind === "img") ? blueImgBox : blueNameBox
        var b = (kind === "img") ? redImgBox : redNameBox
        var w = a.width
        var h = a.height
        if (mode === "max") {
            w = Math.max(a.width, b.width)
            h = Math.max(a.height, b.height)
        } else if (mode === "min") {
            w = Math.min(a.width, b.width)
            h = Math.min(a.height, b.height)
        } else if (mode === "blue") {
            w = a.width
            h = a.height
        } else if (mode === "red") {
            w = b.width
            h = b.height
        }
        a.width = w; a.height = h
        b.width = w; b.height = h
        saveLayout()
    }

    function moveSelected(dx, dy) {
        if (!editMode || !selectedItem) return
        var nx = selectedItem.x + dx
        var ny = selectedItem.y + dy
        var p = {x: nx, y: ny}
        selectedItem.x = p.x
        selectedItem.y = p.y
        if (selectedItem.isCustom && selectedItem.modelIndex !== undefined) {
            customModel.setProperty(selectedItem.modelIndex, "x", selectedItem.x)
            customModel.setProperty(selectedItem.modelIndex, "y", selectedItem.y)
        }
        saveLayout()
    }

    property url flameTex: Qt.resolvedUrl("image/effects/flame.png")
    property url smokeTex: Qt.resolvedUrl("image/effects/smoke.png")
    property url sparkTex: Qt.resolvedUrl("image/effects/spark.png")
    property url flameParticleTex: ""
    property url glowParticleTex: ""
    property var effectCfg: backend ? backend.effectSettings : {}

    Canvas {
        id: flameParticleCanvas
        width: 64
        height: 96
        visible: false
        renderTarget: Canvas.Image
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var w = width
            var h = height
            var cx = w * 0.5
            var g = ctx.createLinearGradient(0, h, 0, 0)
            g.addColorStop(0.0, "rgba(255,255,255,1.0)")
            g.addColorStop(0.45, "rgba(255,255,255,0.75)")
            g.addColorStop(0.75, "rgba(255,255,255,0.35)")
            g.addColorStop(1.0, "rgba(255,255,255,0.0)")
            ctx.fillStyle = g
            ctx.beginPath()
            ctx.moveTo(cx, h * 0.98)
            ctx.quadraticCurveTo(w * 0.08, h * 0.7, cx, h * 0.04)
            ctx.quadraticCurveTo(w * 0.92, h * 0.7, cx, h * 0.98)
            ctx.closePath()
            ctx.fill()
            var g2 = ctx.createRadialGradient(cx, h * 0.82, 0, cx, h * 0.82, w * 0.22)
            g2.addColorStop(0.0, "rgba(255,255,255,0.9)")
            g2.addColorStop(0.8, "rgba(255,255,255,0.0)")
            ctx.fillStyle = g2
            ctx.beginPath()
            ctx.arc(cx, h * 0.82, w * 0.22, 0, Math.PI * 2)
            ctx.closePath()
            ctx.fill()
            root.flameParticleTex = flameParticleCanvas.toDataURL("image/png")
        }
        Component.onCompleted: flameParticleCanvas.requestPaint()
    }

    Canvas {
        id: glowParticleCanvas
        width: 96
        height: 96
        visible: false
        renderTarget: Canvas.Image
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var cx = width * 0.5
            var cy = height * 0.5
            var r = Math.min(width, height) * 0.5
            var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r)
            g.addColorStop(0.0, "rgba(255,255,255,0.8)")
            g.addColorStop(0.5, "rgba(255,255,255,0.4)")
            g.addColorStop(0.85, "rgba(255,255,255,0.15)")
            g.addColorStop(1.0, "rgba(255,255,255,0.0)")
            ctx.fillStyle = g
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, Math.PI * 2)
            ctx.closePath()
            ctx.fill()
            root.glowParticleTex = glowParticleCanvas.toDataURL("image/png")
        }
        Component.onCompleted: glowParticleCanvas.requestPaint()
    }

    ListModel {
        id: customModel
    }

    Rectangle {
        anchors.fill: parent
        color: backend ? backend.overlayBgColor : "transparent"
        opacity: backend ? backend.overlayBgOpacity : 0.0
        z: -10
    }

    property int _lastBlueStreak: 0
    property int _lastRedStreak: 0
    property real _blueFailOpacity: 0.0
    property real _redFailOpacity: 0.0
    property real _blueFailFlash: 0.0
    property real _redFailFlash: 0.0
    property real _blueStunFlash: 0.0
    property real _redStunFlash: 0.0
    property real _blueKdOverlay: 0.0
    property real _redKdOverlay: 0.0
    property real _blueTkoOverlay: 0.0
    property real _redTkoOverlay: 0.0
    property real _blueHitFlash: 0.0
    property real _redHitFlash: 0.0
    property real _blueHeavyImpact: 0.0
    property real _redHeavyImpact: 0.0
    property real _blueKoBurst: 0.0
    property real _redKoBurst: 0.0
    property real _blueHitDamage: 0.0
    property real _redHitDamage: 0.0
    property real _blueHpDownOverlay: 0.0
    property real _redHpDownOverlay: 0.0
    property real _blueHpDownStripe: 0.0
    property real _redHpDownStripe: 0.0
    property string _blueHpDownLabel: ""
    property string _redHpDownLabel: ""
    property string _blueImpactLabel: ""
    property string _redImpactLabel: ""
    property var _blueFailLines: []
    property var _redFailLines: []

    function _makeCracks(w, h) {
        var lines = []
        var count = 14
        for (var i = 0; i < count; i++) {
            var x = Math.random() * w
            var y = Math.random() * h
            var segs = 10
            var pts = []
            pts.push({x: x, y: y})
            for (var s = 0; s < segs; s++) {
                x += (Math.random() - 0.5) * w * 0.26
                y += (Math.random() - 0.4) * h * 0.26
                pts.push({x: Math.max(0, Math.min(w, x)), y: Math.max(0, Math.min(h, y))})
            }
            lines.push(pts)
        }
        return lines
    }

    function triggerFailEffect(side) {
        if (!root.qmlPreviewEnabled || !root._cfg("fail.enabled", true)) return
        if (side === "blue") {
            _blueFailLines = _makeCracks(blueImgBox.width, blueImgBox.height)
            blueFailCanvas.requestPaint()
            blueFailAnim.restart()
        } else if (side === "red") {
            _redFailLines = _makeCracks(redImgBox.width, redImgBox.height)
            redFailCanvas.requestPaint()
            redFailAnim.restart()
        }
        if (root._cfg("fail.sfx_enabled", false)) {
            var p = root._cfg("fail.sfx_path", "")
            if (p) backend.play_fail_sfx(p)
        }
    }
    Connections {
        target: backend
        function onOverlayPresetChanged() {
            root.tekkenPreset = backend && backend.overlayPreset === "tekken8"
            root.scheduleBoundsUpdate()
        }
        function onOverlayShowCinematicChanged() {
            if (!backend || !backend.overlayShowCinematic) {
                root._tekkenKoOpacity = 0
                root._tekkenIntroOpacity = 0
                root._tekkenVsOpacity = 0
            }
        }
        function onOverlayUiScaleChanged() {
            root.uiScale = backend ? backend.overlayUiScale : root.uiScale
            root.scheduleBoundsUpdate()
        }
        function onBlueWinStreakChanged() {
            if (!root.qmlPreviewEnabled) { root._lastBlueStreak = backend.blueWinStreak; return }
            if (backend.blueWinStreak > root._lastBlueStreak) {
                root.triggerWinTextPulse("blue")
            }
            if (backend.blueWinStreak < root._lastBlueStreak && root._lastBlueStreak > 0) {
                if (backend.winChangeReason === "score" && backend.winChangeSide === "red") {
                    root.triggerFailEffect("blue")
                }
            }
            if (backend.blueWinStreak > root._lastBlueStreak && root.isBurstMilestone(backend.blueWinStreak)) {
                blueBurstAnim.restart()
                if (root._cfg("burst.sfx_enabled", false)) {
                    var p = root._cfg("burst.sfx_path", "")
                    if (p) backend.play_burst_sfx(p)
                }
            }
            root._lastBlueStreak = backend.blueWinStreak
        }
        function onRedWinStreakChanged() {
            if (!root.qmlPreviewEnabled) { root._lastRedStreak = backend.redWinStreak; return }
            if (backend.redWinStreak > root._lastRedStreak) {
                root.triggerWinTextPulse("red")
            }
            if (backend.redWinStreak < root._lastRedStreak && root._lastRedStreak > 0) {
                if (backend.winChangeReason === "score" && backend.winChangeSide === "blue") {
                    root.triggerFailEffect("red")
                }
            }
            if (backend.redWinStreak > root._lastRedStreak && root.isBurstMilestone(backend.redWinStreak)) {
                redBurstAnim.restart()
                if (root._cfg("burst.sfx_enabled", false)) {
                    var p = root._cfg("burst.sfx_path", "")
                    if (p) backend.play_burst_sfx(p)
                }
            }
            root._lastRedStreak = backend.redWinStreak
        }
        function onStunFlashRequested(side) {
            if (!root.qmlPreviewEnabled) return
            if (side === "blue") {
                blueStunFlashAnim.restart()
                tekkenBlueStunAnim.restart()
            } else if (side === "red") {
                redStunFlashAnim.restart()
                tekkenRedStunAnim.restart()
            }
        }
        function onSpectatorEffectRequested(side, kind) {
            if (!root.qmlPreviewEnabled) return
            if (kind === "stun") {
                if (side === "blue") { blueStunFlashAnim.restart(); tekkenBlueStunAnim.restart() }
                else if (side === "red") { redStunFlashAnim.restart(); tekkenRedStunAnim.restart() }
            } else if (kind === "knockdown") {
                if (backend && backend.overlayShowCinematic) {
                    root._tekkenKoText = "KNOCK DOWN"
                    tekkenKoAnim.restart()
                }
                if (side === "blue") {
                    root._blueImpactLabel = "KD"
                    root._blueHpDownLabel = "KD"
                    blueKdAnim.restart()
                    blueHpDownAnim.restart()
                } else if (side === "red") {
                    root._redImpactLabel = "KD"
                    root._redHpDownLabel = "KD"
                    redKdAnim.restart()
                    redHpDownAnim.restart()
                }
            } else if (kind === "tko") {
                if (backend && backend.overlayShowCinematic) {
                    root._tekkenKoText = "TECHNICAL KNOCKOUT"
                    tekkenKoAnim.restart()
                }
                if (side === "blue") {
                    root._blueImpactLabel = "TKO"
                    root._blueHpDownLabel = "TKO"
                    blueTkoAnim.restart()
                    blueHpTkoAnim.restart()
                } else if (side === "red") {
                    root._redImpactLabel = "TKO"
                    root._redHpDownLabel = "TKO"
                    redTkoAnim.restart()
                    redHpTkoAnim.restart()
                }
            }
        }
        function onHitImpactRequested(side, damage) {
            if (!root.qmlPreviewEnabled) return
            if (side === "blue") {
                root._blueHitDamage = damage
                blueHitImpactAnim.restart()
                tekkenBlueHitAnim.restart()
                if (damage >= 45) blueHeavyImpactAnim.restart()
            } else if (side === "red") {
                root._redHitDamage = damage
                redHitImpactAnim.restart()
                tekkenRedHitAnim.restart()
                if (damage >= 45) redHeavyImpactAnim.restart()
            }
        }
    }

    SequentialAnimation {
        id: blueStunFlashAnim
        ScriptAction { script: root._blueStunFlash = 1.0 }
        PauseAnimation { duration: 70 }
        NumberAnimation { target: root; property: "_blueStunFlash"; to: 0.82; duration: 90; easing.type: Easing.OutQuad }
        PauseAnimation { duration: 1350 }
        NumberAnimation { target: root; property: "_blueStunFlash"; to: 0.0; duration: 260; easing.type: Easing.OutQuad }
    }
    SequentialAnimation {
        id: redStunFlashAnim
        ScriptAction { script: root._redStunFlash = 1.0 }
        PauseAnimation { duration: 70 }
        NumberAnimation { target: root; property: "_redStunFlash"; to: 0.82; duration: 90; easing.type: Easing.OutQuad }
        PauseAnimation { duration: 1350 }
        NumberAnimation { target: root; property: "_redStunFlash"; to: 0.0; duration: 260; easing.type: Easing.OutQuad }
    }
    SequentialAnimation {
        id: blueKdAnim
        ScriptAction { script: root._blueKoBurst = 1.0 }
        NumberAnimation { target: root; property: "_blueKdOverlay"; from: 0.0; to: 0.78; duration: 120 }
        PauseAnimation { duration: 1450 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_blueKdOverlay"; to: 0.0; duration: 320 }
            NumberAnimation { target: root; property: "_blueKoBurst"; to: 0.0; duration: 460 }
        }
        ScriptAction { script: root._blueImpactLabel = "" }
    }
    SequentialAnimation {
        id: redKdAnim
        ScriptAction { script: root._redKoBurst = 1.0 }
        NumberAnimation { target: root; property: "_redKdOverlay"; from: 0.0; to: 0.78; duration: 120 }
        PauseAnimation { duration: 1450 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_redKdOverlay"; to: 0.0; duration: 320 }
            NumberAnimation { target: root; property: "_redKoBurst"; to: 0.0; duration: 460 }
        }
        ScriptAction { script: root._redImpactLabel = "" }
    }
    SequentialAnimation {
        id: blueTkoAnim
        ScriptAction { script: root._blueKoBurst = 1.0 }
        NumberAnimation { target: root; property: "_blueTkoOverlay"; from: 0.0; to: 0.92; duration: 150 }
        PauseAnimation { duration: 2600 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_blueTkoOverlay"; to: 0.0; duration: 520 }
            NumberAnimation { target: root; property: "_blueKoBurst"; to: 0.0; duration: 760 }
        }
        ScriptAction { script: root._blueImpactLabel = "" }
    }
    SequentialAnimation {
        id: redTkoAnim
        ScriptAction { script: root._redKoBurst = 1.0 }
        NumberAnimation { target: root; property: "_redTkoOverlay"; from: 0.0; to: 0.92; duration: 150 }
        PauseAnimation { duration: 2600 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_redTkoOverlay"; to: 0.0; duration: 520 }
            NumberAnimation { target: root; property: "_redKoBurst"; to: 0.0; duration: 760 }
        }
        ScriptAction { script: root._redImpactLabel = "" }
    }
    SequentialAnimation {
        id: blueHpDownAnim
        ParallelAnimation {
            NumberAnimation { target: root; property: "_blueHpDownOverlay"; from: 0.0; to: 1.0; duration: 110 }
            NumberAnimation { target: root; property: "_blueHpDownStripe"; from: 0.0; to: 1.0; duration: 520; loops: 3 }
        }
        PauseAnimation { duration: 5200 }
        NumberAnimation { target: root; property: "_blueHpDownOverlay"; to: 0.0; duration: 260 }
        ScriptAction { script: root._blueHpDownLabel = "" }
    }
    SequentialAnimation {
        id: redHpDownAnim
        ParallelAnimation {
            NumberAnimation { target: root; property: "_redHpDownOverlay"; from: 0.0; to: 1.0; duration: 110 }
            NumberAnimation { target: root; property: "_redHpDownStripe"; from: 0.0; to: 1.0; duration: 520; loops: 3 }
        }
        PauseAnimation { duration: 5200 }
        NumberAnimation { target: root; property: "_redHpDownOverlay"; to: 0.0; duration: 260 }
        ScriptAction { script: root._redHpDownLabel = "" }
    }
    SequentialAnimation {
        id: blueHpTkoAnim
        ParallelAnimation {
            NumberAnimation { target: root; property: "_blueHpDownOverlay"; from: 0.0; to: 1.0; duration: 130 }
            NumberAnimation { target: root; property: "_blueHpDownStripe"; from: 0.0; to: 1.0; duration: 620; loops: 5 }
        }
        PauseAnimation { duration: 12000 }
        NumberAnimation { target: root; property: "_blueHpDownOverlay"; to: 0.0; duration: 420 }
        ScriptAction { script: root._blueHpDownLabel = "" }
    }
    SequentialAnimation {
        id: redHpTkoAnim
        ParallelAnimation {
            NumberAnimation { target: root; property: "_redHpDownOverlay"; from: 0.0; to: 1.0; duration: 130 }
            NumberAnimation { target: root; property: "_redHpDownStripe"; from: 0.0; to: 1.0; duration: 620; loops: 5 }
        }
        PauseAnimation { duration: 12000 }
        NumberAnimation { target: root; property: "_redHpDownOverlay"; to: 0.0; duration: 420 }
        ScriptAction { script: root._redHpDownLabel = "" }
    }
    SequentialAnimation {
        id: blueHitImpactAnim
        NumberAnimation { target: root; property: "_blueHitFlash"; from: 0.0; to: 0.82; duration: 45 }
        ParallelAnimation {
            SequentialAnimation {
                NumberAnimation { target: blueImgBox; property: "jitterX"; from: -7; to: 7; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterX"; from: 7; to: -5; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterX"; from: -5; to: 4; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterX"; to: 0; duration: 60 }
            }
            SequentialAnimation {
                NumberAnimation { target: blueImgBox; property: "jitterY"; from: 4; to: -4; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterY"; from: -4; to: 3; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterY"; from: 3; to: -2; duration: 42 }
                NumberAnimation { target: blueImgBox; property: "jitterY"; to: 0; duration: 60 }
            }
            NumberAnimation { target: root; property: "_blueHitFlash"; to: 0.0; duration: 230 }
        }
    }
    SequentialAnimation {
        id: redHitImpactAnim
        NumberAnimation { target: root; property: "_redHitFlash"; from: 0.0; to: 0.82; duration: 45 }
        ParallelAnimation {
            SequentialAnimation {
                NumberAnimation { target: redImgBox; property: "jitterX"; from: 7; to: -7; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterX"; from: -7; to: 5; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterX"; from: 5; to: -4; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterX"; to: 0; duration: 60 }
            }
            SequentialAnimation {
                NumberAnimation { target: redImgBox; property: "jitterY"; from: 4; to: -4; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterY"; from: -4; to: 3; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterY"; from: 3; to: -2; duration: 42 }
                NumberAnimation { target: redImgBox; property: "jitterY"; to: 0; duration: 60 }
            }
            NumberAnimation { target: root; property: "_redHitFlash"; to: 0.0; duration: 230 }
        }
    }
    SequentialAnimation {
        id: blueHeavyImpactAnim
        ScriptAction { script: root._blueHeavyImpact = 1.0 }
        PauseAnimation { duration: 70 }
        NumberAnimation { target: root; property: "_blueHeavyImpact"; to: 0.0; duration: 360; easing.type: Easing.OutQuad }
    }
    SequentialAnimation {
        id: redHeavyImpactAnim
        ScriptAction { script: root._redHeavyImpact = 1.0 }
        PauseAnimation { duration: 70 }
        NumberAnimation { target: root; property: "_redHeavyImpact"; to: 0.0; duration: 360; easing.type: Easing.OutQuad }
    }

    function snapValue(v, grid) {
        return Math.round(v / grid) * grid
    }

    function winTextSize(boxH) {
        return Math.max(_cfg("win_text.size_min", 11), Math.min(boxH * _cfg("win_text.size_scale", 0.18), _cfg("win_text.size_max", 18)))
    }

    function _cfg(path, defVal) {
        var obj = effectCfg
        if (!obj) return defVal
        var parts = path.split(".")
        for (var i = 0; i < parts.length; i++) {
            var key = parts[i]
            if (obj === null || obj === undefined || !(key in obj)) return defVal
            obj = obj[key]
        }
        return (obj === undefined || obj === null) ? defVal : obj
    }

    function _aura(path, defVal) {
        return _cfg("aura." + path, defVal)
    }

    function _nameplatePath(streak) {
        if (!_cfg("nameplates.enabled", true)) return ""
        var ms = _cfg("nameplates.milestones", [3, 6, 9, 12, 16, 21, 30])
        var imgs = _cfg("nameplates.images", [])
        if (!ms || ms.length === undefined) return ""
        var best = ""
        for (var i = 0; i < ms.length; i++) {
            var m = parseInt(ms[i] || 0)
            if (!m) continue
            if (streak >= m) {
                if (imgs && imgs.length > i && imgs[i]) {
                    best = imgs[i]
                }
            }
        }
        return best
    }

    function _playerId(side) {
        if (!backend) return ""
        return side === "red" ? backend.redPlayerId : backend.bluePlayerId
    }

    function _playerRegistered(side) {
        if (!backend) return false
        return side === "red" ? backend.redPlayerRegistered : backend.bluePlayerRegistered
    }

    function _playerValid(side) {
        if (!backend) return false
        return side === "red" ? backend.redPlayerValid : backend.bluePlayerValid
    }

    function _burstMilestones() {
        var ms = _cfg("burst.milestones", [3, 6, 9, 12, 16, 21, 30])
        if (!ms || ms.length === undefined) return [3, 6, 9, 12, 16, 21, 30]
        return ms
    }

    function isBurstMilestone(streak) {
        var ms = _burstMilestones()
        var n = parseInt(streak || 0)
        for (var i = 0; i < ms.length; i++) {
            if (parseInt(ms[i]) === n) return true
        }
        return false
    }

    function triggerWinTextPulse(side) {
        if (side === "blue") {
            if (blueWinTextPulse) blueWinTextPulse.restart()
        } else if (side === "red") {
            if (redWinTextPulse) redWinTextPulse.restart()
        }
    }

    function showProfileMenu(side, gx, gy) {
        profileMenuSide = side
        profileMenu.x = Math.max(6, Math.min(gx, root.width - profileMenu.width - 6))
        profileMenu.y = Math.max(topBarHeight + 6, Math.min(gy, root.height - profileMenu.height - 6))
        profileMenu.visible = true
    }

    function placeMenu(menuItem, btn) {
        if (!menuItem || !btn) return
        var p = btn.mapToItem(root.contentItem, 0, 0)
        menuItem.x = Math.max(6, Math.min(p.x, root.width - menuItem.width - 6))
        menuItem.y = Math.max(topBarHeight + 2, Math.min(p.y + btn.height + 2, root.height - menuItem.height - 6))
    }

    function _stageFor(streak) {
        var stages = _cfg("stages", [])
        var best = null
        var bestMin = -1
        for (var i = 0; i < stages.length; i++) {
            var s = stages[i]
            if (!s) continue
            var min = parseInt(s.min || 0)
            if (streak >= min && min >= bestMin) {
                best = s
                bestMin = min
            }
        }
        return best
    }

    function snapPos(item, x, y) {
        var sx = x
        var sy = y
        var snappedX = false
        var snappedY = false
        var items = _snapItems()
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it || it === item || !it.visible) continue
            if (Math.abs((x) - it.x) <= snapThreshold) { sx = it.x; snappedX = true }
            if (Math.abs((x) - (it.x + it.width)) <= snapThreshold) { sx = it.x + it.width; snappedX = true }
            if (Math.abs((x + item.width) - it.x) <= snapThreshold) { sx = it.x - item.width; snappedX = true }
            if (Math.abs((y) - it.y) <= snapThreshold) { sy = it.y; snappedY = true }
            if (Math.abs((y) - (it.y + it.height)) <= snapThreshold) { sy = it.y + it.height; snappedY = true }
            if (Math.abs((y + item.height) - it.y) <= snapThreshold) { sy = it.y - item.height; snappedY = true }
        }
        if (!snappedX) sx = snapValue(x, gridSize)
        if (!snappedY) sy = snapValue(y, gridSize)
        for (var pass = 0; pass < 2; pass++) {
            for (var j = 0; j < items.length; j++) {
                var it2 = items[j]
                if (!it2 || it2 === item || !it2.visible) continue
                var ax1 = sx
                var ay1 = sy
                var ax2 = sx + item.width
                var ay2 = sy + item.height
                var bx1 = it2.x
                var by1 = it2.y
                var bx2 = it2.x + it2.width
                var by2 = it2.y + it2.height
                if (!_rectOverlap(ax1, ax2, bx1, bx2) || !_rectOverlap(ay1, ay2, by1, by2)) continue
                var candidates = [
                    {x: it2.x - item.width, y: sy},
                    {x: it2.x + it2.width, y: sy},
                    {x: sx, y: it2.y - item.height},
                    {x: sx, y: it2.y + it2.height}
                ]
                var best = null
                var bestDist = 1e9
                for (var c = 0; c < candidates.length; c++) {
                    var cand = candidates[c]
                    var cx1 = cand.x
                    var cy1 = cand.y
                    var cx2 = cand.x + item.width
                    var cy2 = cand.y + item.height
                    if (_rectOverlap(cx1, cx2, bx1, bx2) && _rectOverlap(cy1, cy2, by1, by2)) continue
                    if (cand.y < topBarHeight + 2) continue
                    var dist = Math.abs(cand.x - sx) + Math.abs(cand.y - sy)
                    if (dist < bestDist) {
                        bestDist = dist
                        best = cand
                    }
                }
                if (best) {
                    sx = best.x
                    sy = best.y
                }
            }
        }
        if (sy < topBarHeight + 2) sy = topBarHeight + 2
        return {x: sx, y: sy}
    }

    function clampY(v) {
        return Math.max(v, topBarHeight + 2)
    }

    function _rectOverlap(a1, a2, b1, b2) {
        return (a1 < b2) && (a2 > b1)
    }

    function _isConnected(a, b) {
        if (!a || !b || a === b) return false
        var ax2 = a.x + a.width
        var ay2 = a.y + a.height
        var bx2 = b.x + b.width
        var by2 = b.y + b.height
        if (_rectOverlap(a.x, ax2, b.x, bx2) && _rectOverlap(a.y, ay2, b.y, by2)) return true
        var t = groupThreshold
        if (Math.abs(ax2 - b.x) <= t && _rectOverlap(a.y, ay2, b.y, by2)) return true
        if (Math.abs(bx2 - a.x) <= t && _rectOverlap(a.y, ay2, b.y, by2)) return true
        if (Math.abs(ay2 - b.y) <= t && _rectOverlap(a.x, ax2, b.x, bx2)) return true
        if (Math.abs(by2 - a.y) <= t && _rectOverlap(a.x, ax2, b.x, bx2)) return true
        return false
    }

    function _touchingSide(item, side) {
        var items = _snapItems()
        var ax2 = item.x + item.width
        var ay2 = item.y + item.height
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it || it === item || !it.visible) continue
            if (it.noOverlapFade) continue
            var bx2 = it.x + it.width
            var by2 = it.y + it.height
            if (side === "right" && Math.abs(ax2 - it.x) <= snapThreshold && _rectOverlap(item.y, ay2, it.y, by2)) return true
            if (side === "left" && Math.abs(bx2 - item.x) <= snapThreshold && _rectOverlap(item.y, ay2, it.y, by2)) return true
            if (side === "bottom" && Math.abs(ay2 - it.y) <= snapThreshold && _rectOverlap(item.x, ax2, it.x, bx2)) return true
            if (side === "top" && Math.abs(by2 - item.y) <= snapThreshold && _rectOverlap(item.x, ax2, it.x, bx2)) return true
        }
        return false
    }

    function _isOverlapping(item) {
        if (!item || item.noOverlapFade) return false
        if (root.activeDragItem !== item && root.lastDragItem !== item) return false
        var items = _snapItems()
        var ax2 = item.x + item.width
        var ay2 = item.y + item.height
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it || it === item || !it.visible) continue
            if (it.noOverlapFade) continue
            var bx2 = it.x + it.width
            var by2 = it.y + it.height
            if (_rectOverlap(item.x, ax2, it.x, bx2) && _rectOverlap(item.y, ay2, it.y, by2)) return true
        }
        return false
    }

    function _overlapTarget(item) {
        if (!item || item.noOverlapFade) return null
        var items = _snapItems()
        var idxItem = -1
        for (var k = 0; k < items.length; k++) {
            if (items[k] === item) { idxItem = k; break }
        }
        if (idxItem < 0) return null
        var best = null
        var bestArea = 0
        var ax1 = item.x
        var ay1 = item.y
        var ax2 = item.x + item.width
        var ay2 = item.y + item.height
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it || it === item || !it.visible) continue
            if (it.noOverlapFade) continue
            if (i >= idxItem) continue
            var bx1 = it.x
            var by1 = it.y
            var bx2 = it.x + it.width
            var by2 = it.y + it.height
            if (!_rectOverlap(ax1, ax2, bx1, bx2) || !_rectOverlap(ay1, ay2, by1, by2)) continue
            var ix1 = Math.max(ax1, bx1)
            var iy1 = Math.max(ay1, by1)
            var ix2 = Math.min(ax2, bx2)
            var iy2 = Math.min(ay2, by2)
            var area = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1)
            if (area > bestArea) {
                bestArea = area
                best = it
            }
        }
        return best
    }

    function _touchingTarget(item) {
        if (!item || item.noOverlapFade) return null
        var items = _snapItems()
        var idxItem = -1
        for (var k = 0; k < items.length; k++) {
            if (items[k] === item) { idxItem = k; break }
        }
        if (idxItem < 0) return null
        var best = null
        var bestLen = 0
        var ax1 = item.x
        var ay1 = item.y
        var ax2 = item.x + item.width
        var ay2 = item.y + item.height
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it || it === item || !it.visible) continue
            if (it.noOverlapFade) continue
            if (i >= idxItem) continue
            var bx1 = it.x
            var by1 = it.y
            var bx2 = it.x + it.width
            var by2 = it.y + it.height
            var hOverlap = Math.max(0, Math.min(ax2, bx2) - Math.max(ax1, bx1))
            var vOverlap = Math.max(0, Math.min(ay2, by2) - Math.max(ay1, by1))
            if (Math.abs(ax2 - bx1) <= snapThreshold && vOverlap > 0 && vOverlap > bestLen) {
                bestLen = vOverlap
                best = it
            } else if (Math.abs(bx2 - ax1) <= snapThreshold && vOverlap > 0 && vOverlap > bestLen) {
                bestLen = vOverlap
                best = it
            } else if (Math.abs(ay2 - by1) <= snapThreshold && hOverlap > 0 && hOverlap > bestLen) {
                bestLen = hOverlap
                best = it
            } else if (Math.abs(by2 - ay1) <= snapThreshold && hOverlap > 0 && hOverlap > bestLen) {
                bestLen = hOverlap
                best = it
            }
        }
        return best
    }

    function _matchTarget(item) {
        var t = _overlapTarget(item)
        if (!t) t = _touchingTarget(item)
        return t
    }

    function _matchBg(item, color) {
        if (!item || item.noOverlapFade) return color
        var target = _matchTarget(item)
        if (target && target.color) return target.color
        return color
    }

    function _matchBorder(item, color) {
        if (!item || item.noOverlapFade) return color
        var target = _matchTarget(item)
        if (target && target.borderCol !== undefined) return target.borderCol
        if (target && target.border && target.border.color) return target.border.color
        return color
    }

    function _matchRadius(item, baseRadius) {
        if (!item) return baseRadius
        var touching = _touchingSide(item, "left")
            || _touchingSide(item, "right")
            || _touchingSide(item, "top")
            || _touchingSide(item, "bottom")
        return touching ? 0 : baseRadius
    }

    function auraLevel(streak) {
        var stages = _cfg("stages", [])
        var best = _stageFor(streak)
        if (!best) return 0
        var idx = stages.indexOf(best)
        return idx >= 0 ? idx + 1 : 1
    }

    function auraColorFor(streak) {
        var s = _stageFor(streak)
        return s && s.color ? s.color : "transparent"
    }

    function auraBorderColor(baseColor) {
        var c = _cfg("aura.border_color", "")
        return c && c.length > 0 ? c : baseColor
    }

    function auraOpacityFor(streak) {
        var s = _stageFor(streak)
        return s && s.opacity !== undefined ? s.opacity : 0.0
    }

    function auraPulseFor(streak) {
        var s = _stageFor(streak)
        return s && s.pulse !== undefined ? s.pulse : 1.0
    }

    function styleFor(key) {
        if (!backend) return {}
        var s = backend.overlayStyle
        if (!s || typeof s !== 'object') return {}
        return s[key] || {}
    }

    function styleVal(key, field, defVal) {
        var obj = styleFor(key)
        var val = obj[field]
        return (val !== undefined && val !== null) ? val : defVal
    }

    function styleColor(key, field, defColor, opacityField, defOpacity) {
        var c = styleVal(key, field, defColor)
        var o = (defOpacity !== undefined) ? defOpacity : 1.0
        if (opacityField) {
            o = styleVal(key, opacityField, o)
        }
        var qc = Qt.color(c)
        return Qt.rgba(qc.r, qc.g, qc.b, Math.max(0, Math.min(1, o)))
    }

    function styleFontSize(key, defSize) {
        var v = parseInt(styleVal(key, "font_size", 0))
        return v > 0 ? v : defSize
    }

    function winText(count) {
        var fmt = _cfg("win_text.format", "W{n}")
        return fmt.replace("{n}", count)
    }

    function _defaultCustomElement() {
        return {
            id: "",
            x: 20,
            y: topBarHeight + 8,
            w: 160,
            h: 48,
            text: "CUSTOM",
            visible: true,
            bg_color: "#1f2937",
            bg_opacity: 0.85,
            border_color: "#111827",
            border_opacity: 1.0,
            border_width: 2,
            text_color: "#ffffff",
            text_opacity: 1.0,
            font_family: "Bahnschrift",
            font_size: 0,
            font_bold: true,
            font_weight: 700
        }
    }

    function _normalizeCustomElement(raw) {
        var base = _defaultCustomElement()
        if (!raw) return base
        for (var k in raw) {
            base[k] = raw[k]
        }
        if (!base.id || base.id.length === 0) {
            base.id = "custom_" + Date.now().toString(36) + "_" + Math.floor(Math.random() * 1000000).toString(36)
        }
        base.x = parseInt(base.x || 0)
        base.y = clampY(parseInt(base.y || (topBarHeight + 8)))
        base.w = Math.max(30, parseInt(base.w || 160))
        base.h = Math.max(20, parseInt(base.h || 48))
        base.visible = (base.visible === undefined) ? true : !!base.visible
        return base
    }

    function setCustomElements(list) {
        customModel.clear()
        if (!list || list.length === 0) return
        for (var i = 0; i < list.length; i++) {
            var e = _normalizeCustomElement(list[i])
            customModel.append(e)
        }
    }

    function addCustomElement(x, y, w, h, text) {
        var e = _defaultCustomElement()
        e.id = "custom_" + Date.now().toString(36) + "_" + Math.floor(Math.random() * 1000000).toString(36)
        e.x = snapValue(x, gridSize)
        e.y = clampY(snapValue(y, gridSize))
        e.w = Math.max(30, snapValue(w, gridSize))
        e.h = Math.max(20, snapValue(h, gridSize))
        if (text && text.length > 0) e.text = text
        customModel.append(e)
        saveLayout()
    }

    function findCustomItemById(customId) {
        if (!customId || !customLayer) return null
        for (var i = 0; i < customLayer.children.length; i++) {
            var it = customLayer.children[i]
            if (it && it.isCustom && it.model && it.model.id === customId) return it
        }
        return null
    }

    function duplicateCustomElement(modelIndex) {
        if (modelIndex === undefined || modelIndex < 0 || modelIndex >= customModel.count) return null
        var src = customModel.get(modelIndex)
        if (!src) return null
        var copy = _normalizeCustomElement(src)
        copy.id = "custom_" + Date.now().toString(36) + "_" + Math.floor(Math.random() * 1000000).toString(36)
        copy.x = snapValue((src.x || 0) + gridSize * 2, gridSize)
        copy.y = clampY(snapValue((src.y || 0) + gridSize * 2, gridSize))
        customModel.append(copy)
        var newIndex = customModel.count - 1
        var item = findCustomItemById(copy.id)
        if (item) {
            root.selectedItem = item
            root.lastDragItem = item
        }
        return {
            index: newIndex,
            id: copy.id,
            item: item
        }
    }

    function deleteSelectedItem() {
        if (!editMode || !selectedItem || !selectedItem.isCustom) return false
        if (selectedItem.modelIndex === undefined || selectedItem.modelIndex < 0 || selectedItem.modelIndex >= customModel.count) return false
        pushHistory()
        customModel.remove(selectedItem.modelIndex, 1)
        root.activeDragItem = null
        root.lastDragItem = null
        root.selectedItem = null
        saveLayout()
        return true
    }

    function _snapItems() {
        var items = [roundBox, timeBox, blueImgBox, blueNameBox, redImgBox, redNameBox, arenaNameBox]
        if (customLayer) {
            for (var i = 0; i < customLayer.children.length; i++) {
                var it = customLayer.children[i]
                if (it && it.isSnapItem) items.push(it)
            }
        }
        return items
    }

    function _boundsItems() {
        var items = _snapItems()
        if (typeof blueNameplate !== "undefined") items.push(blueNameplate)
        if (typeof redNameplate !== "undefined") items.push(redNameplate)
        if (typeof blueDamageBadge !== "undefined") items.push(blueDamageBadge)
        if (typeof redDamageBadge !== "undefined") items.push(redDamageBadge)
        if (typeof bluePunishmentBadge !== "undefined") items.push(bluePunishmentBadge)
        if (typeof redPunishmentBadge !== "undefined") items.push(redPunishmentBadge)
        if (typeof blueKnockdownDots !== "undefined") items.push(blueKnockdownDots)
        if (typeof redKnockdownDots !== "undefined") items.push(redKnockdownDots)
        if (typeof spectatorMatchBadge !== "undefined") items.push(spectatorMatchBadge)
        if (typeof spectatorRecentHitBadge !== "undefined") items.push(spectatorRecentHitBadge)
        if (typeof blueRecentHitBadge !== "undefined") items.push(blueRecentHitBadge)
        if (typeof redRecentHitBadge !== "undefined") items.push(redRecentHitBadge)
        return items
    }

    function _reserveNameplateSpace(plate) {
        if (!plate) return false
        if (!_cfg("nameplates.enabled", true)) return false
        var imgs = _cfg("nameplates.images", [])
        return imgs && imgs.length !== undefined && imgs.length > 0
    }

    function updateWindowBounds() {
        if (root.tekkenPreset) {
            if (root.mainCaptureFullscreen) {
                root.width = Screen.width
                root.height = Screen.height
                overlayLeftExtra = 0
                return
            }
            var minW2 = 1180
            if (showControls) {
                var bw = (topBarRow ? topBarRow.implicitWidth : 0)
                var rw = (topBarRightControls ? topBarRightControls.implicitWidth : 0)
                minW2 = Math.max(minW2, bw + rw + 80)
            }
            root.width = Math.ceil(minW2 * uiScale)
            root.height = Math.ceil(255 * uiScale)
            overlayLeftExtra = 0
            return
        }
        var items = _boundsItems()
        var minX = 0
        var maxX = 0
        var maxY = topBarHeight
        var pad = overlayPad
        for (var i = 0; i < items.length; i++) {
            var it = items[i]
            if (!it) continue
            var reserveInvisible = (it === blueNameplate || it === redNameplate) && _reserveNameplateSpace(it)
            if (!it.visible && !reserveInvisible) continue
            minX = Math.min(minX, it.x)
            maxX = Math.max(maxX, it.x + it.width)
            maxY = Math.max(maxY, it.y + it.height)
        }
        overlayLeftExtra = Math.max(0, -minX + pad)
        var minW = 450
        if (showControls) {
            // Ensure space for the top bar row content + right side controls
            var topBarButtonsW = (topBarRow ? topBarRow.implicitWidth : 0)
            var topBarRightW = (topBarRightControls ? topBarRightControls.implicitWidth : 0)
            minW = Math.max(minW, topBarButtonsW + topBarRightW + 60)
        }
        root.width = Math.max(minW, Math.ceil((maxX + pad + overlayLeftPad + overlayLeftExtra) * uiScale))
        root.height = Math.max(120, Math.ceil((maxY + pad + overlayTopPad) * uiScale))
    }


    onEditModeChanged: {
        if (editMode) {
            showControls = true
        }
    }

    function scheduleBoundsUpdate() {
        boundsTimer.restart()
    }

    Timer {
        id: boundsTimer
        interval: 60
        repeat: false
        running: false
        onTriggered: updateWindowBounds()
    }

    function applyLayout(l) {
        if (!l) { return }
        root.activeDragItem = null
        root.lastDragItem = null
        root.selectedItem = null
        if (l.visibility && backend) {
            if ("round" in l.visibility) backend.set_overlay_visible("round", !!l.visibility.round)
            if ("time" in l.visibility) backend.set_overlay_visible("time", !!l.visibility.time)
            if ("blue_img" in l.visibility) backend.set_overlay_visible("blue_img", !!l.visibility.blue_img)
            if ("blue_name" in l.visibility) backend.set_overlay_visible("blue_name", !!l.visibility.blue_name)
            if ("red_img" in l.visibility) backend.set_overlay_visible("red_img", !!l.visibility.red_img)
            if ("red_name" in l.visibility) backend.set_overlay_visible("red_name", !!l.visibility.red_name)
            if ("arena_name" in l.visibility) backend.set_overlay_visible("arena_name", !!l.visibility.arena_name)
        }
        if (l.custom_elements) {
            setCustomElements(l.custom_elements)
        } else if (l.custom) {
            setCustomElements(l.custom)
        } else {
            setCustomElements([])
        }
        if (l.round) {
            roundBox.x = l.round.x
            roundBox.y = clampY(l.round.y)
            roundBox.width = l.round.w
            roundBox.height = l.round.h
        }
        if (l.time) {
            timeBox.x = l.time.x
            timeBox.y = clampY(l.time.y)
            timeBox.width = l.time.w
            timeBox.height = l.time.h
        }
        if (l.blue_img) {
            blueImgBox.x = l.blue_img.x
            blueImgBox.y = clampY(l.blue_img.y)
            blueImgBox.width = l.blue_img.w
            blueImgBox.height = l.blue_img.h
        }
        if (l.blue_name) {
            blueNameBox.x = l.blue_name.x
            blueNameBox.y = clampY(l.blue_name.y)
            blueNameBox.width = l.blue_name.w
            blueNameBox.height = l.blue_name.h
        }
        if (l.red_img) {
            redImgBox.x = l.red_img.x
            redImgBox.y = clampY(l.red_img.y)
            redImgBox.width = l.red_img.w
            redImgBox.height = l.red_img.h
        }
        if (l.red_name) {
            redNameBox.x = l.red_name.x
            redNameBox.y = clampY(l.red_name.y)
            redNameBox.width = l.red_name.w
            redNameBox.height = l.red_name.h
        }
        if (l.arena_name) {
            arenaNameBox.x = l.arena_name.x
            arenaNameBox.y = clampY(l.arena_name.y)
            arenaNameBox.width = l.arena_name.w
            arenaNameBox.height = l.arena_name.h
        }
        updateWindowBounds()
    }

    onShowControlsChanged: scheduleBoundsUpdate()

    function collectLayout() {
        var customs = []
        for (var i = 0; i < customModel.count; i++) {
            var e = customModel.get(i)
            customs.push({
                id: e.id,
                x: e.x, y: e.y, w: e.w, h: e.h,
                text: e.text,
                visible: e.visible,
                bg_color: e.bg_color,
                bg_opacity: e.bg_opacity,
                border_color: e.border_color,
                border_opacity: e.border_opacity,
                border_width: e.border_width,
                text_color: e.text_color,
                text_opacity: e.text_opacity,
                font_family: e.font_family,
                font_size: e.font_size,
                font_bold: e.font_bold,
                font_weight: e.font_weight
            })
        }
        return {
            visibility: {
                round: backend ? backend.overlayShowRound : true,
                time: backend ? backend.overlayShowTime : true,
                blue_img: backend ? backend.overlayShowBlueImg : true,
                blue_name: backend ? backend.overlayShowBlueName : true,
                red_img: backend ? backend.overlayShowRedImg : true,
                red_name: backend ? backend.overlayShowRedName : true,
                arena_name: backend ? backend.overlayShowArenaName : true
            },
            round: {x: roundBox.x, y: roundBox.y, w: roundBox.width, h: roundBox.height},
            time: {x: timeBox.x, y: timeBox.y, w: timeBox.width, h: timeBox.height},
            blue_img: {x: blueImgBox.x, y: blueImgBox.y, w: blueImgBox.width, h: blueImgBox.height},
            blue_name: {x: blueNameBox.x, y: blueNameBox.y, w: blueNameBox.width, h: blueNameBox.height},
            red_img: {x: redImgBox.x, y: redImgBox.y, w: redImgBox.width, h: redImgBox.height},
            red_name: {x: redNameBox.x, y: redNameBox.y, w: redNameBox.width, h: redNameBox.height},
            arena_name: {x: arenaNameBox.x, y: arenaNameBox.y, w: arenaNameBox.width, h: arenaNameBox.height},
            custom_elements: customs
        }
    }

    function pushHistory() {
        if (historyBusy) return
        var snap = collectLayout()
        var s = JSON.stringify(snap)
        if (historyIndex >= 0 && layoutHistoryJson[historyIndex] === s) return
        if (historyIndex < layoutHistory.length - 1) {
            layoutHistory = layoutHistory.slice(0, historyIndex + 1)
            layoutHistoryJson = layoutHistoryJson.slice(0, historyIndex + 1)
        }
        layoutHistory.push(snap)
        layoutHistoryJson.push(s)
        historyIndex = layoutHistory.length - 1
        if (layoutHistory.length > historyMax) {
            layoutHistory.shift()
            layoutHistoryJson.shift()
            historyIndex = layoutHistory.length - 1
        }
    }

    function startHistory() {
        layoutHistory = []
        layoutHistoryJson = []
        historyIndex = -1
        pushHistory()
    }

    function undoLayout() {
        if (historyIndex <= 0) return
        historyIndex -= 1
        historyBusy = true
        applyLayout(layoutHistory[historyIndex])
        saveLayout()
        historyBusy = false
    }

    function saveLayout() {
        updateWindowBounds()
        if (!layoutApi) { return }
        if (editMode && !historyBusy) {
            pushHistory()
        }
        layoutApi.saveLayout(collectLayout())
    }

    onClosing: function(close) {
        saveLayout()
    }

    Component.onCompleted: {
        if (layoutApi) {
            var l = layoutApi.loadLayout()
            if (l && Object.keys(l).length > 0) {
                applyLayout(l)
                return
            }
        }
        applyLayout({
            round: {x: 10, y: 10, w: 130, h: 130},
            time: {x: 150, y: 10, w: 200, h: 130},
            blue_img: {x: 360, y: 10, w: 96, h: 96},
            blue_name: {x: 470, y: 10, w: 280, h: 60},
            red_img: {x: 360, y: 110, w: 96, h: 96},
            red_name: {x: 470, y: 110, w: 280, h: 60},
            arena_name: {x: 470, y: 78, w: 280, h: 28}
        })
    }

    Rectangle {
        id: topBar
        parent: root
        width: root.width
        height: topBarHeight
        anchors.left: parent.left
        anchors.top: parent.top
        color: "transparent"
        z: 3000
        visible: true
        opacity: 1.0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            z: -1
            onEntered: root.topBarHover = true
            onExited: root.topBarHover = false
        }
        Column {
            id: topBarRightControls
            anchors.right: parent.right
            anchors.rightMargin: 150
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            z: 5
            visible: true

            Row {
                spacing: 6
                visible: true
                Text {
                    id: scaleLabel
                    text: "\uD06C\uAE30"
                    width: 38
                    color: "#e5e7eb"
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                }
                Slider {
                    id: scaleSlider
                    hoverEnabled: true
                    from: 0.5
                    to: 2.0
                    value: root.uiScale
                    width: 92
                    height: 16
                    ToolTip.visible: hovered
                    ToolTip.text: "UI \uC804\uCCB4 \uD06C\uAE30"
                    onValueChanged: {
                        if (!pressed) {
                            if (backend) {
                                backend.setOverlayUiScale(value)
                            } else {
                                root.uiScale = value
                                root.scheduleBoundsUpdate()
                            }
                        }
                    }
                    onPressedChanged: {
                        if (!pressed) {
                            if (backend) {
                                backend.setOverlayUiScale(value)
                            } else {
                                root.uiScale = value
                                root.scheduleBoundsUpdate()
                            }
                        }
                    }
                }
            }

            Row {
                spacing: 6
                visible: true
                Text {
                    id: bgOpacityLabel
                    text: "\uD22C\uBA85\uB3C4"
                    width: 38
                    color: "#e5e7eb"
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                }
                Slider {
                    id: bgOpacitySlider
                    hoverEnabled: true
                    from: 0.0
                    to: 1.0
                    value: backend ? backend.overlayBgOpacity : 0.85
                    width: 92
                    height: 16
                    ToolTip.visible: hovered
                ToolTip.text: "\uBC30\uACBD \uD22C\uBA85\uB3C4 (\uC67C\uCABD=\uBD88\uD22C\uBA85, \uC624\uB978\uCABD=\uD22C\uBA85)"
                    onValueChanged: {
                        if (!pressed && backend) {
                            backend.setOverlayBgOpacity(value)
                        }
                    }
                    onPressedChanged: {
                        if (!pressed && backend) {
                            backend.setOverlayBgOpacity(value)
                        }
                    }
                }
            }
        }

        Flickable {
            id: topBarLeftFlickable
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.right: topBarRightControls.left
            anchors.rightMargin: 12
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            contentWidth: topBarRow.width
            flickableDirection: Flickable.HorizontalFlick
            interactive: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Row {
                id: topBarRow
                spacing: 6
                anchors.verticalCenter: parent.verticalCenter
            Button {
                text: "\uBA54\uB274"
                width: 44
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#1f1f1f"; radius: 4 }
                onClicked: showControls = true
                ToolTip.visible: hovered
                ToolTip.text: "\uC0C1\uB2E8 \uB3C4\uAD6C \uD45C\uC2DC/\uC228\uAE40"
            }
            Button {
                text: "\uC124\uC815"
                width: 52
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#1f1f1f"; radius: 4 }
                onClicked: { if (backend) backend.open_settings() }
                visible: true
                ToolTip.visible: hovered
                ToolTip.text: "\uC124\uC815\uCC3D \uC5F4\uAE30"
            }
            Button {
                text: "\uC5C5\uB370\uC774\uD2B8"
                width: 68
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#1f1f1f"; radius: 4 }
                onClicked: { if (backend) backend.check_updates() }
                visible: true
                ToolTip.visible: hovered
                ToolTip.text: "\uC0C8 \uBC84\uC804 \uD655\uC778"
            }
            Button {
                text: "\uBC29\uC1A1\uB3D9\uAE30\uD654"
                width: 84
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#0f766e"; radius: 4 }
                onClicked: { if (backend) backend.toggle_chapter_sync() }
                visible: true
                ToolTip.visible: hovered
                ToolTip.text: "\uD074\uB9AD: \uB3D9\uAE30\uD654 ON / \uB2E4\uC2DC \uD074\uB9AD: OFF(\uAE30\uC900 \uD574\uC81C)"
            }
            Rectangle {
                width: syncOnText.implicitWidth + 14
                height: 22
                radius: 11
                color: "#16a34a"
                border.color: "#14532d"
                border.width: 1
                visible: backend && backend.broadcastSyncActive
                Text {
                    id: syncOnText
                    anchors.centerIn: parent
                    text: "\uB3D9\uAE30\uD654 ON"
                    color: "#ffffff"
                    font.pixelSize: 11
                    font.bold: true
                }
            }
            Button {
                text: "\uC7AC\uC0DD \uC911\uC9C0"
                width: 94
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#b91c1c"; radius: 4 }
                onClicked: { if (backend) backend.stop_hud_demo() }
                visible: backend && backend.hudDemoRunning
                ToolTip.visible: hovered
                ToolTip.text: "\uC9C4\uD589 \uC911\uC778 HUD \uB370\uBAA8/\uACFC\uAC70 \uB85C\uADF8 \uB9AC\uD50C\uB808\uC774 \uC911\uC9C0"
            }
            Item {
                width: 62
                height: 26
                Button {
                    id: btnActionsMenu
                    anchors.fill: parent
                    text: "\uC791\uC5C5"
                    hoverEnabled: true
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle { color: "#2a2a2a"; radius: 4 }
                    onClicked: {
                        actionsMenu.visible = !actionsMenu.visible
                        if (actionsMenu.visible) placeMenu(actionsMenu, btnActionsMenu)
                        editMenu.visible = false
                        detectMenu.visible = false
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: "\uC791\uC5C5 \uBA54\uB274"
                }
                visible: true
            }
            Item {
                width: 74
                height: 26
                Button {
                    id: btnEditMenu
                    anchors.fill: parent
                    text: "UI\uD3B8\uC9D1"
                    hoverEnabled: true
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle { color: editMode ? "#ef4444" : "#2a2a2a"; radius: 4 }
                    onClicked: {
                        editMenu.visible = !editMenu.visible
                        if (editMenu.visible) placeMenu(editMenu, btnEditMenu)
                        if (!editMenu.visible) { imgSizeMenu.visible = false; nameSizeMenu.visible = false }
                        actionsMenu.visible = false
                        detectMenu.visible = false
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: "UI \uD3B8\uC9D1 \uBA54\uB274"
                }
                visible: true
            }
            Item {
                width: 62
                height: 26
                Button {
                    id: btnDetectMenu
                    anchors.fill: parent
                    text: "\uAC10\uC9C0"
                    hoverEnabled: true
                    contentItem: Text {
                        text: parent.text
                        color: "#ffffff"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                    }
                    background: Rectangle { color: "#2a2a2a"; radius: 4 }
                    onClicked: {
                        detectMenu.visible = !detectMenu.visible
                        if (detectMenu.visible) placeMenu(detectMenu, btnDetectMenu)
                        editMenu.visible = false
                        actionsMenu.visible = false
                    }
                    ToolTip.visible: hovered
                    ToolTip.text: "\uAC10\uC9C0 \uBA54\uB274"
                }
                visible: true
            }
            Button {
                text: "\uC885\uB8CC"
                width: 52
                height: 26
                hoverEnabled: true
                contentItem: Text {
                    text: parent.text
                    color: "#ffffff"
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                background: Rectangle { color: "#2a2a2a"; radius: 4 }
                onClicked: {
                    if (backend) backend.export_chapter_txt()
                    Qt.quit()
                }
                visible: true
                ToolTip.visible: hovered
                ToolTip.text: "\uD504\uB85C\uADF8\uB7A8 \uC885\uB8CC"
            }
            Rectangle {
                height: 26
                radius: 4
                color: "#111827"
                border.color: "#2a2a2a"
                border.width: 1
                visible: backend && (backend.statusText && backend.statusText.length > 0)
                Text {
                    anchors.centerIn: parent
                    text: backend ? backend.statusText : ""
                    color: "#e5e7eb"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
            }
        }
        // Removed legacy standalone controls moved to topBarRightControls Row
    }

    // hideMenu removed; visibility toggles are handled in edit mode on elements

    Rectangle {
        id: topBarHoverZone
        parent: root
        x: 0
        y: 0
        width: (showControls || root.tekkenPreset) ? parent.width : 360
        height: (showControls || root.tekkenPreset) ? (topBarHeight + 10) : 64
        color: "transparent"
        z: 3001
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            propagateComposedEvents: true
            onEntered: root.topBarHover = true
            onExited: root.topBarHover = false
        }
    }

    Rectangle {
        id: miniDockHoverZone
        parent: root
        anchors.right: parent.right
        anchors.top: parent.top
        width: 120
        height: 52
        color: "transparent"
        z: 3001
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            propagateComposedEvents: true
            onEntered: root.topBarHover = true
            onExited: root.topBarHover = false
        }
    }

    Rectangle {
        id: miniDock
        parent: root
        z: 1205
        width: 74
        height: 28
        radius: 6
        color: "#101418"
        border.color: "#2c3444"
        border.width: 1
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.top: parent.top
        anchors.topMargin: 8
        visible: !editMode && (showControls || topBarHover)
        opacity: miniHover.containsMouse ? 1.0 : 0.82

        MouseArea {
            id: miniHover
            anchors.fill: parent
            hoverEnabled: true
            onClicked: {
                root.showControls = false
                root.topBarHover = false
                root.showMinimized()
            }
        }
        Text {
            anchors.centerIn: parent
            text: "\uCD5C\uC18C\uD654"
            color: "#ffffff"
            font.pixelSize: 12
        }
    }

    Rectangle {
        id: editMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2000
        width: 180
        x: 0
        y: 0
        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: editMode ? "UI\uD3B8\uC9D1 \uC644\uB8CC" : "UI\uD3B8\uC9D1 \uC2DC\uC791"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        editMode = !editMode
                        if (!editMode) {
                            saveLayout()
                        } else {
                            startHistory()
                            keyFocus.forceActiveFocus()
                        }
                        editMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: (editMode && historyIndex > 0) ? "#2a2a2a" : "#1f1f1f"
                opacity: (editMode && historyIndex > 0) ? 1.0 : 0.6
                Text { anchors.centerIn: parent; text: "\uB418\uB3CC\uB9AC\uAE30"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    enabled: editMode && historyIndex > 0
                    onClicked: {
                        undoLayout()
                        editMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "\uCD08\uC0C1\uD654 \uD06C\uAE30 \uB9DE\uCD94\uAE30"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        imgSizeMenu.visible = !imgSizeMenu.visible
                        nameSizeMenu.visible = false
                        imgSizeMenu.x = Math.max(6, Math.min(editMenu.x + editMenu.width + 4, root.width - imgSizeMenu.width - 6))
                        imgSizeMenu.y = Math.max(topBarHeight + 2, Math.min(editMenu.y + 56, root.height - imgSizeMenu.height - 6))
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "\uC774\uB984 \uD06C\uAE30 \uB9DE\uCD94\uAE30"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        nameSizeMenu.visible = !nameSizeMenu.visible
                        imgSizeMenu.visible = false
                        nameSizeMenu.x = Math.max(6, Math.min(editMenu.x + editMenu.width + 4, root.width - nameSizeMenu.width - 6))
                        nameSizeMenu.y = Math.max(topBarHeight + 2, Math.min(editMenu.y + 82, root.height - nameSizeMenu.height - 6))
                    }
                }
            }
        }
    }

    Rectangle {
        id: imgSizeMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2000
        width: 120
        x: 0
        y: 0
        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4
            Repeater {
                model: [
                    {t: "\uD070\uCABD \uAE30\uC900", m: "max"},
                    {t: "\uC791\uC740\uCABD \uAE30\uC900", m: "min"},
                    {t: "\uBE14\uB8E8 \uAE30\uC900", m: "blue"},
                    {t: "\uB808\uB4DC \uAE30\uC900", m: "red"}
                ]
                delegate: Rectangle {
                    width: parent.width
                    height: 22
                    radius: 3
                    color: "#2a2a2a"
                    Text { anchors.centerIn: parent; text: modelData.t; color: "#ffffff"; font.pixelSize: 12 }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            matchPairSize("img", modelData.m)
                            imgSizeMenu.visible = false
                            editMenu.visible = false
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: nameSizeMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2000
        width: 120
        x: 0
        y: 0
        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4
            Repeater {
                model: [
                    {t: "\uD070\uCABD \uAE30\uC900", m: "max"},
                    {t: "\uC791\uC740\uCABD \uAE30\uC900", m: "min"},
                    {t: "\uBE14\uB8E8 \uAE30\uC900", m: "blue"},
                    {t: "\uB808\uB4DC \uAE30\uC900", m: "red"}
                ]
                delegate: Rectangle {
                    width: parent.width
                    height: 22
                    radius: 3
                    color: "#2a2a2a"
                    Text { anchors.centerIn: parent; text: modelData.t; color: "#ffffff"; font.pixelSize: 12 }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            matchPairSize("name", modelData.m)
                            nameSizeMenu.visible = false
                            editMenu.visible = false
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: actionsMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2000
        width: 170
        height: 134
        x: 0
        y: 0
        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: editMode ? "#1f1f1f" : "#2a2a2a"
                opacity: editMode ? 0.6 : 1.0
                Text { anchors.centerIn: parent; text: "\uD0C0\uC774\uBA38 \uCD08\uAE30\uD654"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    enabled: !editMode
                    onClicked: {
                        if (backend) backend.reset_timer()
                        actionsMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "\uD2B8\uB9AC\uAC70 \uD14C\uC2A4\uD2B8"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.test_trigger()
                        actionsMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "\uACFC\uAC70 \uB85C\uADF8 \uB9AC\uD50C\uB808\uC774"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.replay_spectator_last_log()
                        actionsMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "\uC804\uCCB4 HUD \uB370\uBAA8"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.test_spectator_full_demo()
                        actionsMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: "#2a2a2a"
                Text { anchors.centerIn: parent; text: "VS \uC624\uBC84\uB808\uC774 \uD14C\uC2A4\uD2B8"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.test_spectator_vs_intro()
                        actionsMenu.visible = false
                    }
                }
            }
        }
    }

    Rectangle {
        id: detectMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2000
        width: 130
        height: 82
        x: 0
        y: 0
        Column {
            anchors.fill: parent
            anchors.margins: 4
            spacing: 4
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: (backend && backend.logDetectRunning) ? "#ef4444" : "#2a2a2a"
                Text { anchors.centerIn: parent; text: (backend && backend.logDetectRunning) ? "\uB85C\uADF8 \uAC10\uC9C0 \uCF1C\uC9D0" : "\uB85C\uADF8 \uAC10\uC9C0"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.toggle_log_detection()
                        detectMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: (backend && backend.ocrDetectRunning) ? "#ef4444" : "#2a2a2a"
                Text { anchors.centerIn: parent; text: (backend && backend.ocrDetectRunning) ? "\u004F\u0043\u0052 \uAC10\uC9C0 \uCF1C\uC9D0" : "\u004F\u0043\u0052 \uAC10\uC9C0"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.toggle_ocr_detection()
                        detectMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 22
                radius: 3
                color: (backend && backend.pixelDetectRunning) ? "#ef4444" : "#2a2a2a"
                Text { anchors.centerIn: parent; text: (backend && backend.pixelDetectRunning) ? "\uD53D\uC140 \uAC10\uC9C0 \uCF1C\uC9D0" : "\uD53D\uC140 \uAC10\uC9C0"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    onClicked: {
                        if (backend) backend.toggle_pixel_detection()
                        detectMenu.visible = false
                    }
                }
            }
        }
    }

    Rectangle {
        id: profileMenu
        visible: false
        color: "#1c1c1c"
        radius: 4
        border.color: "#333"
        border.width: 1
        z: 2200
        width: 150
        Column {
            anchors.fill: parent
            anchors.margins: 6
            spacing: 6
            Text {
                text: _playerId(profileMenuSide) ? ("ID: " + _playerId(profileMenuSide)) : "ID: -"
                color: "#cbd5e1"
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            Rectangle {
                width: parent.width
                height: 24
                radius: 3
                color: !_playerRegistered(profileMenuSide) ? "#2563eb" : "#2a2a2a"
                opacity: !_playerRegistered(profileMenuSide) ? 1.0 : 0.45
                Text { anchors.centerIn: parent; text: "\uD504\uB85C\uD544 \uB4F1\uB85D"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    enabled: !_playerRegistered(profileMenuSide)
                    onClicked: {
                        if (backend) backend.open_profile_register(profileMenuSide)
                        profileMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 24
                radius: 3
                color: _playerValid(profileMenuSide) ? "#16a34a" : "#2a2a2a"
                opacity: _playerValid(profileMenuSide) ? 1.0 : 0.45
                Text { anchors.centerIn: parent; text: "\uD504\uB85C\uD544 \uC218\uC815"; color: "#ffffff"; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent
                    enabled: _playerValid(profileMenuSide)
                    onClicked: {
                        if (backend) backend.open_profile_edit(profileMenuSide)
                        profileMenu.visible = false
                    }
                }
            }
            Rectangle {
                width: parent.width
                height: 20
                radius: 3
                color: "#2a2a2a"
                opacity: _playerValid(profileMenuSide) ? 0.0 : 0.6
                visible: !_playerValid(profileMenuSide)
                Text { anchors.centerIn: parent; text: "OCR \uC544\uC774\uB514 \uC5C6\uC74C"; color: "#94a3b8"; font.pixelSize: 11 }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: !editMode
        acceptedButtons: Qt.LeftButton
        z: 0
        onPressed: function(mouse) {
            root.startSystemMove()
            mouse.accepted = false
        }
    }

    FocusScope {
        id: keyFocus
        anchors.fill: parent
        focus: true
        activeFocusOnTab: true
        Keys.onPressed: function(event) {
            if (!editMode) return
            if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_Z) {
                undoLayout()
                event.accepted = true
                return
            }
            if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) {
                if (deleteSelectedItem()) {
                    event.accepted = true
                }
                return
            }
            if (!selectedItem) return
            var step = (event.modifiers & Qt.ShiftModifier) ? gridSize * 5 : gridSize
            if (event.key === Qt.Key_Left) { moveSelected(-step, 0); event.accepted = true }
            else if (event.key === Qt.Key_Right) { moveSelected(step, 0); event.accepted = true }
            else if (event.key === Qt.Key_Up) { moveSelected(0, -step); event.accepted = true }
            else if (event.key === Qt.Key_Down) { moveSelected(0, step); event.accepted = true }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: editMenu.visible || imgSizeMenu.visible || nameSizeMenu.visible || profileMenu.visible || actionsMenu.visible || detectMenu.visible
        z: 1500
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: {
            editMenu.visible = false
            imgSizeMenu.visible = false
            nameSizeMenu.visible = false
            profileMenu.visible = false
            actionsMenu.visible = false
            detectMenu.visible = false
        }
    }

    Item {
        id: scaledRoot
        visible: !root.tekkenPreset
        scale: root.uiScale
        transformOrigin: Item.TopLeft
        width: root.width / root.uiScale
        height: root.height / root.uiScale
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.topMargin: overlayTopPad
        anchors.leftMargin: overlayLeftPad + overlayLeftExtra
    }

    Item {
        id: tekkenLayer
        visible: root.qmlPreviewEnabled && root.tekkenPreset
        scale: root.uiScale
        transformOrigin: Item.TopLeft
        width: root.width / Math.max(0.1, root.uiScale)
        height: root.height / Math.max(0.1, root.uiScale)
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.topMargin: overlayTopPad
        z: 80

        function sideName(side) {
            var v = side === "blue" ? (backend ? backend.blueName : "BLUE") : (backend ? backend.redName : "RED")
            if (!v || v === "") return side === "blue" ? "BLUE" : "RED"
            return v
        }
        function hpRatio(side) { return root.hpCurrentRatio(side) }
        function ghostRatio(side) { return root.hpGhostRatio(side) }
        function dmgText(side) {
            return side === "blue" ? (backend ? backend.blueDamageText : "DMG 0") : (backend ? backend.redDamageText : "DMG 0")
        }
        function recentText(side) {
            return side === "blue" ? (backend ? backend.blueRecentHitText : "") : (backend ? backend.redRecentHitText : "")
        }
        function comboHit(side) {
            return side === "blue" ? (backend ? backend.blueComboHitText : "") : (backend ? backend.redComboHitText : "")
        }
        function comboDamage(side) {
            return side === "blue" ? (backend ? backend.blueComboDamageText : "") : (backend ? backend.redComboDamageText : "")
        }
        function commaInt(n) {
            n = Math.max(0, Math.round(Number(n) || 0))
            var s = "" + n
            var out = ""
            while (s.length > 3) {
                out = "," + s.slice(s.length - 3) + out
                s = s.slice(0, s.length - 3)
            }
            return s + out
        }
        function totalDamageLabel(side) {
            var s = side === "blue" ? (backend ? backend.blueTotalDamageText : "0") : (backend ? backend.redTotalDamageText : "0")
            var m = String(s || "").match(/(\d+)/)
            var v = m ? parseInt(m[1]) : 0
            return "TOTAL DAMAGE  " + commaInt(v)
        }

        Rectangle {
            anchors.fill: parent
            color: "transparent"
        }

        Text {
            id: tekkenModeTitle
            anchors.horizontalCenter: parent.horizontalCenter
            y: 7
            text: backend ? backend.arenaName : "RFC"
            color: "#e5e7eb"
            opacity: text !== "" ? 0.65 : 0.0
            font.pixelSize: 12
            font.bold: true
            style: Text.Outline
            styleColor: "#05070b"
        }

        Rectangle {
            id: tekkenCenterPanel
            width: 150
            height: 90
            anchors.horizontalCenter: parent.horizontalCenter
            y: 0
            color: "transparent"
            border.width: 0
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: "transparent" }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 2
                text: backend ? backend.timeText : "3:00"
                color: "#2a0f12"
                opacity: 0.55
                font.pixelSize: 68
                font.bold: true
                style: Text.Outline
                styleColor: "#f8fafc"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                text: backend ? backend.timeText : "3:00"
                color: "#e8e1df"
                font.pixelSize: 68
                font.bold: true
                style: Text.Outline
                styleColor: "#4a1617"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 82
                width: 130
                text: backend ? backend.roundText : "RD 1"
                color: "#f8fafc"
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 14
                font.bold: true
                wrapMode: Text.NoWrap
                style: Text.Outline
                styleColor: "#020617"
            }
        }

        Item {
            id: tekkenBlueGroup
            x: 8 + root._tekkenBlueShakeX
            y: 0 + root._tekkenBlueShakeY
            width: 548
            height: 112

            Image {
                id: tekkenBluePortrait
                source: "image://players/blue?rev=" + (backend ? backend.blueImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                mipmap: false
                sourceSize.width: 768
                sourceSize.height: 768
                fillMode: Image.PreserveAspectFit
                width: 150
                height: 150
                x: 6
                y: -30
            }
            MouseArea {
                anchors.fill: tekkenBluePortrait
                enabled: !editMode
                acceptedButtons: Qt.RightButton
                z: 20
                onClicked: function(mouse) {
                    if (mouse.button === Qt.RightButton) {
                        var p = tekkenBluePortrait.mapToItem(root.contentItem, mouse.x, mouse.y)
                        showProfileMenu("blue", p.x, p.y)
                    }
                }
            }
            Text {
                x: 5
                y: 78
                width: 218
                text: tekkenLayer.sideName("blue")
                color: "#f8fafc"
                font.pixelSize: 19
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
                elide: Text.ElideRight
            }
            Text {
                x: 150
                y: 9
                text: tekkenLayer.totalDamageLabel("blue")
                color: "#dbeafe"
                font.pixelSize: 15
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
            }
            Item {
                id: tekkenBlueHp
                x: 154
                y: 28
                width: 338
                height: 38
                layer.enabled: true
                layer.smooth: true
                layer.samples: 4
                Canvas {
                    id: tekkenBlueHpCanvas
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var hp = tekkenLayer.hpRatio("blue")
                        var ghost = tekkenLayer.ghostRatio("blue")
                        var slant = 38
                        var top = 4.5
                        var bottom = height - 3.5
                        ctx.save()
                        ctx.shadowColor = "rgba(0,0,0,0.75)"
                        ctx.shadowBlur = 10
                        ctx.shadowOffsetY = 2
                        ctx.beginPath()
                        ctx.moveTo(0, top); ctx.lineTo(width - slant, top); ctx.lineTo(width, bottom); ctx.lineTo(slant, bottom); ctx.closePath()
                        ctx.fillStyle = "#05070b"; ctx.fill()
                        ctx.restore()

                        ctx.save()
                        ctx.beginPath()
                        ctx.moveTo(0, top); ctx.lineTo(width - slant, top); ctx.lineTo(width, bottom); ctx.lineTo(slant, bottom); ctx.closePath()
                        ctx.clip()
                        var bg = ctx.createLinearGradient(0, 0, 0, height)
                        bg.addColorStop(0, "#171c27"); bg.addColorStop(0.42, "#05070d"); bg.addColorStop(1, "#0b1020")
                        ctx.fillStyle = bg; ctx.fillRect(0, 0, width, height)
                        var sp = root.spRatio("blue")
                        ctx.fillStyle = "#071225"; ctx.fillRect(0, height - 8.5, width, 5.5)
                        var spGrad = ctx.createLinearGradient(0, 0, width, 0)
                        spGrad.addColorStop(0, "#dff6ff")
                        spGrad.addColorStop(0.32, "#38bdf8")
                        spGrad.addColorStop(0.72, "#2563eb")
                        spGrad.addColorStop(1, "#1e3a8a")
                        ctx.fillStyle = spGrad; ctx.fillRect(0, height - 8.5, width * sp, 5.5)
                        var g = ctx.createLinearGradient(0, 0, width, 0)
                        g.addColorStop(0, "#fffdf0"); g.addColorStop(0.18, "#fff2aa"); g.addColorStop(0.52, "#ffd45a"); g.addColorStop(0.78, "#f59e0b"); g.addColorStop(1, hp < 0.25 ? "#ef4444" : "#fb923c")
                        ctx.fillStyle = "rgba(255,255,255,0.14)"; ctx.fillRect(width * hp, 8.5, width * ghost, height - 19)
                        ctx.fillStyle = g; ctx.fillRect(0, 8.5, width * hp, height - 19)
                        var shine = ctx.createLinearGradient(0, 8, 0, height * 0.55)
                        shine.addColorStop(0, "rgba(255,255,255,0.72)"); shine.addColorStop(1, "rgba(255,255,255,0)")
                        ctx.fillStyle = shine; ctx.fillRect(10, 10, Math.max(0, width * hp - 20), 6)
                        ctx.fillStyle = "rgba(255,255,255,0.13)"; ctx.fillRect(0, 8.5, width, 2)
                        ctx.restore()

                        ctx.beginPath()
                        ctx.moveTo(0, top); ctx.lineTo(width - slant, top); ctx.lineTo(width, bottom); ctx.lineTo(slant, bottom); ctx.closePath()
                        ctx.strokeStyle = "#f8fafc"; ctx.lineWidth = 2.6; ctx.stroke()
                        ctx.beginPath()
                        ctx.moveTo(5, top + 3); ctx.lineTo(width - slant - 7, top + 3)
                        ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 1; ctx.stroke()
                    }
                    Connections {
                        target: backend
                        function onBluePunishmentMidChanged() { tekkenBlueHpCanvas.requestPaint() }
                        function onBluePunishmentLongChanged() { tekkenBlueHpCanvas.requestPaint() }
                        function onBlueSpRatioChanged() { tekkenBlueHpCanvas.requestPaint() }
                    }
                }
            }
            Item {
                x: 156
                y: 72
                width: 54
                height: 34
                visible: backend && backend.overlayShowFlags && backend.blueFlagSource !== ""
                Image {
                    anchors.fill: parent
                    source: backend ? backend.blueFlagSource : ""
                    cache: false
                    smooth: true
                    mipmap: true
                    fillMode: Image.PreserveAspectCrop
                }
            }
            Text {
                x: 13
                y: 108
                text: tekkenLayer.dmgText("blue")
                color: "#e5e7eb"
                font.pixelSize: 14
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
            }
            Row {
                x: 408
                y: 1
                spacing: 5
                Repeater {
                    model: 3
                    Item {
                        width: 22
                        height: 22
                        property bool filled: backend && index >= Math.min(3, backend.blueRoundKnockdowns)
                        layer.enabled: true
                        layer.smooth: true
                        layer.samples: 4
                        Canvas {
                            id: tekkenBlueKdDot
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                var cx = width / 2, cy = height / 2, r = Math.min(width, height) * 0.38
                                ctx.save()
                                ctx.shadowColor = parent.filled ? "rgba(255,196,64,0.72)" : "rgba(0,0,0,0.7)"
                                ctx.shadowBlur = parent.filled ? 8 : 4
                                var outer = ctx.createRadialGradient(cx - r * 0.25, cy - r * 0.35, r * 0.1, cx, cy, r * 1.28)
                                outer.addColorStop(0, parent.filled ? "#fff9d7" : "#667085")
                                outer.addColorStop(0.25, parent.filled ? "#d6a62d" : "#2f3744")
                                outer.addColorStop(0.72, parent.filled ? "#5a2b05" : "#05070c")
                                outer.addColorStop(1, parent.filled ? "#fff4c4" : "#1f2937")
                                ctx.fillStyle = outer
                                ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill()
                                var inner = ctx.createRadialGradient(cx - r * 0.28, cy - r * 0.34, 1, cx, cy, r * 0.86)
                                inner.addColorStop(0, parent.filled ? "#fffbe8" : "#111827")
                                inner.addColorStop(0.38, parent.filled ? "#ffd86a" : "#0b0f18")
                                inner.addColorStop(0.75, parent.filled ? "#c98712" : "#05070c")
                                inner.addColorStop(1, parent.filled ? "#4b2203" : "#02040a")
                                ctx.fillStyle = inner
                                ctx.beginPath(); ctx.arc(cx, cy, r * 0.72, 0, Math.PI * 2); ctx.fill()
                                ctx.strokeStyle = parent.filled ? "rgba(255,255,255,0.85)" : "rgba(203,213,225,0.35)"
                                ctx.lineWidth = 1.2
                                ctx.beginPath(); ctx.arc(cx, cy, r - 0.6, 0, Math.PI * 2); ctx.stroke()
                                ctx.restore()
                            }
                            Connections { target: backend; function onBlueRoundKnockdownsChanged() { tekkenBlueKdDot.requestPaint() } }
                            Component.onCompleted: requestPaint()
                        }
                    }
                }
            }
            Rectangle {
                anchors.fill: tekkenBluePortrait
                color: "white"
                opacity: root._tekkenBlueFlash
            }
            Rectangle {
                anchors.fill: tekkenBluePortrait
                color: "#facc15"
                opacity: root._blueHeavyImpact * 0.42
            }
            Rectangle {
                anchors.fill: tekkenBluePortrait
                color: "#020617"
                opacity: root._blueKoBurst * 0.68
            }
            Text {
                anchors.centerIn: tekkenBluePortrait
                text: root._blueTkoOverlay > root._blueKdOverlay ? "TKO" : "DOWN"
                visible: root.qmlPreviewEnabled && root._blueKoBurst > 0.01
                opacity: root._blueKoBurst
                scale: 0.85 + root._blueKoBurst * 0.35
                color: "#fef3c7"
                font.pixelSize: root._blueTkoOverlay > root._blueKdOverlay ? 31 : 24
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }
        }

        Item {
            id: tekkenRedGroup
            x: parent.width - width - 8 + root._tekkenRedShakeX
            y: 0 + root._tekkenRedShakeY
            width: 548
            height: 112

            Image {
                id: tekkenRedPortrait
                source: "image://players/red?rev=" + (backend ? backend.redImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                mipmap: false
                sourceSize.width: 768
                sourceSize.height: 768
                fillMode: Image.PreserveAspectFit
                width: 150
                height: 150
                x: parent.width - width - 18
                y: -30
                mirror: true
            }
            MouseArea {
                anchors.fill: tekkenRedPortrait
                enabled: !editMode
                acceptedButtons: Qt.RightButton
                z: 20
                onClicked: function(mouse) {
                    if (mouse.button === Qt.RightButton) {
                        var p = tekkenRedPortrait.mapToItem(root.contentItem, mouse.x, mouse.y)
                        showProfileMenu("red", p.x, p.y)
                    }
                }
            }
            Text {
                x: parent.width - width - 5
                y: 78
                width: 218
                text: tekkenLayer.sideName("red")
                color: "#f8fafc"
                font.pixelSize: 19
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
                horizontalAlignment: Text.AlignRight
                elide: Text.ElideRight
            }
            Text {
                x: parent.width - width - 150
                y: 9
                width: 260
                text: tekkenLayer.totalDamageLabel("red")
                color: "#fee2e2"
                horizontalAlignment: Text.AlignRight
                font.pixelSize: 15
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
            }
            Item {
                id: tekkenRedHp
                x: 56
                y: 28
                width: 338
                height: 38
                layer.enabled: true
                layer.smooth: true
                layer.samples: 4
                Canvas {
                    id: tekkenRedHpCanvas
                    anchors.fill: parent
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var hp = tekkenLayer.hpRatio("red")
                        var ghost = tekkenLayer.ghostRatio("red")
                        var slant = 38
                        var top = 4.5
                        var bottom = height - 3.5
                        ctx.save()
                        ctx.shadowColor = "rgba(0,0,0,0.75)"
                        ctx.shadowBlur = 10
                        ctx.shadowOffsetY = 2
                        ctx.beginPath()
                        ctx.moveTo(slant, top); ctx.lineTo(width, top); ctx.lineTo(width - slant, bottom); ctx.lineTo(0, bottom); ctx.closePath()
                        ctx.fillStyle = "#05070b"; ctx.fill()
                        ctx.restore()
                        var filledW = width * hp
                        var ghostW = width * ghost
                        ctx.save()
                        ctx.beginPath()
                        ctx.moveTo(slant, top); ctx.lineTo(width, top); ctx.lineTo(width - slant, bottom); ctx.lineTo(0, bottom); ctx.closePath()
                        ctx.clip()
                        var bg = ctx.createLinearGradient(0, 0, 0, height)
                        bg.addColorStop(0, "#171c27"); bg.addColorStop(0.42, "#05070d"); bg.addColorStop(1, "#0b1020")
                        ctx.fillStyle = bg; ctx.fillRect(0, 0, width, height)
                        var sp = root.spRatio("red")
                        var spW = width * sp
                        ctx.fillStyle = "#071225"; ctx.fillRect(0, height - 8.5, width, 5.5)
                        var spGrad = ctx.createLinearGradient(0, 0, width, 0)
                        spGrad.addColorStop(0, "#1e3a8a")
                        spGrad.addColorStop(0.28, "#2563eb")
                        spGrad.addColorStop(0.68, "#38bdf8")
                        spGrad.addColorStop(1, "#dff6ff")
                        ctx.fillStyle = spGrad; ctx.fillRect(width - spW, height - 8.5, spW, 5.5)
                        var g = ctx.createLinearGradient(0, 0, width, 0)
                        g.addColorStop(0, hp < 0.25 ? "#ef4444" : "#fb923c"); g.addColorStop(0.22, "#f59e0b"); g.addColorStop(0.48, "#ffd45a"); g.addColorStop(0.82, "#fff2aa"); g.addColorStop(1, "#fffdf0")
                        ctx.fillStyle = "rgba(255,255,255,0.14)"; ctx.fillRect(width - filledW - ghostW, 8.5, ghostW, height - 19)
                        ctx.fillStyle = g; ctx.fillRect(width - filledW, 8.5, filledW, height - 19)
                        var shine = ctx.createLinearGradient(0, 8, 0, height * 0.55)
                        shine.addColorStop(0, "rgba(255,255,255,0.72)"); shine.addColorStop(1, "rgba(255,255,255,0)")
                        ctx.fillStyle = shine; ctx.fillRect(width - filledW + 10, 10, Math.max(0, filledW - 20), 6)
                        ctx.fillStyle = "rgba(255,255,255,0.13)"; ctx.fillRect(0, 8.5, width, 2)
                        ctx.restore()

                        ctx.beginPath()
                        ctx.moveTo(slant, top); ctx.lineTo(width, top); ctx.lineTo(width - slant, bottom); ctx.lineTo(0, bottom); ctx.closePath()
                        ctx.strokeStyle = "#f8fafc"; ctx.lineWidth = 2.6; ctx.stroke()
                        ctx.beginPath()
                        ctx.moveTo(slant + 7, top + 3); ctx.lineTo(width - 5, top + 3)
                        ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 1; ctx.stroke()
                    }
                    Connections {
                        target: backend
                        function onRedPunishmentMidChanged() { tekkenRedHpCanvas.requestPaint() }
                        function onRedPunishmentLongChanged() { tekkenRedHpCanvas.requestPaint() }
                        function onRedSpRatioChanged() { tekkenRedHpCanvas.requestPaint() }
                    }
                }
            }
            Item {
                x: 338
                y: 72
                width: 54
                height: 34
                visible: backend && backend.overlayShowFlags && backend.redFlagSource !== ""
                Image {
                    anchors.fill: parent
                    source: backend ? backend.redFlagSource : ""
                    cache: false
                    smooth: true
                    mipmap: true
                    fillMode: Image.PreserveAspectCrop
                }
            }
            Text {
                x: parent.width - width - 13
                y: 108
                width: 140
                text: tekkenLayer.dmgText("red")
                color: "#e5e7eb"
                horizontalAlignment: Text.AlignRight
                font.pixelSize: 14
                font.bold: true
                style: Text.Outline
                styleColor: "#020617"
            }
            Row {
                x: 72
                y: 1
                spacing: 5
                layoutDirection: Qt.RightToLeft
                Repeater {
                    model: 3
                    Item {
                        width: 22
                        height: 22
                        property bool filled: backend && index >= Math.min(3, backend.redRoundKnockdowns)
                        layer.enabled: true
                        layer.smooth: true
                        layer.samples: 4
                        Canvas {
                            id: tekkenRedKdDot
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d")
                                ctx.clearRect(0, 0, width, height)
                                var cx = width / 2, cy = height / 2, r = Math.min(width, height) * 0.38
                                ctx.save()
                                ctx.shadowColor = parent.filled ? "rgba(255,196,64,0.72)" : "rgba(0,0,0,0.7)"
                                ctx.shadowBlur = parent.filled ? 8 : 4
                                var outer = ctx.createRadialGradient(cx - r * 0.25, cy - r * 0.35, r * 0.1, cx, cy, r * 1.28)
                                outer.addColorStop(0, parent.filled ? "#fff9d7" : "#667085")
                                outer.addColorStop(0.25, parent.filled ? "#d6a62d" : "#2f3744")
                                outer.addColorStop(0.72, parent.filled ? "#5a2b05" : "#05070c")
                                outer.addColorStop(1, parent.filled ? "#fff4c4" : "#1f2937")
                                ctx.fillStyle = outer
                                ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill()
                                var inner = ctx.createRadialGradient(cx - r * 0.28, cy - r * 0.34, 1, cx, cy, r * 0.86)
                                inner.addColorStop(0, parent.filled ? "#fffbe8" : "#111827")
                                inner.addColorStop(0.38, parent.filled ? "#ffd86a" : "#0b0f18")
                                inner.addColorStop(0.75, parent.filled ? "#c98712" : "#05070c")
                                inner.addColorStop(1, parent.filled ? "#4b2203" : "#02040a")
                                ctx.fillStyle = inner
                                ctx.beginPath(); ctx.arc(cx, cy, r * 0.72, 0, Math.PI * 2); ctx.fill()
                                ctx.strokeStyle = parent.filled ? "rgba(255,255,255,0.85)" : "rgba(203,213,225,0.35)"
                                ctx.lineWidth = 1.2
                                ctx.beginPath(); ctx.arc(cx, cy, r - 0.6, 0, Math.PI * 2); ctx.stroke()
                                ctx.restore()
                            }
                            Connections { target: backend; function onRedRoundKnockdownsChanged() { tekkenRedKdDot.requestPaint() } }
                            Component.onCompleted: requestPaint()
                        }
                    }
                }
            }
            Rectangle {
                anchors.fill: tekkenRedPortrait
                color: "white"
                opacity: root._tekkenRedFlash
            }
            Rectangle {
                anchors.fill: tekkenRedPortrait
                color: "#facc15"
                opacity: root._redHeavyImpact * 0.42
            }
            Rectangle {
                anchors.fill: tekkenRedPortrait
                color: "#020617"
                opacity: root._redKoBurst * 0.68
            }
            Text {
                anchors.centerIn: tekkenRedPortrait
                text: root._redTkoOverlay > root._redKdOverlay ? "TKO" : "DOWN"
                visible: root.qmlPreviewEnabled && root._redKoBurst > 0.01
                opacity: root._redKoBurst
                scale: 0.85 + root._redKoBurst * 0.35
                color: "#fef3c7"
                font.pixelSize: root._redTkoOverlay > root._redKdOverlay ? 31 : 24
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }
        }

        Item {
            id: tekkenBlueCombo
            x: 32 + root._tekkenBlueComboX + root._tekkenBlueComboShakeX
            y: 132 + root._tekkenBlueComboShakeY
            width: 220
            height: 54
            opacity: root._tekkenBlueComboVisible ? 1 : 0
            scale: root._tekkenBlueComboScale
            rotation: root._tekkenBlueComboRot
            Text {
                id: tekkenBlueComboTitle
                visible: text !== ""
                text: tekkenLayer.comboHit("blue")
                color: text === "COUNTER" ? "#fff7ed" : "#dbeafe"
                font.pixelSize: 26
                font.bold: true
                style: Text.Outline
                styleColor: text === "COUNTER" ? "#7f1d1d" : "#172554"
            }
            Text {
                anchors.top: tekkenBlueComboTitle.bottom
                anchors.left: parent.left
                visible: text !== ""
                text: tekkenLayer.comboDamage("blue")
                color: "#ffd76a"
                font.pixelSize: 22
                font.bold: true
                style: Text.Outline
                styleColor: "#7c2d12"
            }
        }

        Text {
            id: tekkenBlueRecentText
            x: 32 + root._tekkenBlueRecentShakeX
            y: 194 + root._tekkenBlueRecentShakeY
            width: 260
            text: tekkenLayer.recentText("blue")
            color: root.tekkenRecentColor("blue")
            opacity: (text !== "" && root._tekkenBlueRecentVisible) ? 0.95 : 0
            scale: root._tekkenBlueRecentScale
            rotation: root._tekkenBlueRecentRot
            font.pixelSize: backend ? backend.spectatorRecentTextSize : 23
            font.bold: true
            lineHeight: 0.9
            wrapMode: Text.NoWrap
            style: Text.Outline
            styleColor: root.tekkenRecentOutline("blue")
        }

        Item {
            id: tekkenRedCombo
            x: parent.width - width - 32 + root._tekkenRedComboX + root._tekkenRedComboShakeX
            y: 132 + root._tekkenRedComboShakeY
            width: 220
            height: 54
            opacity: root._tekkenRedComboVisible ? 1 : 0
            scale: root._tekkenRedComboScale
            rotation: root._tekkenRedComboRot
            Text {
                id: tekkenRedComboTitle
                visible: text !== ""
                text: tekkenLayer.comboHit("red")
                color: text === "COUNTER" ? "#fff7ed" : "#fee2e2"
                horizontalAlignment: Text.AlignRight
                width: parent.width
                font.pixelSize: 26
                font.bold: true
                style: Text.Outline
                styleColor: text === "COUNTER" ? "#7f1d1d" : "#450a0a"
            }
            Text {
                anchors.top: tekkenRedComboTitle.bottom
                anchors.right: parent.right
                visible: text !== ""
                text: tekkenLayer.comboDamage("red")
                color: "#ffd76a"
                font.pixelSize: 22
                font.bold: true
                style: Text.Outline
                styleColor: "#7c2d12"
            }
        }

        Text {
            id: tekkenRedRecentText
            x: parent.width - width - 32 + root._tekkenRedRecentShakeX
            y: 194 + root._tekkenRedRecentShakeY
            width: 260
            text: tekkenLayer.recentText("red")
            color: root.tekkenRecentColor("red")
            opacity: (text !== "" && root._tekkenRedRecentVisible) ? 0.95 : 0
            scale: root._tekkenRedRecentScale
            rotation: root._tekkenRedRecentRot
            horizontalAlignment: Text.AlignRight
            font.pixelSize: backend ? backend.spectatorRecentTextSize : 23
            font.bold: true
            lineHeight: 0.9
            wrapMode: Text.NoWrap
            style: Text.Outline
            styleColor: root.tekkenRecentOutline("red")
        }

        Item {
            anchors.fill: parent
            visible: root._tekkenKoOpacity > 0.01
            opacity: root._tekkenKoOpacity
            z: 20
            Rectangle {
                anchors.fill: parent
                color: "#ffffff"
                opacity: root._tekkenKoFlash
            }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * root._tekkenKoLineScale
                height: Math.max(8, parent.height * 0.018)
                radius: height / 2
                color: "#fff7ed"
                opacity: Math.min(0.85, root._tekkenKoOpacity)
                rotation: -2
            }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * Math.max(0, root._tekkenKoLineScale - 0.12)
                height: Math.max(4, parent.height * 0.009)
                radius: height / 2
                color: "#ef4444"
                opacity: Math.min(0.65, root._tekkenKoOpacity)
                rotation: 6
            }
            Item {
                id: tekkenKoTitleGroup
                width: parent.width
                height: root.tekkenKoIsTko() ? Math.max(65, parent.height * 0.1) : Math.max(46, parent.height * 0.07)
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.42 + root._tekkenKoY
                x: root._tekkenKoShakeX
                scale: root._tekkenKoScale
                rotation: root._tekkenKoRot

                Rectangle {
                    anchors.centerIn: parent
                    width: root.tekkenKoPanelWidth(parent.width)
                    height: parent.height
                    radius: 10
                    color: "#070b13"
                    opacity: 0.84
                    border.color: "#f59e0b"
                    border.width: 2
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * 0.18
                    width: root.tekkenKoPanelWidth(parent.width) * 1.06
                    height: Math.max(3, parent.height * 0.055)
                    radius: height / 2
                    color: "#fff7ed"
                    opacity: 0.7
                    rotation: -2
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * 0.74
                    width: root.tekkenKoPanelWidth(parent.width) * 1.02
                    height: Math.max(5, parent.height * 0.075)
                    radius: height / 2
                    color: "#dc2626"
                    opacity: 0.78
                    rotation: 2
                }
                Text {
                    anchors.centerIn: parent
                    width: parent.width * 0.82
                    text: root.tekkenKoDisplayText()
                    color: "#020617"
                    opacity: 0.85
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    lineHeight: 0.82
                    font.family: "Impact"
                    font.pixelSize: root.tekkenKoFontSize()
                    font.bold: true
                    font.italic: true
                    font.letterSpacing: root.tekkenKoIsTko() ? 2 : 4
                    style: Text.Outline
                    styleColor: "#020617"
                    transform: Translate { x: -5; y: 7 }
                }
                Text {
                    anchors.centerIn: parent
                    width: parent.width * 0.82
                    text: root.tekkenKoDisplayText()
                    color: "#b91c1c"
                    opacity: 0.78
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    lineHeight: 0.82
                    font.family: "Impact"
                    font.pixelSize: root.tekkenKoFontSize()
                    font.bold: true
                    font.italic: true
                    font.letterSpacing: root.tekkenKoIsTko() ? 2 : 4
                    transform: Translate { x: 4; y: 3 }
                }
                Text {
                    anchors.centerIn: parent
                    width: parent.width * 0.82
                    text: root.tekkenKoDisplayText()
                    color: "#fff7ed"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    lineHeight: 0.82
                    font.family: "Impact"
                    font.pixelSize: root.tekkenKoFontSize()
                    font.bold: true
                    font.italic: true
                    font.letterSpacing: root.tekkenKoIsTko() ? 2 : 4
                    style: Text.Outline
                    styleColor: "#7f1d1d"
                }
            }
        }

        Item {
            anchors.fill: parent
            opacity: root._tekkenVsOpacity
            scale: root._tekkenVsScale
            x: root._tekkenVsShakeX
            y: root._tekkenVsShakeY
            z: 19
            Image {
                anchors.fill: parent
                source: backend ? backend.overlayVsBackgroundSource : ""
                visible: source !== ""
                opacity: backend ? backend.overlayVsBackgroundOpacity : 1.0
                cache: false
                asynchronous: true
                smooth: true
                fillMode: Image.PreserveAspectCrop
            }
            Rectangle {
                anchors.fill: parent
                color: "#020617"
                opacity: (backend && backend.overlayVsBackgroundSource !== "") ? 0.42 : 0.78
            }
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#cc020617" }
                    GradientStop { position: 0.36; color: "#220f172a" }
                    GradientStop { position: 0.68; color: "#22111827" }
                    GradientStop { position: 1.0; color: "#dd020617" }
                }
            }
            Rectangle {
                anchors.fill: parent
                color: "#ffffff"
                opacity: root._tekkenVsFlash
            }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * (0.18 + root._tekkenVsFlash * 1.25)
                height: Math.max(3, parent.height * 0.012)
                radius: height / 2
                color: "#dff7ff"
                opacity: Math.min(0.85, root._tekkenVsFlash * 1.15)
                rotation: -2
            }
            Rectangle {
                anchors.centerIn: parent
                width: parent.width * (0.12 + root._tekkenVsFlash * 0.95)
                height: Math.max(2, parent.height * 0.006)
                radius: height / 2
                color: "#ff2d75"
                opacity: Math.min(0.7, root._tekkenVsFlash * 0.9)
                rotation: 8
            }
            Image {
                source: "image://players/blue?rev=" + (backend ? backend.blueImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                fillMode: Image.PreserveAspectFit
                width: Math.max(440, parent.width * 0.34)
                height: Math.max(520, parent.height * 0.76)
                x: Math.max(24, parent.width * 0.035) + root._tekkenVsBlueX
                y: Math.max(16, parent.height * 0.07)
                rotation: root._tekkenVsBlueRot
            }
            Image {
                source: "image://players/red?rev=" + (backend ? backend.redImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                mirror: true
                fillMode: Image.PreserveAspectFit
                width: Math.max(440, parent.width * 0.34)
                height: Math.max(520, parent.height * 0.76)
                x: parent.width - width - Math.max(24, parent.width * 0.035) + root._tekkenVsRedX
                y: Math.max(16, parent.height * 0.07)
                rotation: root._tekkenVsRedRot
            }
            Text {
                x: Math.max(52, parent.width * 0.052)
                y: parent.height * 0.63 + root._tekkenVsNameY
                width: parent.width * 0.32
                text: tekkenLayer.sideName("blue")
                color: "#e0f2fe"
                font.pixelSize: Math.max(34, parent.height * 0.062)
                font.bold: true
                font.italic: true
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#082f49"
            }
            Text {
                x: parent.width - width - Math.max(52, parent.width * 0.052)
                y: parent.height * 0.63 + root._tekkenVsNameY
                width: parent.width * 0.32
                text: tekkenLayer.sideName("red")
                color: "#e0f2fe"
                horizontalAlignment: Text.AlignRight
                font.pixelSize: Math.max(34, parent.height * 0.062)
                font.bold: true
                font.italic: true
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#7f1d1d"
            }
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.73 + root._tekkenVsStageY
                width: Math.max(420, parent.width * 0.34)
                height: Math.max(70, parent.height * 0.075)
                color: "#44020617"
                border.color: "#66e0f2fe"
                border.width: 1
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: -18
                    text: "STAGE"
                    color: "#e5e7eb"
                    opacity: 0.88
                    font.pixelSize: 24
                    font.bold: true
                    font.letterSpacing: 4
                    style: Text.Outline
                    styleColor: "#020617"
                }
                Text {
                    anchors.centerIn: parent
                    text: (backend && backend.arenaName !== "") ? backend.arenaName : "DEFAULT"
                    color: "#ff2d75"
                    font.pixelSize: Math.max(24, parent.height * 0.42)
                    font.bold: true
                    font.italic: true
                    font.letterSpacing: 2
                    style: Text.Outline
                    styleColor: "#020617"
                }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 160
            text: root._tekkenIntroText
            opacity: root._tekkenIntroOpacity
            scale: root._tekkenIntroScale
            color: "#fefce8"
            font.pixelSize: 70
            font.bold: true
            style: Text.Outline
            styleColor: "#1e293b"
            z: 21
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 226
            text: root._tekkenIntroSubText
            opacity: root._tekkenIntroOpacity
            scale: root._tekkenIntroScale
            color: "#facc15"
            font.pixelSize: 38
            font.bold: true
            style: Text.Outline
            styleColor: "#1e293b"
            z: 21
        }

        Connections {
            target: backend
            function onBlueComboHitTextChanged() {
                if (backend.blueComboHitText !== "") {
                    var wasVisible = root._tekkenBlueComboVisible
                    root._tekkenBlueComboVisible = true
                    if (!wasVisible)
                        tekkenBlueComboIn.restart()
                    tekkenBlueComboPunch.restart()
                    tekkenBlueComboHideTimer.restart()
                } else {
                    root._tekkenBlueComboVisible = false
                }
            }
            function onRedComboHitTextChanged() {
                if (backend.redComboHitText !== "") {
                    var wasVisible = root._tekkenRedComboVisible
                    root._tekkenRedComboVisible = true
                    if (!wasVisible)
                        tekkenRedComboIn.restart()
                    tekkenRedComboPunch.restart()
                    tekkenRedComboHideTimer.restart()
                } else {
                    root._tekkenRedComboVisible = false
                }
            }
            function onBlueRecentHitTextChanged() {
                if (backend.blueRecentHitText !== "") {
                    root._tekkenBlueRecentVisible = true
                    tekkenBlueRecentImpact.restart()
                    tekkenBlueRecentHideTimer.restart()
                } else {
                    root._tekkenBlueRecentVisible = false
                }
            }
            function onRedRecentHitTextChanged() {
                if (backend.redRecentHitText !== "") {
                    root._tekkenRedRecentVisible = true
                    tekkenRedRecentImpact.restart()
                    tekkenRedRecentHideTimer.restart()
                } else {
                    root._tekkenRedRecentVisible = false
                }
            }
            function onRoundTextChanged() {
            }
            function onVsIntroResetRequested() {
                root._tekkenVsKey = ""
                if (root.tekkenPreset)
                    root.maybeStartTekkenVsIntro()
            }
            function onRoundIntroRequested() {
                if (root.tekkenPreset)
                    root.maybeStartTekkenRoundIntro(true)
            }
        }
    }

    SequentialAnimation {
        id: tekkenBlueHitAnim
        NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: -Math.max(4, Math.min(20, root._blueHitDamage / 3)); duration: 32 }
        NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: Math.max(3, Math.min(14, root._blueHitDamage / 4)); duration: 38 }
        NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: 0; duration: 70; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: tekkenRedHitAnim
        NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: Math.max(4, Math.min(20, root._redHitDamage / 3)); duration: 32 }
        NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: -Math.max(3, Math.min(14, root._redHitDamage / 4)); duration: 38 }
        NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: 0; duration: 70; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: tekkenBlueStunAnim
        ScriptAction { script: { root._tekkenBlueFlash = 1.0; root._tekkenBlueShakeX = -18; root._tekkenBlueShakeY = -12 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: 16; duration: 34 }
            NumberAnimation { target: root; property: "_tekkenBlueShakeY"; to: 10; duration: 34 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: -9; duration: 42 }
            NumberAnimation { target: root; property: "_tekkenBlueShakeY"; to: -6; duration: 42 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueFlash"; to: 0.0; duration: 520; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenBlueShakeX"; to: 0; duration: 150; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueShakeY"; to: 0; duration: 150; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenRedStunAnim
        ScriptAction { script: { root._tekkenRedFlash = 1.0; root._tekkenRedShakeX = 18; root._tekkenRedShakeY = -12 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: -16; duration: 34 }
            NumberAnimation { target: root; property: "_tekkenRedShakeY"; to: 10; duration: 34 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: 9; duration: 42 }
            NumberAnimation { target: root; property: "_tekkenRedShakeY"; to: -6; duration: 42 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedFlash"; to: 0.0; duration: 520; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenRedShakeX"; to: 0; duration: 150; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedShakeY"; to: 0; duration: 150; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenKoAnim
        ScriptAction {
            script: {
                root._tekkenKoOpacity = 0
                root._tekkenKoScale = 1.34
                root._tekkenKoY = -190
                root._tekkenKoShakeX = 0
                root._tekkenKoFlash = 0.0
                root._tekkenKoLineScale = 0.0
                root._tekkenKoRot = -5
            }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoOpacity"; to: 1; duration: 60 }
            NumberAnimation { target: root; property: "_tekkenKoY"; to: 24; duration: 150; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 0.96; duration: 150; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "_tekkenKoRot"; to: 2.0; duration: 150; easing.type: Easing.InCubic }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoY"; to: 0; duration: 85; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 1.08; duration: 75; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenKoRot"; to: 0; duration: 85; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenKoFlash"; from: 1.0; to: 0.25; duration: 85; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenKoLineScale"; from: 0.12; to: 0.92; duration: 95; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenKoShakeX"; from: 0; to: -34; duration: 42 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoShakeX"; to: 26; duration: 46 }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 0.98; duration: 70; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenKoFlash"; to: 0.0; duration: 220; easing.type: Easing.OutQuad }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoShakeX"; to: -12; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 1.03; duration: 65; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenKoLineScale"; to: 0.68; duration: 150; easing.type: Easing.OutQuad }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoShakeX"; to: 0; duration: 130; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 1.0; duration: 130; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 1150 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenKoOpacity"; to: 0; duration: 420; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_tekkenKoScale"; to: 1.14; duration: 420; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_tekkenKoLineScale"; to: 1.15; duration: 420; easing.type: Easing.InQuad }
        }
    }
    SequentialAnimation {
        id: tekkenVsIntroAnim
        ScriptAction {
            script: {
                root._tekkenVsOpacity = 0
                root._tekkenVsScale = 1.04
                root._tekkenVsFlash = 1.0
                root._tekkenVsShakeX = 0
                root._tekkenVsShakeY = 0
                root._tekkenVsBlueX = -Math.max(640, root.width * 0.44)
                root._tekkenVsRedX = Math.max(640, root.width * 0.44)
                root._tekkenVsBlueRot = -10
                root._tekkenVsRedRot = 10
                root._tekkenVsNameY = 96
                root._tekkenVsStageY = 120
            }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsOpacity"; to: 1; duration: 70 }
            NumberAnimation { target: root; property: "_tekkenVsFlash"; to: 0.15; duration: 170; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenVsBlueX"; to: 42; duration: 230; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsRedX"; to: -42; duration: 230; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsBlueRot"; to: 2.5; duration: 230; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsRedRot"; to: -2.5; duration: 230; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsNameY"; to: 14; duration: 250; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsStageY"; to: 20; duration: 280; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenVsScale"; to: 1.0; duration: 230; easing.type: Easing.OutCubic }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsBlueX"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsRedX"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsBlueRot"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsRedRot"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsNameY"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsStageY"; to: 0; duration: 115; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsFlash"; to: 0.55; duration: 45 }
            NumberAnimation { target: root; property: "_tekkenVsShakeX"; from: 0; to: -22; duration: 45 }
            NumberAnimation { target: root; property: "_tekkenVsShakeY"; from: 0; to: -6; duration: 45 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsFlash"; to: 0; duration: 260; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenVsShakeX"; to: 16; duration: 52 }
            NumberAnimation { target: root; property: "_tekkenVsShakeY"; to: 4; duration: 52 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsShakeX"; to: -7; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenVsShakeY"; to: -2; duration: 48 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsShakeX"; to: 0; duration: 120; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenVsShakeY"; to: 0; duration: 120; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: backend ? backend.overlayVsHoldMs : 2850 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenVsOpacity"; to: 0; duration: 420; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_tekkenVsScale"; to: 1.12; duration: 420; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_tekkenVsBlueX"; to: -Math.max(420, root.width * 0.28); duration: 420; easing.type: Easing.InCubic }
            NumberAnimation { target: root; property: "_tekkenVsRedX"; to: Math.max(420, root.width * 0.28); duration: 420; easing.type: Easing.InCubic }
        }
    }
    SequentialAnimation {
        id: tekkenRoundIntroAnim
        ScriptAction { script: { root._tekkenIntroOpacity = 0; root._tekkenIntroScale = 0.82 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenIntroOpacity"; to: 1; duration: 120 }
            NumberAnimation { target: root; property: "_tekkenIntroScale"; to: 1.06; duration: 160; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 880 }
        ScriptAction { script: { root._tekkenIntroText = "FIGHT"; root._tekkenIntroSubText = "" } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenIntroOpacity"; from: 0.5; to: 1; duration: 70 }
            NumberAnimation { target: root; property: "_tekkenIntroScale"; from: 0.82; to: 1.15; duration: 120; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 620 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenIntroOpacity"; to: 0; duration: 260 }
            NumberAnimation { target: root; property: "_tekkenIntroScale"; to: 1.34; duration: 260 }
        }
    }
    SequentialAnimation {
        id: tekkenBlueComboIn
        ScriptAction { script: { root._tekkenBlueComboX = -260; root._tekkenBlueComboShakeX = 0; root._tekkenBlueComboShakeY = 0; root._tekkenBlueComboRot = -7 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueComboX"; to: 22; duration: 105; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenBlueComboRot"; to: 2; duration: 105; easing.type: Easing.OutCubic }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueComboX"; to: 0; duration: 75; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueComboRot"; to: 0; duration: 75; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenRedComboIn
        ScriptAction { script: { root._tekkenRedComboX = 260; root._tekkenRedComboShakeX = 0; root._tekkenRedComboShakeY = 0; root._tekkenRedComboRot = 7 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedComboX"; to: -22; duration: 105; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenRedComboRot"; to: -2; duration: 105; easing.type: Easing.OutCubic }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedComboX"; to: 0; duration: 75; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedComboRot"; to: 0; duration: 75; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenBlueComboPunch
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueComboScale"; from: 1.34; to: 0.9; duration: 55; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeX"; from: 0; to: -18; duration: 55 }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeY"; from: 0; to: -7; duration: 55 }
            NumberAnimation { target: root; property: "_tekkenBlueComboRot"; from: -4; to: 3; duration: 55 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueComboScale"; to: 1.08; duration: 58; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeX"; to: 10; duration: 58 }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeY"; to: 4; duration: 58 }
            NumberAnimation { target: root; property: "_tekkenBlueComboRot"; to: -1.5; duration: 58 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueComboScale"; to: 1.0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeX"; to: 0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueComboShakeY"; to: 0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueComboRot"; to: 0; duration: 90; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenRedComboPunch
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedComboScale"; from: 1.34; to: 0.9; duration: 55; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeX"; from: 0; to: 18; duration: 55 }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeY"; from: 0; to: -7; duration: 55 }
            NumberAnimation { target: root; property: "_tekkenRedComboRot"; from: 4; to: -3; duration: 55 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedComboScale"; to: 1.08; duration: 58; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeX"; to: -10; duration: 58 }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeY"; to: 4; duration: 58 }
            NumberAnimation { target: root; property: "_tekkenRedComboRot"; to: 1.5; duration: 58 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedComboScale"; to: 1.0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeX"; to: 0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedComboShakeY"; to: 0; duration: 90; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedComboRot"; to: 0; duration: 90; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenBlueRecentImpact
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueRecentScale"; from: 1.22; to: 0.95; duration: 48; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeX"; from: 0; to: -12; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeY"; from: 0; to: -5; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenBlueRecentRot"; from: -3; to: 2; duration: 48 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueRecentScale"; to: 1.08; duration: 54; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeX"; to: 8; duration: 54 }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeY"; to: 3; duration: 54 }
            NumberAnimation { target: root; property: "_tekkenBlueRecentRot"; to: -1; duration: 54 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenBlueRecentScale"; to: 1.0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeX"; to: 0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueRecentShakeY"; to: 0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenBlueRecentRot"; to: 0; duration: 92; easing.type: Easing.OutBack }
        }
    }
    SequentialAnimation {
        id: tekkenRedRecentImpact
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedRecentScale"; from: 1.22; to: 0.95; duration: 48; easing.type: Easing.OutQuad }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeX"; from: 0; to: 12; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeY"; from: 0; to: -5; duration: 48 }
            NumberAnimation { target: root; property: "_tekkenRedRecentRot"; from: 3; to: -2; duration: 48 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedRecentScale"; to: 1.08; duration: 54; easing.type: Easing.OutCubic }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeX"; to: -8; duration: 54 }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeY"; to: 3; duration: 54 }
            NumberAnimation { target: root; property: "_tekkenRedRecentRot"; to: 1; duration: 54 }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_tekkenRedRecentScale"; to: 1.0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeX"; to: 0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedRecentShakeY"; to: 0; duration: 92; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_tekkenRedRecentRot"; to: 0; duration: 92; easing.type: Easing.OutBack }
        }
    }
    Timer {
        id: tekkenBlueComboHideTimer
        interval: 1900
        repeat: false
        onTriggered: {
            root._tekkenBlueComboVisible = false
            if (backend) backend.clear_combo_display("blue")
        }
    }
    Timer {
        id: tekkenRedComboHideTimer
        interval: 1900
        repeat: false
        onTriggered: {
            root._tekkenRedComboVisible = false
            if (backend) backend.clear_combo_display("red")
        }
    }
    Timer {
        id: tekkenBlueRecentHideTimer
        interval: 1900
        repeat: false
        onTriggered: root._tekkenBlueRecentVisible = false
    }
    Timer {
        id: tekkenRedRecentHideTimer
        interval: 1900
        repeat: false
        onTriggered: root._tekkenRedRecentVisible = false
    }

    Item {
        id: createLayer
        parent: scaledRoot
        anchors.fill: parent
        z: -1
        visible: editMode
        property bool creating: false
        property real startX: 0
        property real startY: 0
        Rectangle {
            id: createPreview
            visible: createLayer.creating
            color: "#60a5fa"
            opacity: 0.2
            border.color: "#3b82f6"
            border.width: 1
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            onPressed: {
                createLayer.creating = true
                createLayer.startX = mouse.x
                createLayer.startY = mouse.y
                createPreview.x = mouse.x
                createPreview.y = mouse.y
                createPreview.width = 0
                createPreview.height = 0
            }
            onPositionChanged: {
                if (!createLayer.creating) return
                var x0 = createLayer.startX
                var y0 = createLayer.startY
                var x1 = mouse.x
                var y1 = mouse.y
                var left = Math.min(x0, x1)
                var top = Math.min(y0, y1)
                var w = Math.abs(x1 - x0)
                var h = Math.abs(y1 - y0)
                createPreview.x = left
                createPreview.y = clampY(top)
                createPreview.width = w
                createPreview.height = h
            }
            onReleased: {
                if (!createLayer.creating) return
                createLayer.creating = false
                var w = createPreview.width
                var h = createPreview.height
                if (w >= 20 && h >= 16) {
                    addCustomElement(createPreview.x, createPreview.y, w, h, "")
                }
                createPreview.width = 0
                createPreview.height = 0
            }
        }
    }

    Item {
        id: customLayer
        parent: scaledRoot
        anchors.fill: parent
        visible: root.qmlPreviewEnabled
        z: 1
        Repeater {
            model: customModel
            delegate: Rectangle {
                id: customBox
                property bool isSnapItem: true
                property bool isCustom: true
                property int modelIndex: index
                property int borderW: Math.max(1, model.border_width === undefined ? 2 : model.border_width)
                property color borderCol: {
                    var c = Qt.color(model.border_color || "#111827")
                    var o = model.border_opacity === undefined ? 1.0 : model.border_opacity
                    return Qt.rgba(c.r, c.g, c.b, Math.max(0, Math.min(1, o)))
                }
                x: model.x
                y: model.y
                width: model.w
                height: model.h
                visible: editMode ? true : !!model.visible
                opacity: (editMode && !model.visible) ? 0.25 : 1.0
                color: {
                    var c = Qt.color(model.bg_color || "#1f2937")
                    var o = model.bg_opacity === undefined ? 0.85 : model.bg_opacity
                    var col = Qt.rgba(c.r, c.g, c.b, Math.max(0, Math.min(1, o)))
                    return root._matchBg(customBox, col)
                }
                border.color: "transparent"
                border.width: 0
                radius: root._matchRadius(customBox, 4)
                HoverHandler { id: customHover }
                ToolTip.visible: customHover.hovered
                ToolTip.text: (model.text && model.text.length > 0)
                    ? ("\uCEE4\uC2A4\uD140 \uC694\uC18C: " + model.text + " (\uD3B8\uC9D1 \uBAA8\uB4DC\uC5D0\uC11C \uB4DC\uB798\uADF8\uB85C \uC774\uB3D9/\uD06C\uAE30 \uC870\uC808)")
                    : "\uCEE4\uC2A4\uD140 \uC694\uC18C (\uD3B8\uC9D1 \uBAA8\uB4DC\uC5D0\uC11C \uB4DC\uB798\uADF8\uB85C \uC774\uB3D9/\uD06C\uAE30 \uC870\uC808)"
                onVisibleChanged: scheduleBoundsUpdate()
                onXChanged: scheduleBoundsUpdate()
                onYChanged: scheduleBoundsUpdate()
                onWidthChanged: scheduleBoundsUpdate()
                onHeightChanged: scheduleBoundsUpdate()
                Text {
                    anchors.centerIn: parent
                    text: model.text || ""
                    font.pixelSize: (model.font_size && model.font_size > 0)
                        ? model.font_size
                        : Math.max(12, Math.min(parent.height * 0.6, 48))
                    font.bold: model.font_bold === undefined ? true : model.font_bold
                    font.weight: model.font_weight === undefined ? 700 : model.font_weight
                    font.family: model.font_family || "Bahnschrift"
                    color: {
                        var c = Qt.color(model.text_color || "#ffffff")
                        var o = model.text_opacity === undefined ? 1.0 : model.text_opacity
                        return Qt.rgba(c.r, c.g, c.b, Math.max(0, Math.min(1, o)))
                    }
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                }
                Rectangle {
                    visible: !root._touchingSide(customBox, "top")
                    color: root._matchBorder(customBox, customBox.borderCol)
                    x: 0
                    y: 0
                    width: customBox.width
                    height: customBox.borderW
                    z: 6
                }
                Rectangle {
                    visible: !root._touchingSide(customBox, "bottom")
                    color: root._matchBorder(customBox, customBox.borderCol)
                    x: 0
                    y: customBox.height - customBox.borderW
                    width: customBox.width
                    height: customBox.borderW
                    z: 6
                }
                Rectangle {
                    visible: !root._touchingSide(customBox, "left")
                    color: root._matchBorder(customBox, customBox.borderCol)
                    x: 0
                    y: 0
                    width: customBox.borderW
                    height: customBox.height
                    z: 6
                }
                Rectangle {
                    visible: !root._touchingSide(customBox, "right")
                    color: root._matchBorder(customBox, customBox.borderCol)
                    x: customBox.width - customBox.borderW
                    y: 0
                    width: customBox.borderW
                    height: customBox.height
                    z: 6
                }
                Rectangle {
                    width: 34; height: 14; radius: 2
                    color: model.visible ? "#ef4444" : "#22c55e"
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.rightMargin: 2
                    anchors.topMargin: 2
                    visible: editMode
                    z: 20
                    Text {
                        anchors.centerIn: parent
                        text: model.visible ? "???" : "??뽯뻻"
                        color: "#ffffff"
                        font.pixelSize: 10
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            pushHistory()
                            customModel.setProperty(index, "visible", !model.visible)
                            saveLayout()
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: !editMode && !!model.visible
                    z: 1
                    onClicked: {
                        customModel.setProperty(index, "visible", false)
                        saveLayout()
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: editMode
                    z: 1
                    drag.target: parent
                    property bool duplicateDrag: false
                    property int duplicateIndex: -1
                    property string duplicateId: ""
                    property real pressX: 0
                    property real pressY: 0
                    property real startItemX: 0
                    property real startItemY: 0
                    onPressed: function(mouse) {
                        pressX = mouse.x
                        pressY = mouse.y
                        startItemX = customBox.x
                        startItemY = customBox.y
                        duplicateDrag = false
                        duplicateIndex = -1
                        duplicateId = ""
                        drag.target = parent
                        root.activeDragItem = customBox
                        root.lastDragItem = customBox
                        root.selectedItem = customBox
                        keyFocus.forceActiveFocus()
                        if (mouse.modifiers & Qt.AltModifier) {
                            pushHistory()
                            var duplicated = root.duplicateCustomElement(index)
                            if (duplicated) {
                                duplicateDrag = true
                                duplicateIndex = duplicated.index
                                duplicateId = duplicated.id
                                drag.target = null
                                var dupItem = duplicated.item ? duplicated.item : root.findCustomItemById(duplicated.id)
                                if (dupItem) {
                                    root.activeDragItem = dupItem
                                    root.lastDragItem = dupItem
                                    root.selectedItem = dupItem
                                    startItemX = dupItem.x
                                    startItemY = dupItem.y
                                } else if (duplicateIndex >= 0 && duplicateIndex < customModel.count) {
                                    var dupModel = customModel.get(duplicateIndex)
                                    startItemX = dupModel.x
                                    startItemY = dupModel.y
                                }
                                Qt.callLater(function() {
                                    var createdItem = root.findCustomItemById(duplicateId)
                                    if (createdItem) {
                                        root.activeDragItem = createdItem
                                        root.lastDragItem = createdItem
                                        root.selectedItem = createdItem
                                    }
                                })
                            }
                        }
                    }
                    onPositionChanged: function(mouse) {
                        if (duplicateDrag) {
                            if (duplicateIndex < 0 || duplicateIndex >= customModel.count) return
                            var item = root.selectedItem
                            if (!item || !item.isCustom) item = root.findCustomItemById(duplicateId)
                            var dx = mouse.x - pressX
                            var dy = mouse.y - pressY
                            var snapRef = item ? item : customBox
                            var p = root.snapPos(snapRef, startItemX + dx, startItemY + dy)
                            customModel.setProperty(duplicateIndex, "x", p.x)
                            customModel.setProperty(duplicateIndex, "y", p.y)
                            if (item) {
                                item.x = p.x
                                item.y = p.y
                                root.selectedItem = item
                            }
                            return
                        }
                        var p = root.snapPos(customBox, customBox.x, customBox.y)
                        customBox.x = p.x
                        customBox.y = p.y
                        customModel.setProperty(index, "x", customBox.x)
                        customModel.setProperty(index, "y", customBox.y)
                    }
                    onReleased: {
                        root.activeDragItem = null
                        if (duplicateDrag) {
                            if (duplicateIndex >= 0 && duplicateIndex < customModel.count) {
                                var releasedItem = root.findCustomItemById(duplicateId)
                                if (releasedItem) {
                                    customModel.setProperty(duplicateIndex, "x", releasedItem.x)
                                    customModel.setProperty(duplicateIndex, "y", releasedItem.y)
                                    root.selectedItem = releasedItem
                                }
                            }
                        } else {
                            customModel.setProperty(index, "x", customBox.x)
                            customModel.setProperty(index, "y", customBox.y)
                        }
                        duplicateDrag = false
                        duplicateIndex = -1
                        duplicateId = ""
                        drag.target = parent
                        saveLayout()
                    }
                }
                Rectangle {
                    width: 10; height: 10; radius: 2
                    color: "#ffffff"; border.color: "#333"
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    visible: editMode
                    z: 5
                    property real startW
                    property real startH
                    property real startX
                    property real startY
                    MouseArea {
                        anchors.fill: parent
                        onPressed: {
                            parent.startW = customBox.width
                            parent.startH = customBox.height
                            parent.startX = mouse.x
                            parent.startY = mouse.y
                        }
                        onPositionChanged: {
                            customBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                            customBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                            customModel.setProperty(index, "w", customBox.width)
                            customModel.setProperty(index, "h", customBox.height)
                        }
                        onReleased: {
                            customModel.setProperty(index, "w", customBox.width)
                            customModel.setProperty(index, "h", customBox.height)
                            saveLayout()
                        }
                    }
                }
            }
        }
        Repeater {
            model: customModel
            delegate: Item {
                parent: customLayer
                x: model.x
                y: model.y
                width: model.w
                height: model.h
                visible: !editMode && !model.visible
                z: 2
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    onClicked: {
                        customModel.setProperty(index, "visible", true)
                        saveLayout()
                    }
                }
            }
        }
    }

    Rectangle {
        id: roundBox
        parent: scaledRoot
        property int borderW: Math.max(1, root.styleVal("round", "border_width", 2))
        property color borderCol: root.styleColor("round", "border_color", "#5b4631", "border_opacity", 1.0)
        color: root._matchBg(roundBox, root.styleColor("round", "bg_color", "#bfa57a", "bg_opacity", 1.0))
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowRound))
        opacity: (editMode && backend && !backend.overlayShowRound) ? 0.25 : 1.0
        border.color: "transparent"
        border.width: 0
        radius: root._matchRadius(roundBox, 4)
        HoverHandler { id: roundHover }
        ToolTip.visible: roundHover.hovered
        ToolTip.text: "\uB77C\uC6B4\uB4DC \uD14D\uC2A4\uD2B8"
        onVisibleChanged: scheduleBoundsUpdate()
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            anchors.centerIn: parent
            text: backend ? backend.roundText : ""
            font.pixelSize: root.styleFontSize("round", Math.max(16, Math.min(parent.height * 0.3, 28)))
            font.bold: root.styleVal("round", "font_bold", true)
            font.weight: root.styleVal("round", "font_weight", 700)
            font.family: root.styleVal("round", "font_family", "Bahnschrift")
            color: root.styleColor("round", "text_color", "#3a2a1d", "text_opacity", 1.0)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.NoWrap
        }
        Rectangle {
            visible: !root._touchingSide(roundBox, "top")
            color: root._matchBorder(roundBox, roundBox.borderCol)
            x: 0
            y: 0
            width: roundBox.width
            height: roundBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(roundBox, "bottom")
            color: root._matchBorder(roundBox, roundBox.borderCol)
            x: 0
            y: roundBox.height - roundBox.borderW
            width: roundBox.width
            height: roundBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(roundBox, "left")
            color: root._matchBorder(roundBox, roundBox.borderCol)
            x: 0
            y: 0
            width: roundBox.borderW
            height: roundBox.height
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(roundBox, "right")
            color: root._matchBorder(roundBox, roundBox.borderCol)
            x: roundBox.width - roundBox.borderW
            y: 0
            width: roundBox.borderW
            height: roundBox.height
            z: 6
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: function(mouse) {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: function(mouse) {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: function(mouse) {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    if (backend) backend.decrement_round()
                } else {
                    if (backend) backend.increment_round()
                }
            }
        }
                MouseArea {
                    anchors.fill: parent
                    enabled: editMode
                    drag.target: parent
                    onPressed: { root.activeDragItem = roundBox; root.lastDragItem = roundBox; root.selectedItem = roundBox; keyFocus.forceActiveFocus() }
                    onPositionChanged: {
                        var p = root.snapPos(roundBox, roundBox.x, roundBox.y)
                        roundBox.x = p.x
                        roundBox.y = p.y
                    }
                    onReleased: { root.activeDragItem = null; saveLayout() }
                }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = roundBox.width
                    parent.startH = roundBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    roundBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    roundBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowRound) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowRound) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("round", !backend.overlayShowRound); saveLayout() }
            }
        }
    }

    Rectangle {
        id: timeBox
        parent: scaledRoot
        property int borderW: Math.max(1, root.styleVal("time", "border_width", 2))
        property color borderCol: root.styleColor("time", "border_color", "#1a1a1a", "border_opacity", 1.0)
        color: root._matchBg(timeBox, root.styleColor("time", "bg_color", "#3a3a3a", "bg_opacity", 1.0))
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend ? backend.overlayShowTime : false))
        opacity: (editMode && backend && !backend.overlayShowTime) ? 0.25 : 1.0
        border.color: "transparent"
        border.width: 0
        radius: root._matchRadius(timeBox, 4)
        HoverHandler { id: timeHover }
        ToolTip.visible: timeHover.hovered
        ToolTip.text: "\uC2DC\uAC04 \uD14D\uC2A4\uD2B8"
        onVisibleChanged: scheduleBoundsUpdate()
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            anchors.centerIn: parent
            text: backend ? backend.timeText : ""
            font.pixelSize: root.styleFontSize("time", Math.max(20, Math.min(parent.height * 0.6, 64)))
            font.bold: root.styleVal("time", "font_bold", true)
            font.weight: root.styleVal("time", "font_weight", 700)
            font.family: root.styleVal("time", "font_family", "Bahnschrift")
            color: (backend && backend.restMode)
                ? root.styleColor("time", "rest_text_color", "#ff5a5a", "rest_text_opacity", 1.0)
                : root.styleColor("time", "text_color", "#ffffff", "text_opacity", 1.0)
        }
        Rectangle {
            visible: !root._touchingSide(timeBox, "top")
            color: root._matchBorder(timeBox, timeBox.borderCol)
            x: 0
            y: 0
            width: timeBox.width
            height: timeBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(timeBox, "bottom")
            color: root._matchBorder(timeBox, timeBox.borderCol)
            x: 0
            y: timeBox.height - timeBox.borderW
            width: timeBox.width
            height: timeBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(timeBox, "left")
            color: root._matchBorder(timeBox, timeBox.borderCol)
            x: 0
            y: 0
            width: timeBox.borderW
            height: timeBox.height
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(timeBox, "right")
            color: root._matchBorder(timeBox, timeBox.borderCol)
            x: timeBox.width - timeBox.borderW
            y: 0
            width: timeBox.borderW
            height: timeBox.height
            z: 6
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: function(mouse) {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: function(mouse) {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    if (backend) backend.toggle_rest_mode()
                } else {
                    if (backend) backend.toggle_timer()
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = timeBox; root.lastDragItem = timeBox; root.selectedItem = timeBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(timeBox, timeBox.x, timeBox.y)
                timeBox.x = p.x
                timeBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = timeBox.width
                    parent.startH = timeBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    timeBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    timeBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowTime) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowTime) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("time", !backend.overlayShowTime); saveLayout() }
            }
        }
    }

    Rectangle {
        id: spectatorMatchBadge
        parent: scaledRoot
        z: 80
        width: Math.max(150, spectatorMatchText.implicitWidth + 20)
        height: 24
        x: timeBox.x + (timeBox.width - width) * 0.5
        y: timeBox.y - height - 6
        radius: 8
        color: Qt.rgba(7 / 255, 12 / 255, 20 / 255, 0.82)
        border.color: Qt.rgba(148 / 255, 163 / 255, 184 / 255, 0.8)
        border.width: 1
        visible: root.qmlPreviewEnabled && backend && backend.spectatorMatchText !== ""
        onVisibleChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        ToolTip.visible: matchBadgeHover.hovered
        ToolTip.text: backend ? backend.cameraText : ""
        HoverHandler { id: matchBadgeHover }
        Text {
            id: spectatorMatchText
            anchors.centerIn: parent
            text: backend ? backend.spectatorMatchText : ""
            color: "#e5e7eb"
            font.bold: true
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        id: spectatorRecentHitBadge
        parent: scaledRoot
        z: 80
        width: Math.max(210, spectatorRecentHitText.implicitWidth + 22)
        height: Math.max(26, spectatorRecentHitText.implicitHeight + 8)
        x: timeBox.x + (timeBox.width - width) * 0.5
        y: timeBox.y + timeBox.height + 6
        radius: 9
        color: Qt.rgba(10 / 255, 15 / 255, 24 / 255, 0.88)
        border.color: Qt.rgba(250 / 255, 204 / 255, 21 / 255, 0.9)
        border.width: 1
        visible: false
        onVisibleChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            id: spectatorRecentHitText
            anchors.centerIn: parent
            text: backend ? backend.spectatorRecentHitText : ""
            color: "#fef3c7"
            font.bold: true
            font.pixelSize: Math.max(10, Math.round((backend ? backend.spectatorRecentTextSize : 23) * 0.55))
            lineHeight: 0.9
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        id: blueRecentHitBadge
        parent: scaledRoot
        z: 80
        width: Math.max(128, blueRecentHitText.implicitWidth + 18)
        height: Math.max(24, blueRecentHitText.implicitHeight + 8)
        x: blueImgBox.x + (blueImgBox.width - width) * 0.5
        y: blueImgBox.y + blueImgBox.height + Math.max(28, blueImgBox.height * 0.26)
        radius: 8
        color: Qt.rgba(5 / 255, 18 / 255, 36 / 255, 0.88)
        border.color: Qt.rgba(96 / 255, 165 / 255, 250 / 255, 0.95)
        border.width: 1
        visible: root.qmlPreviewEnabled && backend && backend.blueRecentHitText !== ""
        onVisibleChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            id: blueRecentHitText
            anchors.centerIn: parent
            text: backend ? backend.blueRecentHitText : ""
            color: "#dbeafe"
            font.bold: true
            font.pixelSize: Math.max(10, Math.round((backend ? backend.spectatorRecentTextSize : 23) * 0.55))
            lineHeight: 0.9
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Rectangle {
        id: redRecentHitBadge
        parent: scaledRoot
        z: 80
        width: Math.max(128, redRecentHitText.implicitWidth + 18)
        height: Math.max(24, redRecentHitText.implicitHeight + 8)
        x: redImgBox.x + (redImgBox.width - width) * 0.5
        y: redImgBox.y + redImgBox.height + Math.max(28, redImgBox.height * 0.26)
        radius: 8
        color: Qt.rgba(39 / 255, 7 / 255, 7 / 255, 0.88)
        border.color: Qt.rgba(248 / 255, 113 / 255, 113 / 255, 0.95)
        border.width: 1
        visible: root.qmlPreviewEnabled && backend && backend.redRecentHitText !== ""
        onVisibleChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            id: redRecentHitText
            anchors.centerIn: parent
            text: backend ? backend.redRecentHitText : ""
            color: "#fee2e2"
            font.bold: true
            font.pixelSize: Math.max(10, Math.round((backend ? backend.spectatorRecentTextSize : 23) * 0.55))
            lineHeight: 0.9
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    Item {
        id: blueAura
        parent: scaledRoot
        x: blueImgBox.x
        y: blueImgBox.y
        width: blueImgBox.width
        height: blueImgBox.height
        visible: root.qmlPreviewEnabled && blueImgBox.visible && backend && root._stageFor(backend.blueWinStreak) !== null && root._cfg("aura.enabled", true)
        z: blueImgBox.z - 1
        property int streak: backend ? backend.blueWinStreak : 0
        property color auraColor: root.auraColorFor(streak)
        property real baseOpacity: root.auraOpacityFor(streak)
        property int level: root.auraLevel(streak)
        property real intensity: 1.0
        property int framePad: root._cfg("aura.frame_padding", 12)
        property int outerPad: root._cfg("aura.outer_padding", 14)
        property int border1: root._cfg("aura.border1", 2)
        property int border2: root._cfg("aura.border2", 1)
        property int border3: root._cfg("aura.border3", 1)
        property color borderColor: root.auraBorderColor(auraColor)
        property real borderOpacity: root._cfg("aura.border_opacity", 0.6)
        property real blurRadius: root._cfg("aura.blur_radius", 0)
        property bool borderEffectEnabled: root._cfg("aura.border_effect_enabled", true)
        property bool backdropEnabled: root._cfg("aura.backdrop_enabled", true)
        property color backdropColor: root._cfg("aura.backdrop_color", "#000000")
        property real backdropOpacity: root._cfg("aura.backdrop_opacity", 0.25)
        property int backdropPad: root._cfg("aura.backdrop_pad", 8)
        property real corePulse: 1.0
        property real bodyPulse: 1.0
        property real glowPulse: 1.0
        property real wispPulse: 1.0

        SequentialAnimation on corePulse {
            running: root.qmlPreviewEnabled && blueAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.75; to: 1.25; duration: 900 }
            NumberAnimation { from: 1.25; to: 0.85; duration: 700 }
            PauseAnimation { duration: 200 }
        }
        SequentialAnimation on bodyPulse {
            running: root.qmlPreviewEnabled && blueAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.7; to: 1.15; duration: 1200 }
            NumberAnimation { from: 1.15; to: 0.85; duration: 900 }
            PauseAnimation { duration: 300 }
        }
        SequentialAnimation on glowPulse {
            running: root.qmlPreviewEnabled && blueAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.6; to: 1.2; duration: 1600 }
            NumberAnimation { from: 1.2; to: 0.75; duration: 1200 }
            PauseAnimation { duration: 400 }
        }
        SequentialAnimation on wispPulse {
            running: root.qmlPreviewEnabled && blueAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.5; to: 1.1; duration: 1800 }
            NumberAnimation { from: 1.1; to: 0.7; duration: 1400 }
            PauseAnimation { duration: 450 }
        }

        Item {
            id: blueAuraContent
            anchors.fill: parent
            visible: true

        Rectangle {
            anchors.centerIn: parent
            width: parent.width + blueAura.backdropPad
            height: parent.height + blueAura.backdropPad
            radius: 10
            color: blueAura.backdropColor
            opacity: blueAura.backdropOpacity
            visible: blueAura.backdropEnabled
            z: -2
        }

        ParticleSystem {
            id: blueParticles
            running: root.qmlPreviewEnabled && blueAura.visible
            Item {
                id: blueNeonFrame
                visible: false
            }
        }

        ImageParticle {
            system: blueParticles
            groups: ["core"]
            source: root.flameParticleTex
            color: Qt.lighter(blueAura.auraColor, 1.7)
            colorVariation: root._aura("core.color_var", 0.04)
            alpha: root._aura("core.alpha", 0.98)
            alphaVariation: root._aura("core.alpha_var", 0.08)
            rotationVariation: root._aura("core.rot_var", 0)
        }

        ImageParticle {
            system: blueParticles
            groups: ["body"]
            source: root.flameParticleTex
            color: Qt.lighter(blueAura.auraColor, 1.25)
            colorVariation: root._aura("body.color_var", 0.06)
            alpha: root._aura("body.alpha", 0.85)
            alphaVariation: root._aura("body.alpha_var", 0.1)
            rotationVariation: root._aura("body.rot_var", 2)
        }

        ImageParticle {
            system: blueParticles
            groups: ["glow"]
            source: root.glowParticleTex
            color: blueAura.auraColor
            colorVariation: root._aura("glow.color_var", 0.08)
            alpha: root._aura("glow.alpha", 0.22)
            alphaVariation: root._aura("glow.alpha_var", 0.08)
            rotationVariation: root._aura("glow.rot_var", 6)
        }

        ImageParticle {
            system: blueParticles
            groups: ["wisps"]
            source: root.glowParticleTex
            color: blueAura.auraColor
            colorVariation: root._aura("wisps.color_var", 0.1)
            alpha: root._aura("wisps.alpha", 0.12)
            alphaVariation: root._aura("wisps.alpha_var", 0.06)
            rotationVariation: root._aura("wisps.rot_var", 6)
        }

        ImageParticle {
            system: blueParticles
            groups: ["spark"]
            source: root.sparkTex
            color: Qt.lighter(blueAura.auraColor, 1.35)
            colorVariation: root._aura("spark.color_var", 0.1)
            alpha: root._aura("spark.alpha", 0.2)
            alphaVariation: root._aura("spark.alpha_var", 0.08)
            rotationVariation: root._aura("spark.rot_var", 0)
        }

        Emitter {
            system: blueParticles
            group: "core"
            width: parent.width * 0.25
            height: parent.height * 0.22
            x: (parent.width - width) * 0.5
            y: parent.height * 0.44
            emitRate: root._cfg("aura.flame_emit", 12) * root._aura("core.emit_mul", 3.2) * blueAura.corePulse
            lifeSpan: root._aura("core.life", 1200)
            lifeSpanVariation: root._aura("core.life_var", 220)
            size: root._cfg("aura.flame_size", 20) * root._aura("core.size_mul", 0.5)
            sizeVariation: (root._cfg("aura.flame_size_var", 14) * root._aura("core.size_var_mul", 0.12)) + root._aura("core.size_var_add", 1)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("core.angle_var", 6); magnitude: root._aura("core.speed", 120); magnitudeVariation: root._aura("core.speed_var", 15) }
            acceleration: AngleDirection { angle: 90; angleVariation: root._aura("core.accel_var", 8); magnitude: root._aura("core.accel", 30); magnitudeVariation: root._aura("core.accel_mag_var", 12) }
        }

        Emitter {
            system: blueParticles
            group: "body"
            width: parent.width * 0.45
            height: parent.height * 0.35
            x: (parent.width - width) * 0.5
            y: parent.height * 0.38
            emitRate: root._cfg("aura.flame_emit", 12) * root._aura("body.emit_mul", 2.6) * blueAura.bodyPulse
            lifeSpan: root._aura("body.life", 1500)
            lifeSpanVariation: root._aura("body.life_var", 260)
            size: root._cfg("aura.flame_size", 20) * root._aura("body.size_mul", 0.7)
            sizeVariation: (root._cfg("aura.flame_size_var", 14) * root._aura("body.size_var_mul", 0.18)) + root._aura("body.size_var_add", 1)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("body.angle_var", 8); magnitude: root._aura("body.speed", 85); magnitudeVariation: root._aura("body.speed_var", 15) }
            acceleration: AngleDirection { angle: 90; angleVariation: root._aura("body.accel_var", 10); magnitude: root._aura("body.accel", 22); magnitudeVariation: root._aura("body.accel_mag_var", 12) }
        }

        Emitter {
            system: blueParticles
            group: "glow"
            width: parent.width * 0.6
            height: parent.height * 0.55
            x: (parent.width - width) * 0.5
            y: parent.height * 0.28
            emitRate: root._cfg("aura.smoke_emit", 6) * root._aura("glow.emit_mul", 0.6) * blueAura.glowPulse
            lifeSpan: root._aura("glow.life", 1700)
            lifeSpanVariation: root._aura("glow.life_var", 320)
            size: root._cfg("aura.smoke_size", 36) * root._aura("glow.size_mul", 0.6)
            sizeVariation: (root._cfg("aura.smoke_size_var", 20) * root._aura("glow.size_var_mul", 0.2)) + root._aura("glow.size_var_add", 2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("glow.angle_var", 8); magnitude: root._aura("glow.speed", 40); magnitudeVariation: root._aura("glow.speed_var", 12) }
        }

        Emitter {
            system: blueParticles
            group: "wisps"
            width: parent.width * 0.55
            height: parent.height * 0.55
            x: (parent.width - width) * 0.5
            y: parent.height * 0.30
            emitRate: root._cfg("aura.smoke_emit", 6) * root._aura("wisps.emit_mul", 0.35) * blueAura.wispPulse
            lifeSpan: root._aura("wisps.life", 1800)
            lifeSpanVariation: root._aura("wisps.life_var", 360)
            size: root._cfg("aura.smoke_size", 36) * root._aura("wisps.size_mul", 0.55)
            sizeVariation: (root._cfg("aura.smoke_size_var", 20) * root._aura("wisps.size_var_mul", 0.18)) + root._aura("wisps.size_var_add", 2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("wisps.angle_var", 7); magnitude: root._aura("wisps.speed", 32); magnitudeVariation: root._aura("wisps.speed_var", 10) }
        }

        Emitter {
            system: blueParticles
            group: "spark"
            width: parent.width * 0.6
            height: parent.height * 0.35
            x: (parent.width - width) * 0.5
            y: parent.height * 0.55
            emitRate: root._cfg("aura.spark_emit", 10) * root._aura("spark.emit_mul", 0.1)
            lifeSpan: root._aura("spark.life", 520)
            lifeSpanVariation: root._aura("spark.life_var", 360)
            size: root._cfg("aura.spark_size", 10) * root._aura("spark.size_mul", 0.6)
            sizeVariation: root._cfg("aura.spark_size_var", 8) * root._aura("spark.size_var_mul", 0.2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("spark.angle_var", 18); magnitude: root._aura("spark.speed", 150); magnitudeVariation: root._aura("spark.speed_var", 45) }
        }

        Turbulence {
            system: blueParticles
            groups: ["core", "body"]
            strength: root._cfg("aura.turbulence", 18) * root._aura("core.turb_mul", 0.15)
        }
        Turbulence {
            system: blueParticles
            groups: ["glow", "wisps", "spark"]
            strength: root._cfg("aura.turbulence", 18) * root._aura("glow.turb_mul", 0.35)
        }

        Item { visible: false }
        }

        Item { visible: false }

    }

    Rectangle {
        id: blueImgBox
        parent: scaledRoot
        property bool noOverlapFade: true
        color: (backend && backend.overlayPlayerMask === "square") ? "#1e1e1e" : "transparent"
        border.color: "transparent"
        border.width: 0
        radius: (backend && backend.overlayPlayerMask === "square") ? 2 : 0
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowBlueImg))
        opacity: (editMode && backend && !backend.overlayShowBlueImg) ? 0.25 : 1.0
        clip: false
        HoverHandler { id: blueImgHover }
        ToolTip.visible: blueImgHover.hovered
        ToolTip.text: "\uBE14\uB8E8 \uCD08\uC0C1\uD654"
        onVisibleChanged: { scheduleBoundsUpdate(); blueImgBoxFill.requestPaint(); blueImgBoxBorder.requestPaint() }
        property real jitterX: 0
        property real jitterY: 0
        property real splitX: 0
        property real splitY: 0
        transform: Translate { x: blueImgBox.jitterX; y: blueImgBox.jitterY }
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Canvas {
            id: blueImgBoxFill
            anchors.fill: parent
            z: 0
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                if (mask === "square") return
                var line = 2.0
                var inset = line * 0.5
                var w = Math.max(0, width - inset * 2)
                var h = Math.max(0, height - inset * 2)
                ctx.fillStyle = "#1e1e1e"
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(w, h) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(w, h) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                }
                ctx.fill()
            }
        }
        Item {
            id: blueImgMasked
            anchors.fill: parent
            z: 1
            property string imageSource: "image://players/blue?rev=" + (backend ? backend.blueImageRev : 0)
            property real shimmerPos: -0.5
            property real pulseOpacity: 0.8
            function requestPaint() { bluePortraitMask.requestPaint(); bluePortraitOverlay.requestPaint() }
            SequentialAnimation on shimmerPos {
                loops: Animation.Infinite
                running: backend && backend.blueWinStreak >= 3
                NumberAnimation { from: -0.5; to: 1.5; duration: 2500; easing.type: Easing.InOutSine }
                PauseAnimation { duration: 800 }
            }
            SequentialAnimation on pulseOpacity {
                loops: Animation.Infinite
                running: backend && backend.blueWinStreak >= 3
                NumberAnimation { from: 0.6; to: 1.0; duration: 1200; easing.type: Easing.InOutQuad }
                NumberAnimation { from: 1.0; to: 0.6; duration: 1200; easing.type: Easing.InOutQuad }
            }
            onShimmerPosChanged: bluePortraitOverlay.requestPaint()
            onPulseOpacityChanged: bluePortraitOverlay.requestPaint()
            Item {
                id: bluePortraitSource
                anchors.fill: parent
                visible: false
                layer.enabled: true
                layer.smooth: true
                layer.textureSize: Qt.size(Math.max(1, Math.ceil(width * 2.5)), Math.max(1, Math.ceil(height * 2.5)))
                Image {
                    source: blueImgMasked.imageSource
                    cache: false
                    asynchronous: true
                    smooth: true
                    mipmap: false
                    sourceSize.width: Math.max(1, Math.ceil(width * 2.5))
                    sourceSize.height: Math.max(1, Math.ceil(height * 2.5))
                    fillMode: Image.PreserveAspectCrop
                    width: parent.width * Math.max(0.5, root._cfg("portrait.zoom", 1.25))
                    height: parent.height * Math.max(0.5, root._cfg("portrait.zoom", 1.25))
                    x: (parent.width - width) * 0.5 + parent.width * root._cfg("portrait.offset_x", 0.0)
                    y: (parent.height - height) * 0.5 + parent.height * root._cfg("portrait.offset_y", -0.08)
                }
            }
            Canvas {
                id: bluePortraitMask
                anchors.fill: parent
                visible: false
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    ctx.fillStyle = "white"
                    ctx.beginPath()
                    if (mask === "circle") {
                        ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var cx = width * 0.5, cy = height * 0.5, rr = Math.min(width, height) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang), py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, width, height)
                    }
                    ctx.fill()
                }
                Component.onCompleted: requestPaint()
            }
            MultiEffect {
                anchors.fill: parent
                source: bluePortraitSource
                maskEnabled: true
                maskSource: bluePortraitMask
                antialiasing: true
            }
            Canvas {
                id: bluePortraitOverlay
                anchors.fill: parent
                z: 2
                visible: root.qmlPreviewEnabled && backend && (backend.blueWinStreak || 0) >= 3
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    if (!visible) return
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var cx = width * 0.5, cy = height * 0.5, rr = Math.min(width, height) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang), py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, width, height)
                    }
                    ctx.clip()
                    var vig = ctx.createLinearGradient(0, height * 0.4, 0, height)
                    vig.addColorStop(0, "transparent")
                    vig.addColorStop(1, "rgba(0,0,0,0.9)")
                    ctx.fillStyle = vig
                    ctx.fillRect(0, 0, width, height)
                    var sPos = blueImgMasked.shimmerPos * width
                    var shim = ctx.createLinearGradient(sPos - 15, 0, sPos + 15, 0)
                    shim.addColorStop(0, "transparent")
                    shim.addColorStop(0.5, "rgba(255,255,255,0.8)")
                    shim.addColorStop(1, "transparent")
                    ctx.globalCompositeOperation = "overlay"
                    ctx.fillStyle = shim
                    ctx.fillRect(0, 0, width, height)
                    ctx.restore()
                }
                onVisibleChanged: requestPaint()
            }
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueImgMasked.requestPaint() }
                function onEffectSettingsChanged() { blueImgMasked.requestPaint() }
                function onBlueImageRevChanged() { blueImgMasked.requestPaint() }
                function onBlueWinStreakChanged() { blueImgMasked.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueImgMasked.requestPaint() }
                function onHeightChanged() { blueImgMasked.requestPaint() }
            }
        }
        Canvas {
            id: blueHitFlashCanvas
            anchors.fill: parent
            z: 8.8
            opacity: root._blueHitFlash
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                var cx = width * 0.5
                var cy = height * 0.5
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(cx, cy, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                ctx.globalAlpha = 0.76
                ctx.fillStyle = "#fff2bd"
                ctx.fillRect(0, 0, width, height)
                ctx.globalAlpha = 1.0
                var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.62)
                g.addColorStop(0.0, "rgba(255,255,255,0.95)")
                g.addColorStop(0.42, "rgba(255,215,92,0.58)")
                g.addColorStop(1.0, "rgba(255,255,255,0)")
                ctx.fillStyle = g
                ctx.fillRect(0, 0, width, height)
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueHitFlashCanvas.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueHitFlashCanvas.requestPaint() }
                function onHeightChanged() { blueHitFlashCanvas.requestPaint() }
            }
        }
        Canvas {
            id: blueStunFlashCanvas
            anchors.fill: parent
            z: 9
            opacity: root._blueStunFlash
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                ctx.fillStyle = "white"
                ctx.fillRect(0, 0, width, height)
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueStunFlashCanvas.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueStunFlashCanvas.requestPaint() }
                function onHeightChanged() { blueStunFlashCanvas.requestPaint() }
            }
        }
        Canvas {
            id: blueHeavyImpactCanvas
            anchors.fill: parent
            z: 9.25
            opacity: root._blueHeavyImpact
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                var gx = width * 0.5
                var gy = height * 0.5
                var g = ctx.createRadialGradient(gx, gy, 0, gx, gy, Math.max(width, height) * 0.72)
                g.addColorStop(0.0, "rgba(255,255,255,0.92)")
                g.addColorStop(0.28, "rgba(250,204,21,0.72)")
                g.addColorStop(0.62, "rgba(249,115,22,0.36)")
                g.addColorStop(1.0, "rgba(239,68,68,0)")
                ctx.fillStyle = g
                ctx.fillRect(0, 0, width, height)
                ctx.lineWidth = Math.max(2, Math.min(width, height) * 0.05)
                ctx.strokeStyle = "rgba(254,240,138,0.95)"
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5 - ctx.lineWidth, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx2 = width * 0.5
                    var cy2 = height * 0.5
                    var rr2 = Math.min(width, height) * 0.5 - ctx.lineWidth
                    for (var j = 0; j < 6; j++) {
                        var a2 = (Math.PI / 3) * j - Math.PI / 6
                        var p2x = cx2 + rr2 * Math.cos(a2)
                        var p2y = cy2 + rr2 * Math.sin(a2)
                        if (j === 0) ctx.moveTo(p2x, p2y); else ctx.lineTo(p2x, p2y)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(ctx.lineWidth, ctx.lineWidth, width - ctx.lineWidth * 2, height - ctx.lineWidth * 2)
                }
                ctx.stroke()
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueHeavyImpactCanvas.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueHeavyImpactCanvas.requestPaint() }
                function onHeightChanged() { blueHeavyImpactCanvas.requestPaint() }
            }
        }
        Canvas {
            id: blueImpactCanvas
            anchors.fill: parent
            z: 9.5
            visible: root.qmlPreviewEnabled && (root._blueKdOverlay > 0.01 || root._blueTkoOverlay > 0.01)
            opacity: Math.max(root._blueKdOverlay, root._blueTkoOverlay)
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                var tko = root._blueTkoOverlay > root._blueKdOverlay
                ctx.fillStyle = tko ? "rgb(6, 8, 12)" : "rgb(0, 12, 32)"
                ctx.fillRect(0, 0, width, height)
                ctx.lineWidth = Math.max(2, Math.min(width, height) * 0.045)
                ctx.strokeStyle = tko ? "rgba(255, 255, 255, 0.95)" : "rgba(147, 197, 253, 0.95)"
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5 - ctx.lineWidth, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx2 = width * 0.5
                    var cy2 = height * 0.5
                    var rr2 = Math.min(width, height) * 0.5 - ctx.lineWidth
                    for (var j = 0; j < 6; j++) {
                        var a2 = (Math.PI / 3) * j - Math.PI / 6
                        var p2x = cx2 + rr2 * Math.cos(a2)
                        var p2y = cy2 + rr2 * Math.sin(a2)
                        if (j === 0) ctx.moveTo(p2x, p2y); else ctx.lineTo(p2x, p2y)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(ctx.lineWidth, ctx.lineWidth, width - ctx.lineWidth * 2, height - ctx.lineWidth * 2)
                }
                ctx.stroke()
                ctx.restore()
            }
            onVisibleChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueImpactCanvas.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueImpactCanvas.requestPaint() }
                function onHeightChanged() { blueImpactCanvas.requestPaint() }
            }
        }
        Text {
            anchors.centerIn: parent
            z: 10
            text: root._blueImpactLabel
            visible: root.qmlPreviewEnabled && text !== "" && (root._blueKdOverlay > 0.01 || root._blueTkoOverlay > 0.01)
            color: root._blueTkoOverlay > root._blueKdOverlay ? "#ffffff" : "#dbeafe"
            font.family: "Arial Black"
            font.bold: true
            font.pixelSize: Math.max(18, Math.min(parent.width, parent.height) * 0.26)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            style: Text.Outline
            styleColor: root._blueTkoOverlay > root._blueKdOverlay ? "#7f1d1d" : "#1e3a8a"
        }
        Rectangle {
            id: blueDamageBadge
            parent: scaledRoot
            z: 10
            width: Math.max(58, blueDamageText.implicitWidth + 16)
            height: Math.max(22, blueImgBox.height * 0.22)
            x: blueImgBox.x + (blueImgBox.width - width) * 0.5
            y: blueImgBox.y + blueImgBox.height + 4
            radius: 8
            color: "transparent"
            border.color: "transparent"
            border.width: 0
            visible: root.qmlPreviewEnabled && blueImgBox.visible && backend && backend.blueDamageText !== ""
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            ToolTip.visible: blueDamageHover.hovered
            ToolTip.text: backend ? backend.blueLogMetaText : ""
            HoverHandler { id: blueDamageHover }
            Text {
                id: blueDamageText
                anchors.centerIn: parent
                text: backend ? backend.blueDamageText : ""
                color: "#e5e7eb"
                font.bold: true
                font.pixelSize: Math.max(13, Math.min(18, parent.height * 0.68))
                font.family: "Arial Black"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                style: Text.Outline
                styleColor: "#020617"
            }
        }
        Rectangle {
            id: blueComboBadge
            parent: scaledRoot
            z: 13
            property bool active: false
            width: Math.max(122, blueComboHit.implicitWidth + 34, blueComboDamage.implicitWidth + 28)
            height: Math.max(46, blueNameBox.height * 1.02)
            x: blueImgBox.x + (blueImgBox.width - width) * 0.5
            y: Math.max(0, blueImgBox.y - height - Math.max(12, blueImgBox.height * 0.12))
            radius: Math.max(4, height * 0.12)
            visible: root.qmlPreviewEnabled && active && backend && backend.blueComboHitText !== ""
            color: "transparent"
            border.color: "transparent"
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            Timer {
                id: blueComboHideTimer
                interval: 2000
                repeat: false
                onTriggered: {
                    blueComboBadge.active = false
                    if (backend) backend.clear_combo_display("blue")
                }
            }
            Connections {
                target: backend
                function onBlueComboHitTextChanged() {
                    if (backend.blueComboHitText !== "") {
                        blueComboBadge.active = true
                        blueComboHideTimer.restart()
                    } else {
                        blueComboBadge.active = false
                        blueComboHideTimer.stop()
                    }
                }
            }
            Text {
                id: blueComboHit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 2
                text: backend ? backend.blueComboHitText : ""
                color: text === "COUNTER" ? "#ffd54a" : "#dbeafe"
                font.family: "Arial Black"
                font.bold: true
                font.italic: true
                font.pixelSize: Math.max(15, parent.height * 0.38)
                style: Text.Outline
                styleColor: "#0f172a"
            }
            Text {
                id: blueComboDamage
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: blueComboHit.bottom
                anchors.topMargin: -1
                text: backend ? backend.blueComboDamageText : ""
                color: blueComboHit.text === "COUNTER" ? "#ffffff" : "#ffe8a3"
                font.family: "Arial Black"
                font.bold: true
                font.italic: true
                font.pixelSize: Math.max(13, parent.height * 0.30)
                style: Text.Outline
                styleColor: "#7c2d12"
            }
        }
        Rectangle {
            id: bluePunishmentBadge
            parent: scaledRoot
            z: 10
            width: blueNameBox.width
            height: Math.max(14, Math.min(22, blueNameBox.height * 0.46))
            x: blueNameBox.x
            y: blueNameBox.y + blueNameBox.height + 4
            radius: Math.max(3, height * 0.35)
            color: "transparent"
            border.color: "transparent"
            border.width: 0
            visible: root.qmlPreviewEnabled && blueImgBox.visible && backend && backend.bluePunishmentText !== ""
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            ToolTip.visible: bluePunishmentHover.hovered
            ToolTip.text: backend ? (backend.bluePunishmentText + "\n" + backend.blueLogMetaText) : ""
            HoverHandler { id: bluePunishmentHover }
            Canvas {
                id: blueHpMetalCanvas
                anchors.fill: parent
                z: 1
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var bevel = Math.max(5, height * 0.55)
                    var pad = Math.max(2, height * 0.18)
                    function barPath(inset) {
                        var x0 = inset, y0 = inset, x1 = width - inset, y1 = height - inset
                        var b = Math.max(2, bevel - inset)
                        ctx.beginPath()
                        ctx.moveTo(x0, y0)
                        ctx.lineTo(x1 - b, y0)
                        ctx.lineTo(x1, y1)
                        ctx.lineTo(x0 + b, y1)
                        ctx.closePath()
                    }
                    function framePath(inset) {
                        var x0 = inset, y0 = inset, x1 = width - inset, y1 = height - inset
                        var b = Math.max(2, bevel - inset)
                        ctx.beginPath()
                        ctx.moveTo(x0, y0)
                        ctx.lineTo(x1 - b, y0)
                        ctx.lineTo(x1, y1)
                        ctx.lineTo(x0 + b, y1)
                        ctx.closePath()
                    }
                    framePath(0.5)
                    var frame = ctx.createLinearGradient(0, 0, 0, height)
                    frame.addColorStop(0.0, "#dbeafe")
                    frame.addColorStop(0.18, "#5ea3ff")
                    frame.addColorStop(0.50, "#111827")
                    frame.addColorStop(0.78, "#60a5fa")
                    frame.addColorStop(1.0, "#eff6ff")
                    ctx.fillStyle = frame
                    ctx.fill()
                    ctx.save()
                    barPath(pad)
                    ctx.clip()
                    var bg = ctx.createLinearGradient(0, 0, 0, height)
                    bg.addColorStop(0, "#111827")
                    bg.addColorStop(1, "#020617")
                    ctx.fillStyle = bg
                    ctx.fillRect(0, 0, width, height)
                    var usableX = pad + 1
                    var usableW = Math.max(0, width - pad * 2 - 2)
                    var baseW = usableW * root.hpBaseRatio("blue")
                    var curW = usableW * root.hpCurrentRatio("blue")
                    var ghostW = Math.max(0, baseW - curW)
                    var rightX = usableX + usableW
                    var baseX = rightX - baseW
                    var curX = rightX - curW
                    if (baseW > 0) {
                        var baseGrad = ctx.createLinearGradient(0, 0, 0, height)
                        baseGrad.addColorStop(0, "#334155")
                        baseGrad.addColorStop(1, "#0f172a")
                        ctx.fillStyle = baseGrad
                        ctx.fillRect(baseX, pad + 1, baseW, height - pad * 2 - 2)
                    }
                    if (ghostW > 0) {
                        var ghostGrad = ctx.createLinearGradient(0, 0, 0, height)
                        ghostGrad.addColorStop(0, "#fed7aa")
                        ghostGrad.addColorStop(0.45, root.hpMidDamageColor("blue"))
                        ghostGrad.addColorStop(1, "#7c2d12")
                        ctx.fillStyle = ghostGrad
                        ctx.fillRect(baseX, pad + 1, ghostW, height - pad * 2 - 2)
                    }
                    if (curW > 0) {
                        var hpGrad = ctx.createLinearGradient(0, 0, 0, height)
                        hpGrad.addColorStop(0, "#ecfeff")
                        hpGrad.addColorStop(0.16, "#a7f3d0")
                        hpGrad.addColorStop(0.52, root.hpBarColor("blue"))
                        hpGrad.addColorStop(1, "#064e3b")
                        ctx.fillStyle = hpGrad
                        ctx.fillRect(curX, pad + 1, curW, height - pad * 2 - 2)
                        ctx.fillStyle = "rgba(255,255,255,0.45)"
                        ctx.fillRect(curX + 2, pad + 2, Math.max(0, curW - 4), Math.max(1, (height - pad * 2) * 0.22))
                    }
                    var shine = ctx.createLinearGradient(0, 0, width, 0)
                    shine.addColorStop(0, "rgba(255,255,255,0)")
                    shine.addColorStop(0.45, "rgba(255,255,255,0.12)")
                    shine.addColorStop(0.52, "rgba(255,255,255,0.32)")
                    shine.addColorStop(0.62, "rgba(255,255,255,0.05)")
                    shine.addColorStop(1, "rgba(255,255,255,0)")
                    ctx.fillStyle = shine
                    ctx.fillRect(0, 0, width, height)
                    ctx.restore()
                    framePath(0.5)
                    ctx.lineWidth = 1
                    ctx.strokeStyle = "rgba(255,255,255,0.65)"
                    ctx.stroke()
                }
                Connections {
                    target: backend
                    function onBluePunishmentMidChanged() { blueHpMetalCanvas.requestPaint() }
                    function onBluePunishmentLongChanged() { blueHpMetalCanvas.requestPaint() }
                }
                Connections {
                    target: bluePunishmentBadge
                    function onWidthChanged() { blueHpMetalCanvas.requestPaint() }
                    function onHeightChanged() { blueHpMetalCanvas.requestPaint() }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                z: 3
                visible: root.qmlPreviewEnabled && root._blueHpDownOverlay > 0.01
                opacity: root._blueHpDownOverlay
                color: root._blueHpDownLabel === "TKO" ? Qt.rgba(30 / 255, 6 / 255, 6 / 255, 0.94) : Qt.rgba(4 / 255, 8 / 255, 18 / 255, 0.92)
                border.color: root._blueHpDownLabel === "TKO" ? "#ffffff" : "#facc15"
                border.width: 1
                clip: true
                Repeater {
                    model: 9
                    Rectangle {
                        width: 10
                        height: bluePunishmentBadge.height * 2.4
                        x: (index * 20 + root._blueHpDownStripe * 40) - 36
                        y: -bluePunishmentBadge.height * 0.7
                        rotation: 28
                        color: root._blueHpDownLabel === "TKO" ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(250 / 255, 204 / 255, 21 / 255, 0.24)
                    }
                }
            }
            Text {
                id: bluePunishmentText
                z: 4
                anchors.centerIn: parent
                text: root._blueHpDownOverlay > 0.01 ? root._blueHpDownLabel : ""
                color: "#ffffff"
                opacity: parent.height >= 13 && root._blueHpDownOverlay > 0.01 ? 1.0 : 0.0
                font.bold: true
                font.pixelSize: root._blueHpDownOverlay > 0.01 ? Math.max(10, parent.height * 0.86) : 9
                style: Text.Outline
                styleColor: "#000000"
            }
        }
        Row {
            id: blueKnockdownDots
            parent: scaledRoot
            z: 11
            spacing: Math.max(3, bluePunishmentBadge.height * 0.18)
            x: bluePunishmentBadge.x + bluePunishmentBadge.width - width
            y: bluePunishmentBadge.y + bluePunishmentBadge.height + Math.max(2, bluePunishmentBadge.height * 0.16)
            visible: root.qmlPreviewEnabled && bluePunishmentBadge.visible
            Repeater {
                model: 3
                Item {
                    property real displaySize: Math.max(13, Math.min(19, bluePunishmentBadge.height * 0.92))
                    width: displaySize
                    height: displaySize
                    property bool filled: backend && index >= Math.min(3, backend.blueRoundKnockdowns)
                    onFilledChanged: blueKnockdownDotCanvas.requestPaint()
                    onDisplaySizeChanged: blueKnockdownDotCanvas.requestPaint()
                    Canvas {
                    id: blueKnockdownDotCanvas
                    property real renderScale: 3.0
                    width: parent.displaySize * renderScale
                    height: width
                    scale: 1.0 / renderScale
                    transformOrigin: Item.TopLeft
                    renderTarget: Canvas.Image
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    Component.onCompleted: requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var cx = width * 0.5
                        var cy = height * 0.5
                        var r = Math.min(width, height) * 0.38
                        ctx.save()

                        if (parent.filled) {
                            var glowSteps = [
                                [1.42, "rgba(255,230,128,0.12)"],
                                [1.25, "rgba(245,200,72,0.18)"],
                                [1.08, "rgba(255,244,176,0.26)"]
                            ]
                            for (var g = 0; g < glowSteps.length; ++g) {
                                ctx.fillStyle = glowSteps[g][1]
                                ctx.beginPath()
                                ctx.arc(cx, cy, r * glowSteps[g][0], 0, Math.PI * 2)
                                ctx.fill()
                            }
                        }

                        var socket = ctx.createRadialGradient(cx - r * 0.18, cy - r * 0.22, r * 0.1, cx, cy, r * 1.34)
                        socket.addColorStop(0.00, "#273142")
                        socket.addColorStop(0.45, "#080b12")
                        socket.addColorStop(0.72, "#02040a")
                        socket.addColorStop(1.00, "#000000")
                        ctx.fillStyle = socket
                        ctx.beginPath()
                        ctx.arc(cx, cy, r * 1.16, 0, Math.PI * 2)
                        ctx.fill()

                        var rim = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r)
                        rim.addColorStop(0.00, parent.filled ? "#fff8d6" : "#d7dee9")
                        rim.addColorStop(0.20, parent.filled ? "#d4af37" : "#64748b")
                        rim.addColorStop(0.46, "#111827")
                        rim.addColorStop(0.74, "#020617")
                        rim.addColorStop(1.00, parent.filled ? "#fffbe6" : "#334155")
                        ctx.fillStyle = rim
                        ctx.beginPath()
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                        ctx.fill()

                        var inner = r * 0.68
                        var fill = ctx.createRadialGradient(cx - inner * 0.36, cy - inner * 0.42, inner * 0.08, cx, cy, inner * 1.08)
                        if (parent.filled) {
                            fill.addColorStop(0.00, "#fffdf0")
                            fill.addColorStop(0.16, "#fff1a8")
                            fill.addColorStop(0.42, "#ffd54a")
                            fill.addColorStop(0.72, "#c9971a")
                            fill.addColorStop(1.00, "#6b4e05")
                        } else {
                            fill.addColorStop(0.00, "#475569")
                            fill.addColorStop(0.36, "#1e293b")
                            fill.addColorStop(0.74, "#0f172a")
                            fill.addColorStop(1.00, "#020617")
                        }
                        ctx.fillStyle = fill
                        ctx.beginPath()
                        ctx.arc(cx, cy, inner, 0, Math.PI * 2)
                        ctx.fill()

                        var cap = ctx.createRadialGradient(cx - inner * 0.35, cy - inner * 0.42, inner * 0.02, cx - inner * 0.25, cy - inner * 0.34, inner * 0.72)
                        cap.addColorStop(0.0, "rgba(255,255,255,0.82)")
                        cap.addColorStop(0.34, "rgba(255,255,255,0.20)")
                        cap.addColorStop(1.0, "rgba(255,255,255,0)")
                        ctx.fillStyle = cap
                        ctx.beginPath()
                        ctx.arc(cx - inner * 0.22, cy - inner * 0.32, inner * 0.52, 0, Math.PI * 2)
                        ctx.fill()

                        ctx.strokeStyle = parent.filled ? "rgba(255,255,255,0.92)" : "rgba(203,213,225,0.38)"
                        ctx.lineWidth = 1
                        ctx.beginPath()
                        ctx.arc(cx, cy, r - 0.5, 0, Math.PI * 2)
                        ctx.stroke()
                        ctx.restore()
                    }
                    }
                    Connections {
                        target: backend
                        function onBlueRoundKnockdownsChanged() { blueKnockdownDotCanvas.requestPaint() }
                    }
                }
            }
        }
        Image {
            id: blueNameplate
            parent: scaledRoot
            z: blueImgBox.z + 1
            property string npPath: root._nameplatePath(backend ? backend.blueWinStreak : 0)
            property string npSide: root._cfg("nameplates.side_blue", "left")
            visible: root.qmlPreviewEnabled && blueImgBox.visible && npPath !== ""
            width: root._cfg("nameplates.width", 110) * root._cfg("nameplates.scale", 1.0)
            height: root._cfg("nameplates.height", 30) * root._cfg("nameplates.scale", 1.0)
            x: npSide === "right"
                ? (blueImgBox.x + blueImgBox.width + root._cfg("nameplates.gap", 6))
                : (blueImgBox.x - width - root._cfg("nameplates.gap", 6))
            y: blueImgBox.y + (blueImgBox.height - height) * 0.5
            source: (npPath && backend) ? backend.resolve_asset_url(npPath) : ""
            fillMode: Image.PreserveAspectFit
            smooth: true
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            HoverHandler { id: blueNameplateHover }
            ToolTip.visible: blueNameplateHover.hovered
            ToolTip.text: "\uBE14\uB8E8 \uC5F0\uC2B9 \uBA85\uCC30 \uC774\uBBF8\uC9C0 (\uC5F0\uC2B9 \uB2E8\uACC4\uC5D0 \uB530\uB77C \uD45C\uC2DC)"
            // Nameplates should not resize the overlay window.
        }
        Canvas {
            property real line: 2.0
            property real shimmerPhase: 0.0
            width: parent.width + line * 2
            height: parent.height + line * 2
            x: -line
            y: -line
            z: 2
            renderTarget: Canvas.Image
            Timer {
                interval: 40
                repeat: true
                running: root.qmlPreviewEnabled && blueImgBox.visible
                onTriggered: {
                    blueImgBoxBorder.shimmerPhase = (blueImgBoxBorder.shimmerPhase + 0.02) % 1.0
                    blueImgBoxBorder.requestPaint()
                }
            }
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                var line = blueImgBoxBorder.line
                var baseW = parent.width
                var baseH = parent.height
                var cx = line + baseW * 0.5
                var cy = line + baseH * 0.5
                ctx.lineWidth = line
                var p = blueImgBoxBorder.shimmerPhase
                var s = Math.max(0.0, Math.min(1.0, p))
                var ang = -Math.PI * 2 * s
                var vx = Math.cos(ang)
                var vy = Math.sin(ang)
                var len = Math.max(width, height)
                var gx1 = cx - vx * len
                var gy1 = cy - vy * len
                var gx2 = cx + vx * len
                var gy2 = cy + vy * len
                var g = ctx.createLinearGradient(gx1, gy1, gx2, gy2)
                g.addColorStop(0.0, "#4a4f55")
                g.addColorStop(0.35, "#7c838b")
                g.addColorStop(0.5, "#f0f3f6")
                g.addColorStop(0.65, "#8b939c")
                g.addColorStop(1.0, "#4a4f55")
                ctx.strokeStyle = g
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(baseW, baseH) * 0.5 + line * 0.5
                    ctx.arc(cx, cy, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var rr = Math.min(baseW, baseH) * 0.5 + line * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(line * 0.5, line * 0.5, baseW + line, baseH + line)
                }
                ctx.stroke()
            }
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { blueImgBoxBorder.requestPaint(); blueImgBoxFill.requestPaint() }
            }
            Connections {
                target: backend
                function onBlueImageRevChanged() { blueImgBoxBorder.requestPaint(); blueImgBoxFill.requestPaint() }
            }
            Connections {
                target: blueImgBox
                function onWidthChanged() { blueImgBoxBorder.requestPaint(); blueImgBoxFill.requestPaint() }
                function onHeightChanged() { blueImgBoxBorder.requestPaint(); blueImgBoxFill.requestPaint() }
            }
            id: blueImgBoxBorder
        }
        Item {
            id: blueInnerFx
            anchors.fill: parent
            clip: true
            visible: root.qmlPreviewEnabled && backend && backend.blueWinStreak >= 3
            z: 2
            Item {
                id: blueInnerFxContent
                anchors.fill: parent
            Canvas {
                id: blueDust
                anchors.fill: parent
                visible: root.qmlPreviewEnabled && root._cfg("inner.dust.enabled", true) && backend && (backend.blueWinStreak || 0) >= root._cfg("inner.dust.min", 3)
                opacity: root._cfg("inner.dust.opacity", 0.12)
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height)
                    ctx.save(); ctx.beginPath(); var m = (backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    ctx.fillStyle = "rgba(255,255,255,0.15)"
                    for (var i=0; i<15; i++) {
                        ctx.beginPath(); ctx.arc(Math.random()*width, Math.random()*height, 0.5+Math.random(), 0, 6.28)
                        ctx.fill()
                    }
                    ctx.restore()
                }
            }
            Timer {
                interval: root._cfg("inner.dust.interval", 140)
                repeat: true
                running: root.qmlPreviewEnabled && blueInnerFx.visible && blueDust.visible
                onTriggered: blueDust.requestPaint()
            }
            Canvas {
                id: blueHUD
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.hud.enabled", true) && backend && backend.blueWinStreak >= root._cfg("inner.hud.min", 6)
                property real rot: 0
                RotationAnimation on rot { from: 0; to: 360; duration: root._cfg("inner.hud.speed", 10000); loops: Animation.Infinite; running: root.qmlPreviewEnabled && blueHUD.visible }
                onRotChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    
                    ctx.translate(width*0.5, height*0.5);
                    var hudAlpha = root._cfg("inner.hud.opacity", 0.5)
                    ctx.strokeStyle = "rgba(147, 197, 253, " + hudAlpha + ")"; ctx.lineWidth = 1.5
                    // Inner HUD Arc
                    ctx.save(); ctx.rotate(rot*Math.PI/180)
                    ctx.beginPath(); ctx.arc(0, 0, width*0.35, 0, 1.8); ctx.stroke()
                    ctx.beginPath(); ctx.arc(0, 0, width*0.35, Math.PI, Math.PI+1.8); ctx.stroke(); ctx.restore()
                    // Outer HUD Arc (Opposite)
                    ctx.save(); ctx.rotate(-rot*0.6*Math.PI/180)
                    ctx.strokeStyle = "rgba(147, 197, 253, " + (hudAlpha * 0.6) + ")"
                    ctx.beginPath(); ctx.arc(0, 0, width*0.42, 0.5, 2.5); ctx.stroke()
                    ctx.beginPath(); ctx.arc(0, 0, width*0.42, Math.PI+0.5, Math.PI+2.5); ctx.stroke(); ctx.restore()
                    
                    ctx.restore()
                }
            }
            Canvas {
                id: blueElectricBits
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.electric.enabled", true) && backend && backend.blueWinStreak >= root._cfg("inner.electric.min", 9)
                property var bolts: []
                Timer {
                    interval: root._cfg("inner.electric.interval", 100); repeat: true; running: root.qmlPreviewEnabled && blueElectricBits.visible
                    onTriggered: {
                        var b = []; if (Math.random() > 0.4) {
                            var w = parent.width, h = parent.height
                            var x1 = Math.random()*w, y1 = Math.random()*h
                            var x2 = x1 + (Math.random()-0.5)*w*0.8, y2 = y1 + (Math.random()-0.5)*h*0.8
                            var opMin = root._cfg("inner.electric.opacity_min", 0.3)
                            var opMax = root._cfg("inner.electric.opacity_max", 0.9)
                            if (opMax < opMin) { var tmp = opMax; opMax = opMin; opMin = tmp }
                            var op = opMin + Math.random() * Math.max(0, opMax - opMin)
                            b.push({x1:x1, y1:y1, x2:x2, y2:y2, op: op})
                        }
                        parent.bolts = b; parent.requestPaint()
                    }
                }
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); if (bolts.length===0) return
                    ctx.save(); ctx.beginPath(); var m = (backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    ctx.strokeStyle = "#cfe4ff"; ctx.lineWidth = 1.8;
                    for (var i=0; i<bolts.length; i++) {
                        var b = bolts[i]; ctx.globalAlpha = b.op; ctx.beginPath(); ctx.moveTo(b.x1, b.y1)
                        var segs = 5, cx = b.x1, cy = b.y1
                        for (var j=1; j<=segs; j++) {
                            cx += (b.x2-b.x1)/segs + (Math.random()-0.5)*20
                            cy += (b.y2-b.y1)/segs + (Math.random()-0.5)*20
                            ctx.lineTo(cx, cy)
                        }
                        ctx.stroke()
                    }
                    ctx.restore()
                }
            }
            Canvas {
                id: blueNovaPulse
                anchors.fill: parent
                renderTarget: Canvas.Image
                property real energy: 0; property real shock: 0
                visible: root.qmlPreviewEnabled && root._cfg("inner.core.enabled", true) && backend && backend.blueWinStreak >= root._cfg("inner.core.min", 12)
                ParallelAnimation {
                    running: root.qmlPreviewEnabled && blueNovaPulse.visible; loops: Animation.Infinite
                    SequentialAnimation {
                        NumberAnimation { target: blueNovaPulse; property: "energy"; from: 0; to: 1; duration: root._cfg("inner.core.period", 900) * 0.28; easing.type: Easing.InSine }
                        NumberAnimation { target: blueNovaPulse; property: "energy"; from: 1; to: 0; duration: root._cfg("inner.core.period", 900) * 0.72; easing.type: Easing.OutCubic }
                        PauseAnimation { duration: root._cfg("inner.core.period", 900) * 0.56 }
                    }
                    SequentialAnimation {
                        PauseAnimation { duration: 230 }
                        NumberAnimation { target: blueNovaPulse; property: "shock"; from: 0; to: 1.2; duration: 900; easing.type: Easing.OutExpo }
                    }
                }
                onEnergyChanged: {
                    if (energy > 0.8) { blueImgBox.jitterX = (Math.random()-0.5)*4; blueImgBox.jitterY = (Math.random()-0.5)*4 }
                    else { blueImgBox.jitterX = 0; blueImgBox.jitterY = 0 }
                    requestPaint()
                }
                onShockChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    
                    var cx=width*0.5, cy=height*0.5
                    if(energy > 0) {
                        var maxAlpha = root._cfg("inner.core.opacity_max", 0.5)
                        var coreSize = root._cfg("inner.core.size", 0.35)
                        ctx.globalAlpha = energy * maxAlpha; ctx.fillStyle = "white"; ctx.fillRect(0,0,width,height)
                        var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, width * coreSize * energy)
                        g.addColorStop(0, "rgba(255,255,255,1)")
                        g.addColorStop(0.3, "rgba(96,165,250,0.8)")
                        g.addColorStop(1, "transparent")
                        ctx.globalAlpha = 1.0; ctx.fillStyle = g; ctx.fillRect(0,0,width,height)
                    }
                    if(shock > 0 && shock < 1) {
                        ctx.strokeStyle = "rgba(255,255,255,"+(1-shock)+")"; ctx.lineWidth = 3
                        ctx.beginPath(); ctx.arc(cx, cy, width*0.5*shock, 0, 6.28); ctx.stroke()
                    }
                    ctx.restore()
                }
            }

            Canvas {
                id: blueChronoRift
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.chrono.enabled", true) && backend && backend.blueWinStreak >= root._cfg("inner.chrono.min", 30)
                property real p: 0
                NumberAnimation on p { from: 0; to: 1; duration: root._cfg("inner.chrono.speed", 1500); loops: Animation.Infinite; running: root.qmlPreviewEnabled && blueChronoRift.visible }
                onPChanged: {
                    if (p > 0.9) { blueImgBox.jitterX = (Math.random()-0.5)*8; blueImgBox.jitterY = (Math.random()-0.5)*8 }
                    requestPaint()
                }
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    var chronoAlpha = root._cfg("inner.chrono.opacity", 1.0)
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    var cx=width*0.5, cy=height*0.5
                    
                    // 1. Divine Singularity (Center)
                    var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, width*0.5)
                    g.addColorStop(0, "rgba(0,0,0,"+(p*0.9*chronoAlpha)+")")
                    g.addColorStop(0.2, "rgba(59,130,246,"+(p*0.6*chronoAlpha)+")")
                    g.addColorStop(0.4, "rgba(251,191,36,"+(p*0.4*chronoAlpha)+")") // Golden touch
                    g.addColorStop(0.6, "transparent")
                    ctx.fillStyle = g; ctx.fillRect(0,0,width,height)
                    
                    // 2. Divine Halo (Rotating Ring)
                    ctx.strokeStyle = "rgba(251,191,36,"+((0.3 + p*0.4)*chronoAlpha)+")"; ctx.lineWidth = 2.5; 
                    ctx.beginPath(); ctx.arc(cx, cy, width*0.45, p*6.28, p*6.28 + 2.5); ctx.stroke()
                    ctx.beginPath(); ctx.arc(cx, cy, width*0.45, p*6.28 + Math.PI, p*6.28 + Math.PI + 2.5); ctx.stroke()
                    
                    // 3. Divine Rays
                    ctx.strokeStyle = "rgba(255,255,255,"+((1-p)*chronoAlpha)+")"; ctx.lineWidth = 1; ctx.globalAlpha = (1-p) * chronoAlpha
                    for(var i=0; i<10; i++) {
                        var a = (i/10)*6.28 + p*0.5; var r1 = width*0.6, r2 = width*0.05
                        ctx.beginPath(); ctx.moveTo(cx+Math.cos(a)*r1, cy+Math.sin(a)*r1); ctx.lineTo(cx+Math.cos(a)*r2, cy+Math.sin(a)*r2); ctx.stroke()
                    }
                    
                    // 4. Ether Glimmer (Stars)
                    ctx.fillStyle = "white"; ctx.globalAlpha = p * 0.6 * chronoAlpha
                    for(var j=0; j<10; j++) {
                        var sx = (Math.sin(p*6.28 + j)*0.4 + 0.5)*width, sy = (Math.cos(p*6.28 + j*1.5)*0.4 + 0.5)*height
                        ctx.beginPath(); ctx.arc(sx, sy, 1, 0, 6.28); ctx.fill()
                    }
                    ctx.restore()
                }
            }

            }
        }
        Item {
            id: blueBurst
            anchors.fill: parent
            visible: false
            z: 5
            transform: Translate { x: blueImgBox.jitterX; y: blueImgBox.jitterY }
            Canvas {
                id: blueBurstMask
                anchors.fill: parent
                renderTarget: Canvas.Image
                property real flashOpacity: 0.0
                property real bloomOpacity: 0.0
                onPaint: {
                    if (width <= 0 || height <= 0) return
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var w = width
                    var h = height
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        var r = Math.min(w, h) * 0.5
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var rr = Math.min(w, h) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang)
                            var py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, w, h)
                    }
                    ctx.clip()

                    if (blueBurstMask.flashOpacity > 0.0) {
                        ctx.globalAlpha = blueBurstMask.flashOpacity
                        ctx.fillStyle = "#fff8e6"
                        ctx.fillRect(0, 0, w, h)
                    }
                    if (blueBurstMask.bloomOpacity > 0.0) {
                        ctx.globalAlpha = blueBurstMask.bloomOpacity
                        var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.6)
                        g.addColorStop(0.0, "#fff5dc")
                        g.addColorStop(0.6, Qt.lighter(root.auraColorFor(backend ? backend.blueWinStreak : 0), 1.6))
                        g.addColorStop(1.0, "rgba(255,255,255,0)")
                        ctx.fillStyle = g
                        ctx.fillRect(0, 0, w, h)
                    }
                    ctx.restore()
                }
                onFlashOpacityChanged: requestPaint()
                onBloomOpacityChanged: requestPaint()
            }
            Rectangle {
                id: blueRingBurst
                anchors.centerIn: parent
                width: parent.width * 0.6
                height: parent.height * 0.6
                radius: Math.min(width, height) / 2
                color: "transparent"
                border.color: "#ffe7b0"
                border.width: 3
                opacity: 0
                scale: 0.6
            }
            Rectangle {
                id: blueBeam1
                width: parent.width * 1.6
                height: 4
                color: "#ffe9b8"
                opacity: 0
                anchors.centerIn: parent
                rotation: 12
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: blueBeam2
                width: parent.width * 1.4
                height: 3
                color: "#fff4c2"
                opacity: 0
                anchors.centerIn: parent
                rotation: -18
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: blueBeam3
                width: parent.width * 1.8
                height: 2
                color: "#ffffff"
                opacity: 0
                anchors.centerIn: parent
                rotation: 32
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: blueHexRing
                anchors.centerIn: parent
                width: parent.width * 0.8
                height: parent.height * 0.8
                radius: 6
                color: "transparent"
                border.color: "#fff0c7"
                border.width: 2
                opacity: 0
                rotation: 15
                scale: 0.7
            }
        }
        SequentialAnimation {
            id: blueBurstAnim
            running: false
            onStarted: blueBurst.visible = true
            onStopped: blueBurst.visible = false
            ParallelAnimation {
                NumberAnimation { target: blueBurstMask; property: "flashOpacity"; from: 0.0; to: 1.0; duration: 70 }
                NumberAnimation { target: blueBurstMask; property: "bloomOpacity"; from: 0.0; to: 0.8; duration: 110 }
                NumberAnimation { target: blueRingBurst; property: "opacity"; from: 0.0; to: 0.9; duration: 130 }
                NumberAnimation { target: blueRingBurst; property: "scale"; from: 0.6; to: 1.35; duration: 240 }
                NumberAnimation { target: blueHexRing; property: "opacity"; from: 0.0; to: 0.7; duration: 150 }
                NumberAnimation { target: blueHexRing; property: "scale"; from: 0.7; to: 1.2; duration: 260 }
                NumberAnimation { target: blueBeam1; property: "opacity"; from: 0.0; to: 0.85; duration: 90 }
                NumberAnimation { target: blueBeam2; property: "opacity"; from: 0.0; to: 0.75; duration: 90 }
                NumberAnimation { target: blueBeam3; property: "opacity"; from: 0.0; to: 0.6; duration: 90 }
            }
            ParallelAnimation {
                NumberAnimation { target: blueBurstMask; property: "flashOpacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: blueBurstMask; property: "bloomOpacity"; to: 0.0; duration: 300 }
                NumberAnimation { target: blueRingBurst; property: "opacity"; to: 0.0; duration: 300 }
                NumberAnimation { target: blueHexRing; property: "opacity"; to: 0.0; duration: 320 }
                NumberAnimation { target: blueBeam1; property: "opacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: blueBeam2; property: "opacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: blueBeam3; property: "opacity"; to: 0.0; duration: 200 }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: function(mouse) {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: function(mouse) {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: function(mouse) {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    if (backend) backend.decrement_win("blue")
                } else {
                    if (backend) backend.add_win("blue")
                }
            }
        }
        Item {
            id: blueFailFx
            anchors.fill: parent
            visible: root.qmlPreviewEnabled && blueImgBox.visible
            z: 6
            opacity: root._blueFailOpacity
            Timer {
                interval: 20
                repeat: true
                running: root.qmlPreviewEnabled && root._blueFailOpacity > 0.0
                onTriggered: {
                    blueImgBox.jitterX = (Math.random() - 0.5) * 9
                    blueImgBox.jitterY = (Math.random() - 0.5) * 9
                }
                onRunningChanged: {
                    if (!running) { blueImgBox.jitterX = 0; blueImgBox.jitterY = 0; }
                }
            }
            Canvas {
                id: blueFailCanvas
                anchors.fill: parent
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var w = width
                    var h = height
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        var r = Math.min(w, h) * 0.5
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var rr = Math.min(w, h) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang)
                            var py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, w, h)
                    }
                    ctx.clip()
                    ctx.fillStyle = root._cfg("fail.tint", "#000000")
                    ctx.globalAlpha = 0.75
                    ctx.fillRect(0, 0, w, h)
                    ctx.globalAlpha = 1.0
                    ctx.strokeStyle = "#e6e6e6"
                    ctx.lineWidth = 2.6
                    ctx.shadowColor = "#ffffff"
                    ctx.shadowBlur = 6
                    for (var i = 0; i < root._blueFailLines.length; i++) {
                        var pts = root._blueFailLines[i]
                        if (!pts || pts.length === 0) continue
                        ctx.beginPath()
                        ctx.moveTo(pts[0].x, pts[0].y)
                        for (var j = 1; j < pts.length; j++) {
                            ctx.lineTo(pts[j].x, pts[j].y)
                        }
                        ctx.stroke()
                    }
                    ctx.shadowBlur = 0
                    ctx.restore()
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                visible: root.qmlPreviewEnabled && root._blueFailFlash > 0.0
                z: 2
                Canvas {
                    anchors.fill: parent
                    renderTarget: Canvas.Image
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                        var cx = width * 0.5
                        var cy = height * 0.5
                        var w = width
                        var h = height
                        ctx.save()
                        ctx.beginPath()
                        if (mask === "circle") {
                            var r = Math.min(w, h) * 0.5
                            ctx.arc(cx, cy, r, 0, Math.PI * 2)
                        } else if (mask === "hex") {
                            var rr = Math.min(w, h) * 0.5
                            for (var i = 0; i < 6; i++) {
                                var ang = (Math.PI / 3) * i - Math.PI / 6
                                var px = cx + rr * Math.cos(ang)
                                var py = cy + rr * Math.sin(ang)
                                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                            }
                            ctx.closePath()
                        } else {
                            ctx.rect(0, 0, w, h)
                        }
                        ctx.clip()
                        ctx.fillStyle = "#ffffff"
                        ctx.globalAlpha = root._blueFailFlash * root._blueFailOpacity
                        ctx.fillRect(0, 0, w, h)
                        ctx.restore()
                    }
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    Connections {
                        target: backend
                        function onOverlayPlayerMaskChanged() { requestPaint() }
                    }
                }
            }
        }
        SequentialAnimation {
            id: blueFailAnim
            running: false
            ParallelAnimation {
                NumberAnimation { target: root; property: "_blueFailOpacity"; from: 0.0; to: root._cfg("fail.overlay_opacity", 0.85); duration: 280 }
                NumberAnimation { target: root; property: "_blueFailFlash"; from: 0.0; to: 1.0; duration: 140 }
            }
            NumberAnimation { target: root; property: "_blueFailFlash"; from: 1.0; to: 0.0; duration: 360 }
            PauseAnimation { duration: 360 }
            NumberAnimation { target: root; property: "_blueFailOpacity"; from: root._cfg("fail.overlay_opacity", 0.85); to: 0.0; duration: 1800 }
        }
        Item {
            id: blueWinTextWrap
            visible: root.qmlPreviewEnabled && _cfg("win_text.enabled", true) && backend && backend.blueWinStreak > 0
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: parent.height * _cfg("win_text.offset_ratio", 0.22)
            z: 100
            implicitWidth: blueWinTextBase.implicitWidth
            implicitHeight: blueWinTextBase.implicitHeight
            width: implicitWidth
            height: implicitHeight
            property real pulseScale: 1.0
            property real pulseOpacity: 0.0
            Rectangle {
                id: blueWinTextGlow
                anchors.centerIn: parent
                width: blueWinTextBase.implicitWidth * 1.8
                height: blueWinTextBase.implicitHeight * 1.6
                radius: height * 0.5
                color: _cfg("win_text.highlight_color", "#f8fbff")
                opacity: blueWinTextWrap.pulseOpacity
                scale: blueWinTextWrap.pulseScale
            }
            Text {
                id: blueWinTextShadow
                text: winText(backend ? backend.blueWinStreak : 0)
                color: _cfg("win_text.shadow_color", "#0b0f14")
                opacity: _cfg("win_text.shadow_opacity", 0.6)
                font.pixelSize: winTextSize(blueImgBox.height)
                font.bold: true
                renderType: Text.NativeRendering
                antialiasing: true
                smooth: true
                x: 0
                y: 1
            }
            Text {
                id: blueWinTextBase
                text: winText(backend ? backend.blueWinStreak : 0)
                color: _cfg("win_text.base_color", "#d6dbe0")
                font.pixelSize: winTextSize(blueImgBox.height)
                font.bold: true
                style: Text.Outline
                styleColor: Qt.rgba(
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).r,
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).g,
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).b,
                    0.55
                )
                renderType: Text.NativeRendering
                antialiasing: true
                smooth: true
            }
            Rectangle {
                id: blueWinTextHighlightClip
                anchors.left: blueWinTextBase.left
                anchors.right: blueWinTextBase.right
                anchors.top: blueWinTextBase.top
                height: blueWinTextBase.implicitHeight * _cfg("win_text.highlight_height", 0.55)
                color: "transparent"
                clip: true
                Text {
                    text: winText(backend ? backend.blueWinStreak : 0)
                    color: _cfg("win_text.highlight_color", "#f8fbff")
                    opacity: 0.65
                    font.pixelSize: winTextSize(blueImgBox.height)
                    font.bold: true
                    renderType: Text.NativeRendering
                    antialiasing: true
                    smooth: true
                    y: -1
                }
            }
            SequentialAnimation {
                id: blueWinTextPulse
                running: false
                ParallelAnimation {
                    NumberAnimation { target: blueWinTextWrap; property: "pulseOpacity"; from: 0.0; to: 0.7; duration: 90 }
                    NumberAnimation { target: blueWinTextWrap; property: "pulseScale"; from: 0.9; to: 1.25; duration: 140; easing.type: Easing.OutQuad }
                }
                ParallelAnimation {
                    NumberAnimation { target: blueWinTextWrap; property: "pulseOpacity"; to: 0.0; duration: 220; easing.type: Easing.OutQuad }
                    NumberAnimation { target: blueWinTextWrap; property: "pulseScale"; to: 1.0; duration: 240; easing.type: Easing.OutQuad }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = blueImgBox; root.lastDragItem = blueImgBox; root.selectedItem = blueImgBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(blueImgBox, blueImgBox.x, blueImgBox.y)
                blueImgBox.x = p.x
                blueImgBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = blueImgBox.width
                    parent.startH = blueImgBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    blueImgBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    blueImgBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowBlueImg) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowBlueImg) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); backend.set_overlay_visible("blue_img", !backend.overlayShowBlueImg); saveLayout() }
            }
        }
    }

    Rectangle {
        id: blueNameBox
        parent: scaledRoot
        property int borderW: Math.max(1, root.styleVal("blue_name", "border_width", 1))
        property color borderCol: root.styleColor("blue_name", "border_color", "#1b3f8a", "border_opacity", 1.0)
        color: root._matchBg(blueNameBox, root.styleColor("blue_name", "bg_color", "#2d5ed0", "bg_opacity", 1.0))
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowBlueName))
        opacity: (editMode && backend && !backend.overlayShowBlueName) ? 0.25 : 1.0
        border.color: "transparent"
        border.width: 0
        radius: root._matchRadius(blueNameBox, 2)
        HoverHandler { id: blueNameHover }
        ToolTip.visible: blueNameHover.hovered
        ToolTip.text: "\uBE14\uB8E8 \uCF54\uB108 \uB2C9\uB124\uC784. \uC88C\uD074\uB9AD: \uD504\uB85C\uD544 \uBD88\uB7EC\uC624\uAE30  \u00B7  \uC6B0\uD074\uB9AD: \uD504\uB85C\uD544 \uB4F1\uB85D/\uC218\uC815"
        onVisibleChanged: scheduleBoundsUpdate()
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            id: blueNameText
            anchors.centerIn: parent
            text: backend ? backend.blueName : ""
            width: parent.width - 10
            height: parent.height - 6
            font.pixelSize: root.styleFontSize("blue_name", Math.max(14, Math.min(parent.height * 0.5, 28)))
            font.family: root.styleVal("blue_name", "font_family", "Noto Sans KR")
            font.bold: root.styleVal("blue_name", "font_bold", true)
            font.weight: root.styleVal("blue_name", "font_weight", Font.Black)
            color: root.styleColor("blue_name", "text_color", "#ffffff", "text_opacity", 1.0)
            elide: Text.ElideRight
            fontSizeMode: Text.Fit
            minimumPixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        Rectangle {
            width: Math.max(2, root.styleVal("blue_name", "badge_width", Math.max(8, parent.height * 0.18)))
            height: parent.height
            radius: 0
            color: root.styleColor("blue_name", "badge_color", "#3b82f6")
            anchors.verticalCenter: parent.verticalCenter
            x: root.styleVal("blue_name", "badge_side", "left") === "right" ? parent.width : -width
            z: 100
            visible: root.styleVal("blue_name", "badge_enabled", true) && (editMode || (backend && backend.blueName && backend.blueName.length > 0))
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.color: Qt.rgba(1, 1, 1, 0.45)
                border.width: 1
                radius: 2
            }
            Rectangle {
                anchors.fill: parent
                radius: 2
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.2) }
                    GradientStop { position: 0.5; color: "transparent" }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.1) }
                }
            }
        }
        Rectangle {
            visible: !root._touchingSide(blueNameBox, "top")
            color: root._matchBorder(blueNameBox, blueNameBox.borderCol)
            x: 0
            y: 0
            width: blueNameBox.width
            height: blueNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(blueNameBox, "bottom")
            color: root._matchBorder(blueNameBox, blueNameBox.borderCol)
            x: 0
            y: blueNameBox.height - blueNameBox.borderW
            width: blueNameBox.width
            height: blueNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(blueNameBox, "left")
            color: root._matchBorder(blueNameBox, blueNameBox.borderCol)
            x: 0
            y: 0
            width: blueNameBox.borderW
            height: blueNameBox.height
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(blueNameBox, "right")
            color: root._matchBorder(blueNameBox, blueNameBox.borderCol)
            x: blueNameBox.width - blueNameBox.borderW
            y: 0
            width: blueNameBox.borderW
            height: blueNameBox.height
            z: 6
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: function(mouse) {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: function(mouse) {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: function(mouse) {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    var p = blueNameBox.mapToItem(root.contentItem, mouse.x, mouse.y)
                    showProfileMenu("blue", p.x, p.y)
                } else {
                    backend.select_player("blue")
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = blueNameBox; root.lastDragItem = blueNameBox; root.selectedItem = blueNameBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(blueNameBox, blueNameBox.x, blueNameBox.y)
                blueNameBox.x = p.x
                blueNameBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = blueNameBox.width
                    parent.startH = blueNameBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    blueNameBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    blueNameBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowBlueName) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowBlueName) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("blue_name", !backend.overlayShowBlueName); saveLayout() }
            }
        }
    }

    Item {
        id: redAura
        parent: scaledRoot
        x: redImgBox.x
        y: redImgBox.y
        width: redImgBox.width
        height: redImgBox.height
        visible: root.qmlPreviewEnabled && redImgBox.visible && backend && root._stageFor(backend.redWinStreak) !== null && root._cfg("aura.enabled", true)
        z: redImgBox.z - 1
        property int streak: backend ? backend.redWinStreak : 0
        property color auraColor: root.auraColorFor(streak)
        property real baseOpacity: root.auraOpacityFor(streak)
        property int level: root.auraLevel(streak)
        property real intensity: 1.0
        property int framePad: root._cfg("aura.frame_padding", 12)
        property int outerPad: root._cfg("aura.outer_padding", 14)
        property int border1: root._cfg("aura.border1", 2)
        property int border2: root._cfg("aura.border2", 1)
        property int border3: root._cfg("aura.border3", 1)
        property color borderColor: root.auraBorderColor(auraColor)
        property real borderOpacity: root._cfg("aura.border_opacity", 0.6)
        property real blurRadius: root._cfg("aura.blur_radius", 0)
        property bool borderEffectEnabled: root._cfg("aura.border_effect_enabled", true)
        property bool backdropEnabled: root._cfg("aura.backdrop_enabled", true)
        property color backdropColor: root._cfg("aura.backdrop_color", "#000000")
        property real backdropOpacity: root._cfg("aura.backdrop_opacity", 0.25)
        property int backdropPad: root._cfg("aura.backdrop_pad", 8)
        property real corePulse: 1.0
        property real bodyPulse: 1.0
        property real glowPulse: 1.0
        property real wispPulse: 1.0

        SequentialAnimation on corePulse {
            running: root.qmlPreviewEnabled && redAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.75; to: 1.25; duration: 900 }
            NumberAnimation { from: 1.25; to: 0.85; duration: 700 }
            PauseAnimation { duration: 200 }
        }
        SequentialAnimation on bodyPulse {
            running: root.qmlPreviewEnabled && redAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.7; to: 1.15; duration: 1200 }
            NumberAnimation { from: 1.15; to: 0.85; duration: 900 }
            PauseAnimation { duration: 300 }
        }
        SequentialAnimation on glowPulse {
            running: root.qmlPreviewEnabled && redAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.6; to: 1.2; duration: 1600 }
            NumberAnimation { from: 1.2; to: 0.75; duration: 1200 }
            PauseAnimation { duration: 400 }
        }
        SequentialAnimation on wispPulse {
            running: root.qmlPreviewEnabled && redAura.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.5; to: 1.1; duration: 1800 }
            NumberAnimation { from: 1.1; to: 0.7; duration: 1400 }
            PauseAnimation { duration: 450 }
        }

        Item {
            id: redAuraContent
            anchors.fill: parent
            visible: true

        Rectangle {
            anchors.centerIn: parent
            width: parent.width + redAura.backdropPad
            height: parent.height + redAura.backdropPad
            radius: 10
            color: redAura.backdropColor
            opacity: redAura.backdropOpacity
            visible: redAura.backdropEnabled
            z: -2
        }

        ParticleSystem {
            id: redParticles
            running: root.qmlPreviewEnabled && redAura.visible
            Item {
                id: redNeonFrame
                visible: false
            }
        }

        ImageParticle {
            system: redParticles
            groups: ["core"]
            source: root.flameParticleTex
            color: Qt.lighter(redAura.auraColor, 1.7)
            colorVariation: root._aura("core.color_var", 0.04)
            alpha: root._aura("core.alpha", 0.98)
            alphaVariation: root._aura("core.alpha_var", 0.08)
            rotationVariation: root._aura("core.rot_var", 0)
        }

        ImageParticle {
            system: redParticles
            groups: ["body"]
            source: root.flameParticleTex
            color: Qt.lighter(redAura.auraColor, 1.25)
            colorVariation: root._aura("body.color_var", 0.06)
            alpha: root._aura("body.alpha", 0.85)
            alphaVariation: root._aura("body.alpha_var", 0.1)
            rotationVariation: root._aura("body.rot_var", 2)
        }

        ImageParticle {
            system: redParticles
            groups: ["glow"]
            source: root.glowParticleTex
            color: redAura.auraColor
            colorVariation: root._aura("glow.color_var", 0.08)
            alpha: root._aura("glow.alpha", 0.22)
            alphaVariation: root._aura("glow.alpha_var", 0.08)
            rotationVariation: root._aura("glow.rot_var", 6)
        }

        ImageParticle {
            system: redParticles
            groups: ["wisps"]
            source: root.glowParticleTex
            color: redAura.auraColor
            colorVariation: root._aura("wisps.color_var", 0.1)
            alpha: root._aura("wisps.alpha", 0.12)
            alphaVariation: root._aura("wisps.alpha_var", 0.06)
            rotationVariation: root._aura("wisps.rot_var", 6)
        }

        ImageParticle {
            system: redParticles
            groups: ["spark"]
            source: root.sparkTex
            color: Qt.lighter(redAura.auraColor, 1.35)
            colorVariation: root._aura("spark.color_var", 0.1)
            alpha: root._aura("spark.alpha", 0.2)
            alphaVariation: root._aura("spark.alpha_var", 0.08)
            rotationVariation: root._aura("spark.rot_var", 0)
        }

        Emitter {
            system: redParticles
            group: "core"
            width: parent.width * 0.25
            height: parent.height * 0.22
            x: (parent.width - width) * 0.5
            y: parent.height * 0.44
            emitRate: root._cfg("aura.flame_emit", 12) * root._aura("core.emit_mul", 3.2) * redAura.corePulse
            lifeSpan: root._aura("core.life", 1200)
            lifeSpanVariation: root._aura("core.life_var", 220)
            size: root._cfg("aura.flame_size", 20) * root._aura("core.size_mul", 0.5)
            sizeVariation: (root._cfg("aura.flame_size_var", 14) * root._aura("core.size_var_mul", 0.12)) + root._aura("core.size_var_add", 1)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("core.angle_var", 6); magnitude: root._aura("core.speed", 120); magnitudeVariation: root._aura("core.speed_var", 15) }
            acceleration: AngleDirection { angle: 90; angleVariation: root._aura("core.accel_var", 8); magnitude: root._aura("core.accel", 30); magnitudeVariation: root._aura("core.accel_mag_var", 12) }
        }

        Emitter {
            system: redParticles
            group: "body"
            width: parent.width * 0.45
            height: parent.height * 0.35
            x: (parent.width - width) * 0.5
            y: parent.height * 0.38
            emitRate: root._cfg("aura.flame_emit", 12) * root._aura("body.emit_mul", 2.6) * redAura.bodyPulse
            lifeSpan: root._aura("body.life", 1500)
            lifeSpanVariation: root._aura("body.life_var", 260)
            size: root._cfg("aura.flame_size", 20) * root._aura("body.size_mul", 0.7)
            sizeVariation: (root._cfg("aura.flame_size_var", 14) * root._aura("body.size_var_mul", 0.18)) + root._aura("body.size_var_add", 1)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("body.angle_var", 8); magnitude: root._aura("body.speed", 85); magnitudeVariation: root._aura("body.speed_var", 15) }
            acceleration: AngleDirection { angle: 90; angleVariation: root._aura("body.accel_var", 10); magnitude: root._aura("body.accel", 22); magnitudeVariation: root._aura("body.accel_mag_var", 12) }
        }

        Emitter {
            system: redParticles
            group: "glow"
            width: parent.width * 0.6
            height: parent.height * 0.55
            x: (parent.width - width) * 0.5
            y: parent.height * 0.28
            emitRate: root._cfg("aura.smoke_emit", 6) * root._aura("glow.emit_mul", 0.6) * redAura.glowPulse
            lifeSpan: root._aura("glow.life", 1700)
            lifeSpanVariation: root._aura("glow.life_var", 320)
            size: root._cfg("aura.smoke_size", 36) * root._aura("glow.size_mul", 0.6)
            sizeVariation: (root._cfg("aura.smoke_size_var", 20) * root._aura("glow.size_var_mul", 0.2)) + root._aura("glow.size_var_add", 2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("glow.angle_var", 8); magnitude: root._aura("glow.speed", 40); magnitudeVariation: root._aura("glow.speed_var", 12) }
        }

        Emitter {
            system: redParticles
            group: "wisps"
            width: parent.width * 0.55
            height: parent.height * 0.55
            x: (parent.width - width) * 0.5
            y: parent.height * 0.30
            emitRate: root._cfg("aura.smoke_emit", 6) * root._aura("wisps.emit_mul", 0.35) * redAura.wispPulse
            lifeSpan: root._aura("wisps.life", 1800)
            lifeSpanVariation: root._aura("wisps.life_var", 360)
            size: root._cfg("aura.smoke_size", 36) * root._aura("wisps.size_mul", 0.55)
            sizeVariation: (root._cfg("aura.smoke_size_var", 20) * root._aura("wisps.size_var_mul", 0.18)) + root._aura("wisps.size_var_add", 2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("wisps.angle_var", 7); magnitude: root._aura("wisps.speed", 32); magnitudeVariation: root._aura("wisps.speed_var", 10) }
        }

        Emitter {
            system: redParticles
            group: "spark"
            width: parent.width * 0.6
            height: parent.height * 0.35
            x: (parent.width - width) * 0.5
            y: parent.height * 0.55
            emitRate: root._cfg("aura.spark_emit", 10) * root._aura("spark.emit_mul", 0.1)
            lifeSpan: root._aura("spark.life", 520)
            lifeSpanVariation: root._aura("spark.life_var", 360)
            size: root._cfg("aura.spark_size", 10) * root._aura("spark.size_mul", 0.6)
            sizeVariation: root._cfg("aura.spark_size_var", 8) * root._aura("spark.size_var_mul", 0.2)
            velocity: AngleDirection { angle: 270; angleVariation: root._aura("spark.angle_var", 18); magnitude: root._aura("spark.speed", 150); magnitudeVariation: root._aura("spark.speed_var", 45) }
        }

        Turbulence {
            system: redParticles
            groups: ["core", "body"]
            strength: root._cfg("aura.turbulence", 18) * root._aura("core.turb_mul", 0.15)
        }
        Turbulence {
            system: redParticles
            groups: ["glow", "wisps", "spark"]
            strength: root._cfg("aura.turbulence", 18) * root._aura("glow.turb_mul", 0.35)
        }

        Item { visible: false }
        }

        Item { visible: false }

    }

    Rectangle {
        id: redImgBox
        parent: scaledRoot
        property bool noOverlapFade: true
        color: (backend && backend.overlayPlayerMask === "square") ? "#1e1e1e" : "transparent"
        border.color: "transparent"
        border.width: 0
        radius: (backend && backend.overlayPlayerMask === "square") ? 2 : 0
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowRedImg))
        opacity: (editMode && backend && !backend.overlayShowRedImg) ? 0.25 : 1.0
        clip: false
        HoverHandler { id: redImgHover }
        ToolTip.visible: redImgHover.hovered
        ToolTip.text: "\uB808\uB4DC \uCD08\uC0C1\uD654"
        onVisibleChanged: { scheduleBoundsUpdate(); redImgBoxFill.requestPaint(); redImgBoxBorder.requestPaint() }
        property real jitterX: 0
        property real jitterY: 0
        property real splitX: 0
        property real splitY: 0
        transform: Translate { x: redImgBox.jitterX; y: redImgBox.jitterY }
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Canvas {
            id: redImgBoxFill
            anchors.fill: parent
            z: 0
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                if (mask === "square") return
                var line = 2.0
                var inset = line * 0.5
                var w = Math.max(0, width - inset * 2)
                var h = Math.max(0, height - inset * 2)
                ctx.fillStyle = "#1e1e1e"
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(w, h) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(w, h) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                }
                ctx.fill()
            }
        }
        Item {
            id: redImgMasked
            anchors.fill: parent
            z: 1
            property string imageSource: "image://players/red?rev=" + (backend ? backend.redImageRev : 0)
            property real shimmerPos: -0.5
            property real pulseOpacity: 0.8
            function requestPaint() { redPortraitMask.requestPaint(); redPortraitOverlay.requestPaint() }
            SequentialAnimation on shimmerPos {
                loops: Animation.Infinite
                running: backend && backend.redWinStreak >= 3
                NumberAnimation { from: -0.5; to: 1.5; duration: 2500; easing.type: Easing.InOutSine }
                PauseAnimation { duration: 800 }
            }
            SequentialAnimation on pulseOpacity {
                loops: Animation.Infinite
                running: backend && backend.redWinStreak >= 3
                NumberAnimation { from: 0.6; to: 1.0; duration: 1200; easing.type: Easing.InOutQuad }
                NumberAnimation { from: 1.0; to: 0.6; duration: 1200; easing.type: Easing.InOutQuad }
            }
            onShimmerPosChanged: redPortraitOverlay.requestPaint()
            onPulseOpacityChanged: redPortraitOverlay.requestPaint()
            Item {
                id: redPortraitSource
                anchors.fill: parent
                visible: false
                layer.enabled: true
                layer.smooth: true
                layer.textureSize: Qt.size(Math.max(1, Math.ceil(width * 2.5)), Math.max(1, Math.ceil(height * 2.5)))
                Image {
                    source: redImgMasked.imageSource
                    cache: false
                    asynchronous: true
                    smooth: true
                    mipmap: false
                    sourceSize.width: Math.max(1, Math.ceil(width * 2.5))
                    sourceSize.height: Math.max(1, Math.ceil(height * 2.5))
                    fillMode: Image.PreserveAspectCrop
                    width: parent.width * Math.max(0.5, root._cfg("portrait.zoom", 1.25))
                    height: parent.height * Math.max(0.5, root._cfg("portrait.zoom", 1.25))
                    x: (parent.width - width) * 0.5 + parent.width * root._cfg("portrait.offset_x", 0.0)
                    y: (parent.height - height) * 0.5 + parent.height * root._cfg("portrait.offset_y", -0.08)
                }
            }
            Canvas {
                id: redPortraitMask
                anchors.fill: parent
                visible: false
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    ctx.fillStyle = "white"
                    ctx.beginPath()
                    if (mask === "circle") {
                        ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var cx = width * 0.5, cy = height * 0.5, rr = Math.min(width, height) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang), py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, width, height)
                    }
                    ctx.fill()
                }
                Component.onCompleted: requestPaint()
            }
            MultiEffect {
                anchors.fill: parent
                source: redPortraitSource
                maskEnabled: true
                maskSource: redPortraitMask
                antialiasing: true
            }
            Canvas {
                id: redPortraitOverlay
                anchors.fill: parent
                z: 2
                visible: root.qmlPreviewEnabled && backend && (backend.redWinStreak || 0) >= 3
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    if (!visible) return
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var cx = width * 0.5, cy = height * 0.5, rr = Math.min(width, height) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang), py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, width, height)
                    }
                    ctx.clip()
                    var vig = ctx.createLinearGradient(0, height * 0.4, 0, height)
                    vig.addColorStop(0, "transparent")
                    vig.addColorStop(1, "rgba(0,0,0,0.9)")
                    ctx.fillStyle = vig
                    ctx.fillRect(0, 0, width, height)
                    var sPos = redImgMasked.shimmerPos * width
                    var shim = ctx.createLinearGradient(sPos - 15, 0, sPos + 15, 0)
                    shim.addColorStop(0, "transparent")
                    shim.addColorStop(0.5, "rgba(255,255,255,0.8)")
                    shim.addColorStop(1, "transparent")
                    ctx.globalCompositeOperation = "overlay"
                    ctx.fillStyle = shim
                    ctx.fillRect(0, 0, width, height)
                    ctx.restore()
                }
                onVisibleChanged: requestPaint()
            }
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redImgMasked.requestPaint() }
                function onEffectSettingsChanged() { redImgMasked.requestPaint() }
                function onRedImageRevChanged() { redImgMasked.requestPaint() }
                function onRedWinStreakChanged() { redImgMasked.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redImgMasked.requestPaint() }
                function onHeightChanged() { redImgMasked.requestPaint() }
            }
        }
        Canvas {
            id: redHitFlashCanvas
            anchors.fill: parent
            z: 8.8
            opacity: root._redHitFlash
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                var cx = width * 0.5
                var cy = height * 0.5
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(cx, cy, Math.min(width, height) * 0.5, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                ctx.globalAlpha = 0.76
                ctx.fillStyle = "#fff2bd"
                ctx.fillRect(0, 0, width, height)
                ctx.globalAlpha = 1.0
                var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.62)
                g.addColorStop(0.0, "rgba(255,255,255,0.95)")
                g.addColorStop(0.42, "rgba(255,215,92,0.58)")
                g.addColorStop(1.0, "rgba(255,255,255,0)")
                ctx.fillStyle = g
                ctx.fillRect(0, 0, width, height)
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redHitFlashCanvas.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redHitFlashCanvas.requestPaint() }
                function onHeightChanged() { redHitFlashCanvas.requestPaint() }
            }
        }
        Canvas {
            id: redStunFlashCanvas
            anchors.fill: parent
            z: 9
            opacity: root._redStunFlash
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                ctx.fillStyle = "white"
                ctx.fillRect(0, 0, width, height)
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redStunFlashCanvas.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redStunFlashCanvas.requestPaint() }
                function onHeightChanged() { redStunFlashCanvas.requestPaint() }
            }
        }
        Canvas {
            id: redHeavyImpactCanvas
            anchors.fill: parent
            z: 9.25
            opacity: root._redHeavyImpact
            visible: opacity > 0.01
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                var gx = width * 0.5
                var gy = height * 0.5
                var g = ctx.createRadialGradient(gx, gy, 0, gx, gy, Math.max(width, height) * 0.72)
                g.addColorStop(0.0, "rgba(255,255,255,0.92)")
                g.addColorStop(0.28, "rgba(250,204,21,0.72)")
                g.addColorStop(0.62, "rgba(249,115,22,0.36)")
                g.addColorStop(1.0, "rgba(239,68,68,0)")
                ctx.fillStyle = g
                ctx.fillRect(0, 0, width, height)
                ctx.lineWidth = Math.max(2, Math.min(width, height) * 0.05)
                ctx.strokeStyle = "rgba(254,240,138,0.95)"
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5 - ctx.lineWidth, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx2 = width * 0.5
                    var cy2 = height * 0.5
                    var rr2 = Math.min(width, height) * 0.5 - ctx.lineWidth
                    for (var j = 0; j < 6; j++) {
                        var a2 = (Math.PI / 3) * j - Math.PI / 6
                        var p2x = cx2 + rr2 * Math.cos(a2)
                        var p2y = cy2 + rr2 * Math.sin(a2)
                        if (j === 0) ctx.moveTo(p2x, p2y); else ctx.lineTo(p2x, p2y)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(ctx.lineWidth, ctx.lineWidth, width - ctx.lineWidth * 2, height - ctx.lineWidth * 2)
                }
                ctx.stroke()
                ctx.restore()
            }
            onOpacityChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redHeavyImpactCanvas.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redHeavyImpactCanvas.requestPaint() }
                function onHeightChanged() { redHeavyImpactCanvas.requestPaint() }
            }
        }
        Canvas {
            id: redImpactCanvas
            anchors.fill: parent
            z: 9.5
            visible: root.qmlPreviewEnabled && (root._redKdOverlay > 0.01 || root._redTkoOverlay > 0.01)
            opacity: Math.max(root._redKdOverlay, root._redTkoOverlay)
            renderTarget: Canvas.Image
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                ctx.save()
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(width, height) * 0.5
                    ctx.arc(width * 0.5, height * 0.5, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var rr = Math.min(width, height) * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(0, 0, width, height)
                }
                ctx.clip()
                var tko = root._redTkoOverlay > root._redKdOverlay
                ctx.fillStyle = tko ? "rgb(20, 6, 6)" : "rgb(32, 0, 0)"
                ctx.fillRect(0, 0, width, height)
                ctx.lineWidth = Math.max(2, Math.min(width, height) * 0.045)
                ctx.strokeStyle = tko ? "rgba(255, 255, 255, 0.95)" : "rgba(252, 165, 165, 0.95)"
                ctx.beginPath()
                if (mask === "circle") {
                    ctx.arc(width * 0.5, height * 0.5, Math.min(width, height) * 0.5 - ctx.lineWidth, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var cx2 = width * 0.5
                    var cy2 = height * 0.5
                    var rr2 = Math.min(width, height) * 0.5 - ctx.lineWidth
                    for (var j = 0; j < 6; j++) {
                        var a2 = (Math.PI / 3) * j - Math.PI / 6
                        var p2x = cx2 + rr2 * Math.cos(a2)
                        var p2y = cy2 + rr2 * Math.sin(a2)
                        if (j === 0) ctx.moveTo(p2x, p2y); else ctx.lineTo(p2x, p2y)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(ctx.lineWidth, ctx.lineWidth, width - ctx.lineWidth * 2, height - ctx.lineWidth * 2)
                }
                ctx.stroke()
                ctx.restore()
            }
            onVisibleChanged: requestPaint()
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redImpactCanvas.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redImpactCanvas.requestPaint() }
                function onHeightChanged() { redImpactCanvas.requestPaint() }
            }
        }
        Text {
            anchors.centerIn: parent
            z: 10
            text: root._redImpactLabel
            visible: root.qmlPreviewEnabled && text !== "" && (root._redKdOverlay > 0.01 || root._redTkoOverlay > 0.01)
            color: root._redTkoOverlay > root._redKdOverlay ? "#ffffff" : "#fee2e2"
            font.family: "Arial Black"
            font.bold: true
            font.pixelSize: Math.max(18, Math.min(parent.width, parent.height) * 0.26)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            style: Text.Outline
            styleColor: root._redTkoOverlay > root._redKdOverlay ? "#7f1d1d" : "#7f1d1d"
        }
        Rectangle {
            id: redDamageBadge
            parent: scaledRoot
            z: 10
            width: Math.max(58, redDamageText.implicitWidth + 16)
            height: Math.max(22, redImgBox.height * 0.22)
            x: redImgBox.x + (redImgBox.width - width) * 0.5
            y: redImgBox.y + redImgBox.height + 4
            radius: 8
            color: "transparent"
            border.color: "transparent"
            border.width: 0
            visible: root.qmlPreviewEnabled && redImgBox.visible && backend && backend.redDamageText !== ""
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            ToolTip.visible: redDamageHover.hovered
            ToolTip.text: backend ? backend.redLogMetaText : ""
            HoverHandler { id: redDamageHover }
            Text {
                id: redDamageText
                anchors.centerIn: parent
                text: backend ? backend.redDamageText : ""
                color: "#e5e7eb"
                font.bold: true
                font.pixelSize: Math.max(13, Math.min(18, parent.height * 0.68))
                font.family: "Arial Black"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                style: Text.Outline
                styleColor: "#020617"
            }
        }
        Rectangle {
            id: redComboBadge
            parent: scaledRoot
            z: 13
            property bool active: false
            width: Math.max(122, redComboHit.implicitWidth + 34, redComboDamage.implicitWidth + 28)
            height: Math.max(46, redNameBox.height * 1.02)
            x: redImgBox.x + (redImgBox.width - width) * 0.5
            y: Math.max(0, redImgBox.y - height - Math.max(12, redImgBox.height * 0.12))
            radius: Math.max(4, height * 0.12)
            visible: root.qmlPreviewEnabled && active && backend && backend.redComboHitText !== ""
            color: "transparent"
            border.color: "transparent"
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            Timer {
                id: redComboHideTimer
                interval: 2000
                repeat: false
                onTriggered: {
                    redComboBadge.active = false
                    if (backend) backend.clear_combo_display("red")
                }
            }
            Connections {
                target: backend
                function onRedComboHitTextChanged() {
                    if (backend.redComboHitText !== "") {
                        redComboBadge.active = true
                        redComboHideTimer.restart()
                    } else {
                        redComboBadge.active = false
                        redComboHideTimer.stop()
                    }
                }
            }
            Text {
                id: redComboHit
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 2
                text: backend ? backend.redComboHitText : ""
                color: text === "COUNTER" ? "#ffd54a" : "#fee2e2"
                font.family: "Arial Black"
                font.bold: true
                font.italic: true
                font.pixelSize: Math.max(15, parent.height * 0.38)
                style: Text.Outline
                styleColor: "#1f0707"
            }
            Text {
                id: redComboDamage
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: redComboHit.bottom
                anchors.topMargin: -1
                text: backend ? backend.redComboDamageText : ""
                color: redComboHit.text === "COUNTER" ? "#ffffff" : "#ffe8a3"
                font.family: "Arial Black"
                font.bold: true
                font.italic: true
                font.pixelSize: Math.max(13, parent.height * 0.30)
                style: Text.Outline
                styleColor: "#7c2d12"
            }
        }
        Rectangle {
            id: redPunishmentBadge
            parent: scaledRoot
            z: 10
            width: redNameBox.width
            height: Math.max(14, Math.min(22, redNameBox.height * 0.46))
            x: redNameBox.x
            y: redNameBox.y + redNameBox.height + 4
            radius: Math.max(3, height * 0.35)
            color: "transparent"
            border.color: "transparent"
            border.width: 0
            visible: root.qmlPreviewEnabled && redImgBox.visible && backend && backend.redPunishmentText !== ""
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            ToolTip.visible: redPunishmentHover.hovered
            ToolTip.text: backend ? (backend.redPunishmentText + "\n" + backend.redLogMetaText) : ""
            HoverHandler { id: redPunishmentHover }
            Canvas {
                id: redHpMetalCanvas
                anchors.fill: parent
                z: 1
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var bevel = Math.max(5, height * 0.55)
                    var pad = Math.max(2, height * 0.18)
                    function barPath(inset) {
                        var x0 = inset, y0 = inset, x1 = width - inset, y1 = height - inset
                        var b = Math.max(2, bevel - inset)
                        ctx.beginPath()
                        ctx.moveTo(x0 + b, y0)
                        ctx.lineTo(x1, y0)
                        ctx.lineTo(x1 - b, y1)
                        ctx.lineTo(x0, y1)
                        ctx.closePath()
                    }
                    function framePath(inset) {
                        var x0 = inset, y0 = inset, x1 = width - inset, y1 = height - inset
                        var b = Math.max(2, bevel - inset)
                        ctx.beginPath()
                        ctx.moveTo(x0 + b, y0)
                        ctx.lineTo(x1, y0)
                        ctx.lineTo(x1 - b, y1)
                        ctx.lineTo(x0, y1)
                        ctx.closePath()
                    }
                    framePath(0.5)
                    var frame = ctx.createLinearGradient(0, 0, 0, height)
                    frame.addColorStop(0.0, "#fee2e2")
                    frame.addColorStop(0.18, "#fb7185")
                    frame.addColorStop(0.50, "#111827")
                    frame.addColorStop(0.78, "#ef4444")
                    frame.addColorStop(1.0, "#fff1f2")
                    ctx.fillStyle = frame
                    ctx.fill()
                    ctx.save()
                    barPath(pad)
                    ctx.clip()
                    var bg = ctx.createLinearGradient(0, 0, 0, height)
                    bg.addColorStop(0, "#111827")
                    bg.addColorStop(1, "#020617")
                    ctx.fillStyle = bg
                    ctx.fillRect(0, 0, width, height)
                    var usableX = pad + 1
                    var usableW = Math.max(0, width - pad * 2 - 2)
                    var baseW = usableW * root.hpBaseRatio("red")
                    var curW = usableW * root.hpCurrentRatio("red")
                    var ghostW = Math.max(0, baseW - curW)
                    if (baseW > 0) {
                        var baseGrad = ctx.createLinearGradient(0, 0, 0, height)
                        baseGrad.addColorStop(0, "#334155")
                        baseGrad.addColorStop(1, "#0f172a")
                        ctx.fillStyle = baseGrad
                        ctx.fillRect(usableX, pad + 1, baseW, height - pad * 2 - 2)
                    }
                    if (ghostW > 0) {
                        var ghostGrad = ctx.createLinearGradient(0, 0, 0, height)
                        ghostGrad.addColorStop(0, "#ffedd5")
                        ghostGrad.addColorStop(0.45, root.hpMidDamageColor("red"))
                        ghostGrad.addColorStop(1, "#7c2d12")
                        ctx.fillStyle = ghostGrad
                        ctx.fillRect(usableX + curW, pad + 1, ghostW, height - pad * 2 - 2)
                    }
                    if (curW > 0) {
                        var hpGrad = ctx.createLinearGradient(0, 0, 0, height)
                        hpGrad.addColorStop(0, "#ecfeff")
                        hpGrad.addColorStop(0.16, "#a7f3d0")
                        hpGrad.addColorStop(0.52, root.hpBarColor("red"))
                        hpGrad.addColorStop(1, "#064e3b")
                        ctx.fillStyle = hpGrad
                        ctx.fillRect(usableX, pad + 1, curW, height - pad * 2 - 2)
                        ctx.fillStyle = "rgba(255,255,255,0.45)"
                        ctx.fillRect(usableX + 2, pad + 2, Math.max(0, curW - 4), Math.max(1, (height - pad * 2) * 0.22))
                    }
                    var shine = ctx.createLinearGradient(0, 0, width, 0)
                    shine.addColorStop(0, "rgba(255,255,255,0)")
                    shine.addColorStop(0.38, "rgba(255,255,255,0.05)")
                    shine.addColorStop(0.48, "rgba(255,255,255,0.32)")
                    shine.addColorStop(0.55, "rgba(255,255,255,0.12)")
                    shine.addColorStop(1, "rgba(255,255,255,0)")
                    ctx.fillStyle = shine
                    ctx.fillRect(0, 0, width, height)
                    ctx.restore()
                    framePath(0.5)
                    ctx.lineWidth = 1
                    ctx.strokeStyle = "rgba(255,255,255,0.65)"
                    ctx.stroke()
                }
                Connections {
                    target: backend
                    function onRedPunishmentMidChanged() { redHpMetalCanvas.requestPaint() }
                    function onRedPunishmentLongChanged() { redHpMetalCanvas.requestPaint() }
                }
                Connections {
                    target: redPunishmentBadge
                    function onWidthChanged() { redHpMetalCanvas.requestPaint() }
                    function onHeightChanged() { redHpMetalCanvas.requestPaint() }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                z: 3
                visible: root.qmlPreviewEnabled && root._redHpDownOverlay > 0.01
                opacity: root._redHpDownOverlay
                color: root._redHpDownLabel === "TKO" ? Qt.rgba(30 / 255, 6 / 255, 6 / 255, 0.94) : Qt.rgba(18 / 255, 4 / 255, 4 / 255, 0.92)
                border.color: root._redHpDownLabel === "TKO" ? "#ffffff" : "#facc15"
                border.width: 1
                clip: true
                Repeater {
                    model: 9
                    Rectangle {
                        width: 10
                        height: redPunishmentBadge.height * 2.4
                        x: (index * 20 + root._redHpDownStripe * 40) - 36
                        y: -redPunishmentBadge.height * 0.7
                        rotation: 28
                        color: root._redHpDownLabel === "TKO" ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(250 / 255, 204 / 255, 21 / 255, 0.24)
                    }
                }
            }
            Text {
                id: redPunishmentText
                z: 4
                anchors.centerIn: parent
                text: root._redHpDownOverlay > 0.01 ? root._redHpDownLabel : ""
                color: "#ffffff"
                opacity: parent.height >= 13 && root._redHpDownOverlay > 0.01 ? 1.0 : 0.0
                font.bold: true
                font.pixelSize: root._redHpDownOverlay > 0.01 ? Math.max(10, parent.height * 0.86) : 9
                style: Text.Outline
                styleColor: "#000000"
            }
        }
        Row {
            id: redKnockdownDots
            parent: scaledRoot
            z: 11
            spacing: Math.max(3, redPunishmentBadge.height * 0.18)
            x: redPunishmentBadge.x
            y: redPunishmentBadge.y + redPunishmentBadge.height + Math.max(2, redPunishmentBadge.height * 0.16)
            visible: root.qmlPreviewEnabled && redPunishmentBadge.visible
            Repeater {
                model: 3
                Item {
                    property real displaySize: Math.max(13, Math.min(19, redPunishmentBadge.height * 0.92))
                    width: displaySize
                    height: displaySize
                    property bool filled: backend && index < Math.max(0, 3 - backend.redRoundKnockdowns)
                    onFilledChanged: redKnockdownDotCanvas.requestPaint()
                    onDisplaySizeChanged: redKnockdownDotCanvas.requestPaint()
                    Canvas {
                    id: redKnockdownDotCanvas
                    property real renderScale: 3.0
                    width: parent.displaySize * renderScale
                    height: width
                    scale: 1.0 / renderScale
                    transformOrigin: Item.TopLeft
                    renderTarget: Canvas.Image
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    Component.onCompleted: requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var cx = width * 0.5
                        var cy = height * 0.5
                        var r = Math.min(width, height) * 0.38
                        ctx.save()

                        if (parent.filled) {
                            var glowSteps = [
                                [1.42, "rgba(255,230,128,0.12)"],
                                [1.25, "rgba(245,200,72,0.18)"],
                                [1.08, "rgba(255,244,176,0.26)"]
                            ]
                            for (var g = 0; g < glowSteps.length; ++g) {
                                ctx.fillStyle = glowSteps[g][1]
                                ctx.beginPath()
                                ctx.arc(cx, cy, r * glowSteps[g][0], 0, Math.PI * 2)
                                ctx.fill()
                            }
                        }

                        var socket = ctx.createRadialGradient(cx - r * 0.18, cy - r * 0.22, r * 0.1, cx, cy, r * 1.34)
                        socket.addColorStop(0.00, "#273142")
                        socket.addColorStop(0.45, "#080b12")
                        socket.addColorStop(0.72, "#02040a")
                        socket.addColorStop(1.00, "#000000")
                        ctx.fillStyle = socket
                        ctx.beginPath()
                        ctx.arc(cx, cy, r * 1.16, 0, Math.PI * 2)
                        ctx.fill()

                        var rim = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r)
                        rim.addColorStop(0.00, parent.filled ? "#fff8d6" : "#d7dee9")
                        rim.addColorStop(0.20, parent.filled ? "#d4af37" : "#64748b")
                        rim.addColorStop(0.46, "#111827")
                        rim.addColorStop(0.74, "#020617")
                        rim.addColorStop(1.00, parent.filled ? "#fffbe6" : "#334155")
                        ctx.fillStyle = rim
                        ctx.beginPath()
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                        ctx.fill()

                        var inner = r * 0.68
                        var fill = ctx.createRadialGradient(cx - inner * 0.36, cy - inner * 0.42, inner * 0.08, cx, cy, inner * 1.08)
                        if (parent.filled) {
                            fill.addColorStop(0.00, "#fffdf0")
                            fill.addColorStop(0.16, "#fff1a8")
                            fill.addColorStop(0.42, "#ffd54a")
                            fill.addColorStop(0.72, "#c9971a")
                            fill.addColorStop(1.00, "#6b4e05")
                        } else {
                            fill.addColorStop(0.00, "#475569")
                            fill.addColorStop(0.36, "#1e293b")
                            fill.addColorStop(0.74, "#0f172a")
                            fill.addColorStop(1.00, "#020617")
                        }
                        ctx.fillStyle = fill
                        ctx.beginPath()
                        ctx.arc(cx, cy, inner, 0, Math.PI * 2)
                        ctx.fill()

                        var cap = ctx.createRadialGradient(cx - inner * 0.35, cy - inner * 0.42, inner * 0.02, cx - inner * 0.25, cy - inner * 0.34, inner * 0.72)
                        cap.addColorStop(0.0, "rgba(255,255,255,0.82)")
                        cap.addColorStop(0.34, "rgba(255,255,255,0.20)")
                        cap.addColorStop(1.0, "rgba(255,255,255,0)")
                        ctx.fillStyle = cap
                        ctx.beginPath()
                        ctx.arc(cx - inner * 0.22, cy - inner * 0.32, inner * 0.52, 0, Math.PI * 2)
                        ctx.fill()

                        ctx.strokeStyle = parent.filled ? "rgba(255,255,255,0.92)" : "rgba(203,213,225,0.38)"
                        ctx.lineWidth = 1
                        ctx.beginPath()
                        ctx.arc(cx, cy, r - 0.5, 0, Math.PI * 2)
                        ctx.stroke()
                        ctx.restore()
                    }
                    }
                    Connections {
                        target: backend
                        function onRedRoundKnockdownsChanged() { redKnockdownDotCanvas.requestPaint() }
                    }
                }
            }
        }
        Image {
            id: redNameplate
            parent: scaledRoot
            z: redImgBox.z + 1
            property string npPath: root._nameplatePath(backend ? backend.redWinStreak : 0)
            property string npSide: root._cfg("nameplates.side_red", "right")
            visible: root.qmlPreviewEnabled && redImgBox.visible && npPath !== ""
            width: root._cfg("nameplates.width", 110) * root._cfg("nameplates.scale", 1.0)
            height: root._cfg("nameplates.height", 30) * root._cfg("nameplates.scale", 1.0)
            x: npSide === "left"
                ? (redImgBox.x - width - root._cfg("nameplates.gap", 6))
                : (redImgBox.x + redImgBox.width + root._cfg("nameplates.gap", 6))
            y: redImgBox.y + (redImgBox.height - height) * 0.5
            source: (npPath && backend) ? backend.resolve_asset_url(npPath) : ""
            fillMode: Image.PreserveAspectFit
            smooth: true
            onVisibleChanged: scheduleBoundsUpdate()
            onWidthChanged: scheduleBoundsUpdate()
            onHeightChanged: scheduleBoundsUpdate()
            HoverHandler { id: redNameplateHover }
            ToolTip.visible: redNameplateHover.hovered
            ToolTip.text: "\uB808\uB4DC \uC5F0\uC2B9 \uBA85\uCC30 \uC774\uBBF8\uC9C0 (\uC5F0\uC2B9 \uB2E8\uACC4\uC5D0 \uB530\uB77C \uD45C\uC2DC)"
            // Nameplates should not resize the overlay window.
        }
        Canvas {
            property real line: 2.0
            property real shimmerPhase: 0.0
            width: parent.width + line * 2
            height: parent.height + line * 2
            x: -line
            y: -line
            z: 2
            renderTarget: Canvas.Image
            Timer {
                interval: 40
                repeat: true
                running: root.qmlPreviewEnabled && redImgBox.visible
                onTriggered: {
                    redImgBoxBorder.shimmerPhase = (redImgBoxBorder.shimmerPhase + 0.02) % 1.0
                    redImgBoxBorder.requestPaint()
                }
            }
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                var line = redImgBoxBorder.line
                var baseW = parent.width
                var baseH = parent.height
                var cx = line + baseW * 0.5
                var cy = line + baseH * 0.5
                ctx.lineWidth = line
                var p = redImgBoxBorder.shimmerPhase
                var s = Math.max(0.0, Math.min(1.0, p))
                var ang = -Math.PI * 2 * s
                var vx = Math.cos(ang)
                var vy = Math.sin(ang)
                var len = Math.max(width, height)
                var gx1 = cx - vx * len
                var gy1 = cy - vy * len
                var gx2 = cx + vx * len
                var gy2 = cy + vy * len
                var g = ctx.createLinearGradient(gx1, gy1, gx2, gy2)
                g.addColorStop(0.0, "#4a4f55")
                g.addColorStop(0.35, "#7c838b")
                g.addColorStop(0.5, "#f0f3f6")
                g.addColorStop(0.65, "#8b939c")
                g.addColorStop(1.0, "#4a4f55")
                ctx.strokeStyle = g
                ctx.beginPath()
                if (mask === "circle") {
                    var r = Math.min(baseW, baseH) * 0.5 + line * 0.5
                    ctx.arc(cx, cy, r, 0, Math.PI * 2)
                } else if (mask === "hex") {
                    var rr = Math.min(baseW, baseH) * 0.5 + line * 0.5
                    for (var i = 0; i < 6; i++) {
                        var ang = (Math.PI / 3) * i - Math.PI / 6
                        var px = cx + rr * Math.cos(ang)
                        var py = cy + rr * Math.sin(ang)
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                } else {
                    ctx.rect(line * 0.5, line * 0.5, baseW + line, baseH + line)
                }
                ctx.stroke()
            }
            Connections {
                target: backend
                function onOverlayPlayerMaskChanged() { redImgBoxBorder.requestPaint(); redImgBoxFill.requestPaint() }
            }
            Connections {
                target: backend
                function onRedImageRevChanged() { redImgBoxBorder.requestPaint(); redImgBoxFill.requestPaint() }
            }
            Connections {
                target: redImgBox
                function onWidthChanged() { redImgBoxBorder.requestPaint(); redImgBoxFill.requestPaint() }
                function onHeightChanged() { redImgBoxBorder.requestPaint(); redImgBoxFill.requestPaint() }
            }
            id: redImgBoxBorder
        }
        Item {
            id: redInnerFx
            anchors.fill: parent
            clip: true
            visible: root.qmlPreviewEnabled && backend && backend.redWinStreak >= 3
            z: 2
            Item {
                id: redInnerFxContent
                anchors.fill: parent
            Canvas {
                id: redDust
                anchors.fill: parent
                visible: root.qmlPreviewEnabled && root._cfg("inner.dust.enabled", true) && backend && (backend.redWinStreak || 0) >= root._cfg("inner.dust.min", 3)
                opacity: root._cfg("inner.dust.opacity", 0.12)
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height)
                    ctx.save(); ctx.beginPath(); var m = (backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    ctx.fillStyle = "rgba(255,255,255,0.15)"
                    for (var i=0; i<15; i++) {
                        ctx.beginPath(); ctx.arc(Math.random()*width, Math.random()*height, 0.5+Math.random(), 0, 6.28)
                        ctx.fill()
                    }
                    ctx.restore()
                }
            }
            Timer {
                interval: root._cfg("inner.dust.interval", 140)
                repeat: true
                running: root.qmlPreviewEnabled && redInnerFx.visible && redDust.visible
                onTriggered: redDust.requestPaint()
            }
            Canvas {
                id: redHUD
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.hud.enabled", true) && backend && backend.redWinStreak >= root._cfg("inner.hud.min", 6)
                property real rot: 0
                RotationAnimation on rot { from: 0; to: 360; duration: root._cfg("inner.hud.speed", 10000); loops: Animation.Infinite; running: root.qmlPreviewEnabled && redHUD.visible }
                onRotChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    
                    ctx.translate(width*0.5, height*0.5);
                    var hudAlpha = root._cfg("inner.hud.opacity", 0.5)
                    ctx.strokeStyle = "rgba(248, 113, 113, " + hudAlpha + ")"; ctx.lineWidth = 1.5
                    ctx.save(); ctx.rotate(rot*Math.PI/180)
                    ctx.beginPath(); ctx.arc(0, 0, width*0.35, 0, 1.8); ctx.stroke()
                    ctx.beginPath(); ctx.arc(0, 0, width*0.35, Math.PI, Math.PI+1.8); ctx.stroke(); ctx.restore()
                    ctx.save(); ctx.rotate(-rot*0.6*Math.PI/180)
                    ctx.strokeStyle = "rgba(248, 113, 113, " + (hudAlpha * 0.6) + ")"
                    ctx.beginPath(); ctx.arc(0, 0, width*0.42, 0.5, 2.5); ctx.stroke()
                    ctx.beginPath(); ctx.arc(0, 0, width*0.42, Math.PI+0.5, Math.PI+2.5); ctx.stroke(); ctx.restore()
                    
                    ctx.restore()
                }
            }
            Canvas {
                id: redElectricBits
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.electric.enabled", true) && backend && backend.redWinStreak >= root._cfg("inner.electric.min", 9)
                property var bolts: []
                Timer {
                    interval: root._cfg("inner.electric.interval", 100); repeat: true; running: root.qmlPreviewEnabled && redElectricBits.visible
                    onTriggered: {
                        var b = []; if (Math.random() > 0.4) {
                            var w = parent.width, h = parent.height
                            var x1 = Math.random()*w, y1 = Math.random()*h
                            var x2 = x1 + (Math.random()-0.5)*w*0.8, y2 = y1 + (Math.random()-0.5)*h*0.8
                            var opMin = root._cfg("inner.electric.opacity_min", 0.3)
                            var opMax = root._cfg("inner.electric.opacity_max", 0.9)
                            if (opMax < opMin) { var tmp = opMax; opMax = opMin; opMin = tmp }
                            var op = opMin + Math.random() * Math.max(0, opMax - opMin)
                            b.push({x1:x1, y1:y1, x2:x2, y2:y2, op: op})
                        }
                        parent.bolts = b; parent.requestPaint()
                    }
                }
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); if (bolts.length===0) return
                    ctx.save(); ctx.beginPath(); var m = (backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    ctx.strokeStyle = "#ffe4cf"; ctx.lineWidth = 1.8;
                    for (var i=0; i<bolts.length; i++) {
                        var b = bolts[i]; ctx.globalAlpha = b.op; ctx.beginPath(); ctx.moveTo(b.x1, b.y1)
                        var segs = 5, cx = b.x1, cy = b.y1
                        for (var j=1; j<=segs; j++) {
                            cx += (b.x2-b.x1)/segs + (Math.random()-0.5)*20
                            cy += (b.y2-b.y1)/segs + (Math.random()-0.5)*20
                            ctx.lineTo(cx, cy)
                        }
                        ctx.stroke()
                    }
                    ctx.restore()
                }
            }
            Canvas {
                id: redNovaPulse
                anchors.fill: parent
                renderTarget: Canvas.Image
                property real energy: 0; property real shock: 0
                visible: root.qmlPreviewEnabled && root._cfg("inner.core.enabled", true) && backend && backend.redWinStreak >= root._cfg("inner.core.min", 12)
                ParallelAnimation {
                    running: root.qmlPreviewEnabled && redNovaPulse.visible; loops: Animation.Infinite
                    SequentialAnimation {
                        NumberAnimation { target: redNovaPulse; property: "energy"; from: 0; to: 1; duration: root._cfg("inner.core.period", 900) * 0.28; easing.type: Easing.InSine }
                        NumberAnimation { target: redNovaPulse; property: "energy"; from: 1; to: 0; duration: root._cfg("inner.core.period", 900) * 0.72; easing.type: Easing.OutCubic }
                        PauseAnimation { duration: root._cfg("inner.core.period", 900) * 0.56 }
                    }
                    SequentialAnimation {
                        PauseAnimation { duration: 230 }
                        NumberAnimation { target: redNovaPulse; property: "shock"; from: 0; to: 1.2; duration: 900; easing.type: Easing.OutExpo }
                    }
                }
                onEnergyChanged: {
                    if (energy > 0.8) { redImgBox.jitterX = (Math.random()-0.5)*4; redImgBox.jitterY = (Math.random()-0.5)*4 }
                    else { redImgBox.jitterX = 0; redImgBox.jitterY = 0 }
                    requestPaint()
                }
                onShockChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    
                    var cx=width*0.5, cy=height*0.5
                    if(energy > 0) {
                        var maxAlpha = root._cfg("inner.core.opacity_max", 0.5)
                        var coreSize = root._cfg("inner.core.size", 0.35)
                        ctx.globalAlpha = energy * maxAlpha; ctx.fillStyle = "white"; ctx.fillRect(0,0,width,height)
                        var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, width * coreSize * energy)
                        g.addColorStop(0, "rgba(255,255,255,1)")
                        g.addColorStop(0.3, "rgba(248,113,113,0.8)")
                        g.addColorStop(1, "transparent")
                        ctx.globalAlpha = 1.0; ctx.fillStyle = g; ctx.fillRect(0,0,width,height)
                    }
                    if(shock > 0 && shock < 1) {
                        ctx.strokeStyle = "rgba(255,255,255,"+(1-shock)+")"; ctx.lineWidth = 3
                        ctx.beginPath(); ctx.arc(cx, cy, width*0.5*shock, 0, 6.28); ctx.stroke()
                    }
                    ctx.restore()
                }
            }

            Canvas {
                id: redChronoRift
                anchors.fill: parent
                renderTarget: Canvas.Image
                visible: root.qmlPreviewEnabled && root._cfg("inner.chrono.enabled", true) && backend && backend.redWinStreak >= root._cfg("inner.chrono.min", 30)
                property real p: 0
                NumberAnimation on p { from: 0; to: 1; duration: root._cfg("inner.chrono.speed", 1500); loops: Animation.Infinite; running: root.qmlPreviewEnabled && redChronoRift.visible }
                onPChanged: {
                    if (p > 0.9) { redImgBox.jitterX = (Math.random()-0.5)*8; redImgBox.jitterY = (Math.random()-0.5)*8 }
                    requestPaint()
                }
                onPaint: {
                    var ctx = getContext("2d"); ctx.clearRect(0,0,width,height); ctx.save()
                    var chronoAlpha = root._cfg("inner.chrono.opacity", 1.0)
                    ctx.beginPath(); var m=(backend?backend.overlayPlayerMask:"square")||"square"
                    if(m==="circle") ctx.arc(width*0.5, height*0.5, Math.min(width,height)*0.5, 0, 6.28)
                    else if(m==="hex") { var rr=Math.min(width,height)*0.5; for(var i=0;i<6;i++){ var a=(Math.PI/3)*i-Math.PI/6; ctx.lineTo(width*0.5+rr*Math.cos(a), height*0.5+rr*Math.sin(a)); } ctx.closePath(); }
                    else ctx.rect(0,0,width,height); ctx.clip()
                    var cx=width*0.5, cy=height*0.5
                    
                    // 1. Divine Singularity (Center)
                    var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, width*0.5)
                    g.addColorStop(0, "rgba(0,0,0,"+(p*0.9*chronoAlpha)+")")
                    g.addColorStop(0.2, "rgba(239,68,68,"+(p*0.6*chronoAlpha)+")")
                    g.addColorStop(0.4, "rgba(251,191,36,"+(p*0.4*chronoAlpha)+")") // Golden touch
                    g.addColorStop(0.6, "transparent")
                    ctx.fillStyle = g; ctx.fillRect(0,0,width,height)
                    
                    // 2. Divine Halo (Rotating Ring)
                    ctx.strokeStyle = "rgba(251,191,36,"+((0.3 + p*0.4)*chronoAlpha)+")"; ctx.lineWidth = 2.5; 
                    ctx.beginPath(); ctx.arc(cx, cy, width*0.45, p*6.28, p*6.28 + 2.5); ctx.stroke()
                    ctx.beginPath(); ctx.arc(cx, cy, width*0.45, p*6.28 + Math.PI, p*6.28 + Math.PI + 2.5); ctx.stroke()
                    
                    // 3. Divine Rays
                    ctx.strokeStyle = "rgba(255,255,255,"+((1-p)*chronoAlpha)+")"; ctx.lineWidth = 1; ctx.globalAlpha = (1-p) * chronoAlpha
                    for(var i=0; i<10; i++) {
                        var a = (i/10)*6.28 + p*0.5; var r1 = width*0.6, r2 = width*0.05
                        ctx.beginPath(); ctx.moveTo(cx+Math.cos(a)*r1, cy+Math.sin(a)*r1); ctx.lineTo(cx+Math.cos(a)*r2, cy+Math.sin(a)*r2); ctx.stroke()
                    }
                    
                    // 4. Ether Glimmer (Stars)
                    ctx.fillStyle = "white"; ctx.globalAlpha = p * 0.6 * chronoAlpha
                    for(var j=0; j<10; j++) {
                        var sx = (Math.sin(p*6.28 + j)*0.4 + 0.5)*width, sy = (Math.cos(p*6.28 + j*1.5)*0.4 + 0.5)*height
                        ctx.beginPath(); ctx.arc(sx, sy, 1, 0, 6.28); ctx.fill()
                    }
                    ctx.restore()
                }
            }

            }
        }
        Item {
            id: redBurst
            anchors.fill: parent
            visible: false
            z: 5
            transform: Translate { x: redImgBox.jitterX; y: redImgBox.jitterY }
            Canvas {
                id: redBurstMask
                anchors.fill: parent
                renderTarget: Canvas.Image
                property real flashOpacity: 0.0
                property real bloomOpacity: 0.0
                onPaint: {
                    if (width <= 0 || height <= 0) return
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var w = width
                    var h = height
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        var r = Math.min(w, h) * 0.5
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var rr = Math.min(w, h) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang)
                            var py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, w, h)
                    }
                    ctx.clip()

                    if (redBurstMask.flashOpacity > 0.0) {
                        ctx.globalAlpha = redBurstMask.flashOpacity
                        ctx.fillStyle = "#fff8e6"
                        ctx.fillRect(0, 0, w, h)
                    }
                    if (redBurstMask.bloomOpacity > 0.0) {
                        ctx.globalAlpha = redBurstMask.bloomOpacity
                        var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.6)
                        g.addColorStop(0.0, "#fff5dc")
                        g.addColorStop(0.6, Qt.lighter(root.auraColorFor(backend ? backend.redWinStreak : 0), 1.6))
                        g.addColorStop(1.0, "rgba(255,255,255,0)")
                        ctx.fillStyle = g
                        ctx.fillRect(0, 0, w, h)
                    }
                    ctx.restore()
                }
                onFlashOpacityChanged: requestPaint()
                onBloomOpacityChanged: requestPaint()
            }
            Rectangle {
                id: redRingBurst
                anchors.centerIn: parent
                width: parent.width * 0.6
                height: parent.height * 0.6
                radius: Math.min(width, height) / 2
                color: "transparent"
                border.color: "#ffe7b0"
                border.width: 3
                opacity: 0
                scale: 0.6
            }
            Rectangle {
                id: redBeam1
                width: parent.width * 1.6
                height: 4
                color: "#ffe9b8"
                opacity: 0
                anchors.centerIn: parent
                rotation: 12
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: redBeam2
                width: parent.width * 1.4
                height: 3
                color: "#fff4c2"
                opacity: 0
                anchors.centerIn: parent
                rotation: -18
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: redBeam3
                width: parent.width * 1.8
                height: 2
                color: "#ffffff"
                opacity: 0
                anchors.centerIn: parent
                rotation: 32
                visible: backend && (backend.overlayPlayerMask !== "circle" && backend.overlayPlayerMask !== "hex")
            }
            Rectangle {
                id: redHexRing
                anchors.centerIn: parent
                width: parent.width * 0.8
                height: parent.height * 0.8
                radius: 6
                color: "transparent"
                border.color: "#fff0c7"
                border.width: 2
                opacity: 0
                rotation: 15
                scale: 0.7
            }
        }
        SequentialAnimation {
            id: redBurstAnim
            running: false
            onStarted: redBurst.visible = true
            onStopped: redBurst.visible = false
            ParallelAnimation {
                NumberAnimation { target: redBurstMask; property: "flashOpacity"; from: 0.0; to: 1.0; duration: 70 }
                NumberAnimation { target: redBurstMask; property: "bloomOpacity"; from: 0.0; to: 0.8; duration: 110 }
                NumberAnimation { target: redRingBurst; property: "opacity"; from: 0.0; to: 0.9; duration: 130 }
                NumberAnimation { target: redRingBurst; property: "scale"; from: 0.6; to: 1.35; duration: 240 }
                NumberAnimation { target: redHexRing; property: "opacity"; from: 0.0; to: 0.7; duration: 150 }
                NumberAnimation { target: redHexRing; property: "scale"; from: 0.7; to: 1.2; duration: 260 }
                NumberAnimation { target: redBeam1; property: "opacity"; from: 0.0; to: 0.85; duration: 90 }
                NumberAnimation { target: redBeam2; property: "opacity"; from: 0.0; to: 0.75; duration: 90 }
                NumberAnimation { target: redBeam3; property: "opacity"; from: 0.0; to: 0.6; duration: 90 }
            }
            ParallelAnimation {
                NumberAnimation { target: redBurstMask; property: "flashOpacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: redBurstMask; property: "bloomOpacity"; to: 0.0; duration: 300 }
                NumberAnimation { target: redRingBurst; property: "opacity"; to: 0.0; duration: 300 }
                NumberAnimation { target: redHexRing; property: "opacity"; to: 0.0; duration: 320 }
                NumberAnimation { target: redBeam1; property: "opacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: redBeam2; property: "opacity"; to: 0.0; duration: 200 }
                NumberAnimation { target: redBeam3; property: "opacity"; to: 0.0; duration: 200 }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: function(mouse) {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    if (backend) backend.decrement_win("red")
                } else {
                    if (backend) backend.add_win("red")
                }
            }
        }
        Item {
            id: redFailFx
            anchors.fill: parent
            visible: root.qmlPreviewEnabled && redImgBox.visible
            z: 6
            opacity: root._redFailOpacity
            Timer {
                interval: 20
                repeat: true
                running: root.qmlPreviewEnabled && root._redFailOpacity > 0.0
                onTriggered: {
                    redImgBox.jitterX = (Math.random() - 0.5) * 9
                    redImgBox.jitterY = (Math.random() - 0.5) * 9
                }
                onRunningChanged: {
                    if (!running) { redImgBox.jitterX = 0; redImgBox.jitterY = 0; }
                }
            }
            Canvas {
                id: redFailCanvas
                anchors.fill: parent
                renderTarget: Canvas.Image
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                    var cx = width * 0.5
                    var cy = height * 0.5
                    var w = width
                    var h = height
                    ctx.save()
                    ctx.beginPath()
                    if (mask === "circle") {
                        var r = Math.min(w, h) * 0.5
                        ctx.arc(cx, cy, r, 0, Math.PI * 2)
                    } else if (mask === "hex") {
                        var rr = Math.min(w, h) * 0.5
                        for (var i = 0; i < 6; i++) {
                            var ang = (Math.PI / 3) * i - Math.PI / 6
                            var px = cx + rr * Math.cos(ang)
                            var py = cy + rr * Math.sin(ang)
                            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                        }
                        ctx.closePath()
                    } else {
                        ctx.rect(0, 0, w, h)
                    }
                    ctx.clip()
                    ctx.fillStyle = root._cfg("fail.tint", "#000000")
                    ctx.globalAlpha = 0.75
                    ctx.fillRect(0, 0, w, h)
                    ctx.globalAlpha = 1.0
                    ctx.strokeStyle = "#e6e6e6"
                    ctx.lineWidth = 2.6
                    ctx.shadowColor = "#ffffff"
                    ctx.shadowBlur = 6
                    for (var i = 0; i < root._redFailLines.length; i++) {
                        var pts = root._redFailLines[i]
                        if (!pts || pts.length === 0) continue
                        ctx.beginPath()
                        ctx.moveTo(pts[0].x, pts[0].y)
                        for (var j = 1; j < pts.length; j++) {
                            ctx.lineTo(pts[j].x, pts[j].y)
                        }
                        ctx.stroke()
                    }
                    ctx.shadowBlur = 0
                    ctx.restore()
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
            }
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                visible: root.qmlPreviewEnabled && root._redFailFlash > 0.0
                z: 2
                Canvas {
                    anchors.fill: parent
                    renderTarget: Canvas.Image
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var mask = (backend ? backend.overlayPlayerMask : "square") || "square"
                        var cx = width * 0.5
                        var cy = height * 0.5
                        var w = width
                        var h = height
                        ctx.save()
                        ctx.beginPath()
                        if (mask === "circle") {
                            var r = Math.min(w, h) * 0.5
                            ctx.arc(cx, cy, r, 0, Math.PI * 2)
                        } else if (mask === "hex") {
                            var rr = Math.min(w, h) * 0.5
                            for (var i = 0; i < 6; i++) {
                                var ang = (Math.PI / 3) * i - Math.PI / 6
                                var px = cx + rr * Math.cos(ang)
                                var py = cy + rr * Math.sin(ang)
                                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                            }
                            ctx.closePath()
                        } else {
                            ctx.rect(0, 0, w, h)
                        }
                        ctx.clip()
                        ctx.fillStyle = "#ffffff"
                        ctx.globalAlpha = root._redFailFlash * root._redFailOpacity
                        ctx.fillRect(0, 0, w, h)
                        ctx.restore()
                    }
                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    Connections {
                        target: backend
                        function onOverlayPlayerMaskChanged() { requestPaint() }
                    }
                }
            }
        }
        SequentialAnimation {
            id: redFailAnim
            running: false
            ParallelAnimation {
                NumberAnimation { target: root; property: "_redFailOpacity"; from: 0.0; to: root._cfg("fail.overlay_opacity", 0.85); duration: 280 }
                NumberAnimation { target: root; property: "_redFailFlash"; from: 0.0; to: 1.0; duration: 140 }
            }
            NumberAnimation { target: root; property: "_redFailFlash"; from: 1.0; to: 0.0; duration: 360 }
            PauseAnimation { duration: 360 }
            NumberAnimation { target: root; property: "_redFailOpacity"; from: root._cfg("fail.overlay_opacity", 0.85); to: 0.0; duration: 1800 }
        }
        Item {
            id: redWinTextWrap
            visible: root.qmlPreviewEnabled && _cfg("win_text.enabled", true) && backend && backend.redWinStreak > 0
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: parent.height * _cfg("win_text.offset_ratio", 0.22)
            z: 100
            implicitWidth: redWinTextBase.implicitWidth
            implicitHeight: redWinTextBase.implicitHeight
            width: implicitWidth
            height: implicitHeight
            property real pulseScale: 1.0
            property real pulseOpacity: 0.0
            Rectangle {
                id: redWinTextGlow
                anchors.centerIn: parent
                width: redWinTextBase.implicitWidth * 1.8
                height: redWinTextBase.implicitHeight * 1.6
                radius: height * 0.5
                color: _cfg("win_text.highlight_color", "#f8fbff")
                opacity: redWinTextWrap.pulseOpacity
                scale: redWinTextWrap.pulseScale
            }
            Text {
                id: redWinTextShadow
                text: winText(backend ? backend.redWinStreak : 0)
                color: _cfg("win_text.shadow_color", "#0b0f14")
                opacity: _cfg("win_text.shadow_opacity", 0.6)
                font.pixelSize: winTextSize(redImgBox.height)
                font.bold: true
                renderType: Text.NativeRendering
                antialiasing: true
                smooth: true
                x: 0
                y: 1
            }
            Text {
                id: redWinTextBase
                text: winText(backend ? backend.redWinStreak : 0)
                color: _cfg("win_text.base_color", "#d6dbe0")
                font.pixelSize: winTextSize(redImgBox.height)
                font.bold: true
                style: Text.Outline
                styleColor: Qt.rgba(
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).r,
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).g,
                    Qt.color(_cfg("win_text.outline_color", "#2b2f34")).b,
                    0.55
                )
                renderType: Text.NativeRendering
                antialiasing: true
                smooth: true
            }
            Rectangle {
                id: redWinTextHighlightClip
                anchors.left: redWinTextBase.left
                anchors.right: redWinTextBase.right
                anchors.top: redWinTextBase.top
                height: redWinTextBase.implicitHeight * _cfg("win_text.highlight_height", 0.55)
                color: "transparent"
                clip: true
                Text {
                    text: winText(backend ? backend.redWinStreak : 0)
                    color: _cfg("win_text.highlight_color", "#f8fbff")
                    opacity: 0.65
                    font.pixelSize: winTextSize(redImgBox.height)
                    font.bold: true
                    renderType: Text.NativeRendering
                    antialiasing: true
                    smooth: true
                    y: -1
                }
            }
            SequentialAnimation {
                id: redWinTextPulse
                running: false
                ParallelAnimation {
                    NumberAnimation { target: redWinTextWrap; property: "pulseOpacity"; from: 0.0; to: 0.7; duration: 90 }
                    NumberAnimation { target: redWinTextWrap; property: "pulseScale"; from: 0.9; to: 1.25; duration: 140; easing.type: Easing.OutQuad }
                }
                ParallelAnimation {
                    NumberAnimation { target: redWinTextWrap; property: "pulseOpacity"; to: 0.0; duration: 220; easing.type: Easing.OutQuad }
                    NumberAnimation { target: redWinTextWrap; property: "pulseScale"; to: 1.0; duration: 240; easing.type: Easing.OutQuad }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = redImgBox; root.lastDragItem = redImgBox; root.selectedItem = redImgBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(redImgBox, redImgBox.x, redImgBox.y)
                redImgBox.x = p.x
                redImgBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = redImgBox.width
                    parent.startH = redImgBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    redImgBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    redImgBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowRedImg) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowRedImg) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("red_img", !backend.overlayShowRedImg); saveLayout() }
            }
        }
    }

    Rectangle {
        id: redNameBox
        parent: scaledRoot
        property int borderW: Math.max(1, root.styleVal("red_name", "border_width", 1))
        property color borderCol: root.styleColor("red_name", "border_color", "#8f2d2d", "border_opacity", 1.0)
        color: root._matchBg(redNameBox, root.styleColor("red_name", "bg_color", "#d14b4b", "bg_opacity", 1.0))
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowRedName))
        opacity: (editMode && backend && !backend.overlayShowRedName) ? 0.25 : 1.0
        border.color: "transparent"
        border.width: 0
        radius: root._matchRadius(redNameBox, 2)
        HoverHandler { id: redNameHover }
        ToolTip.visible: redNameHover.hovered
        ToolTip.text: "\uB808\uB4DC \uCF54\uB108 \uB2C9\uB124\uC784. \uC88C\uD074\uB9AD: \uD504\uB85C\uD544 \uBD88\uB7EC\uC624\uAE30  \u00B7  \uC6B0\uD074\uB9AD: \uD504\uB85C\uD544 \uB4F1\uB85D/\uC218\uC815"
        onVisibleChanged: scheduleBoundsUpdate()
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            id: redNameText
            anchors.centerIn: parent
            text: backend ? backend.redName : ""
            width: parent.width - 10
            height: parent.height - 6
            font.pixelSize: root.styleFontSize("red_name", Math.max(14, Math.min(parent.height * 0.5, 28)))
            font.family: root.styleVal("red_name", "font_family", "Noto Sans KR")
            font.bold: root.styleVal("red_name", "font_bold", true)
            font.weight: root.styleVal("red_name", "font_weight", Font.Black)
            color: root.styleColor("red_name", "text_color", "#ffffff", "text_opacity", 1.0)
            elide: Text.ElideRight
            fontSizeMode: Text.Fit
            minimumPixelSize: 10
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        Rectangle {
            width: Math.max(2, root.styleVal("red_name", "badge_width", Math.max(8, parent.height * 0.18)))
            height: parent.height
            radius: 0
            color: root.styleColor("red_name", "badge_color", "#ef4444")
            anchors.verticalCenter: parent.verticalCenter
            x: root.styleVal("red_name", "badge_side", "right") === "right" ? parent.width : -width
            z: 100
            visible: root.styleVal("red_name", "badge_enabled", true) && (editMode || (backend && backend.redName && backend.redName.length > 0))
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                border.color: Qt.rgba(1, 1, 1, 0.45)
                border.width: 1
                radius: 2
            }
            Rectangle {
                anchors.fill: parent
                radius: 2
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.2) }
                    GradientStop { position: 0.5; color: "transparent" }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.1) }
                }
            }
        }
        Rectangle {
            visible: !root._touchingSide(redNameBox, "top")
            color: root._matchBorder(redNameBox, redNameBox.borderCol)
            x: 0
            y: 0
            width: redNameBox.width
            height: redNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(redNameBox, "bottom")
            color: root._matchBorder(redNameBox, redNameBox.borderCol)
            x: 0
            y: redNameBox.height - redNameBox.borderW
            width: redNameBox.width
            height: redNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(redNameBox, "left")
            color: root._matchBorder(redNameBox, redNameBox.borderCol)
            x: 0
            y: 0
            width: redNameBox.borderW
            height: redNameBox.height
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(redNameBox, "right")
            color: root._matchBorder(redNameBox, redNameBox.borderCol)
            x: redNameBox.width - redNameBox.borderW
            y: 0
            width: redNameBox.borderW
            height: redNameBox.height
            z: 6
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
            onClicked: function(mouse) {
                if (moved) return
                if (mouse.button === Qt.RightButton) {
                    var p = redNameBox.mapToItem(root.contentItem, mouse.x, mouse.y)
                    showProfileMenu("red", p.x, p.y)
                } else {
                    backend.select_player("red")
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = redNameBox; root.lastDragItem = redNameBox; root.selectedItem = redNameBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(redNameBox, redNameBox.x, redNameBox.y)
                redNameBox.x = p.x
                redNameBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = redNameBox.width
                    parent.startH = redNameBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    redNameBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    redNameBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowRedName) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowRedName) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("red_name", !backend.overlayShowRedName); saveLayout() }
            }
        }
    }

    Item {
        id: blueWinTextTopLayer
        parent: scaledRoot
        x: blueImgBox.x + (blueImgBox.width - width) * 0.5
        y: blueImgBox.y + (blueImgBox.height - height) * 0.5 + blueImgBox.height * root._cfg("win_text.offset_ratio", 0.22)
        width: blueWinTopText.implicitWidth
        height: blueWinTopText.implicitHeight
        visible: root.qmlPreviewEnabled && root._cfg("win_text.enabled", true) && backend && backend.blueWinStreak > 0
        z: 10000
        Text {
            id: blueWinTopShadow
            text: root.winText(backend ? backend.blueWinStreak : 0)
            x: 2
            y: 2
            color: "#000000"
            opacity: 0.9
            font.pixelSize: Math.max(root.winTextSize(blueImgBox.height), 24)
            font.bold: true
            renderType: Text.NativeRendering
        }
        Text {
            id: blueWinTopText
            text: root.winText(backend ? backend.blueWinStreak : 0)
            color: root._cfg("win_text.highlight_color", "#f8fbff")
            font.pixelSize: Math.max(root.winTextSize(blueImgBox.height), 24)
            font.bold: true
            style: Text.Outline
            styleColor: "#000000"
            renderType: Text.NativeRendering
        }
    }

    Item {
        id: redWinTextTopLayer
        parent: scaledRoot
        x: redImgBox.x + (redImgBox.width - width) * 0.5
        y: redImgBox.y + (redImgBox.height - height) * 0.5 + redImgBox.height * root._cfg("win_text.offset_ratio", 0.22)
        width: redWinTopText.implicitWidth
        height: redWinTopText.implicitHeight
        visible: root.qmlPreviewEnabled && root._cfg("win_text.enabled", true) && backend && backend.redWinStreak > 0
        z: 10000
        Text {
            id: redWinTopShadow
            text: root.winText(backend ? backend.redWinStreak : 0)
            x: 2
            y: 2
            color: "#000000"
            opacity: 0.9
            font.pixelSize: Math.max(root.winTextSize(redImgBox.height), 24)
            font.bold: true
            renderType: Text.NativeRendering
        }
        Text {
            id: redWinTopText
            text: root.winText(backend ? backend.redWinStreak : 0)
            color: root._cfg("win_text.highlight_color", "#f8fbff")
            font.pixelSize: Math.max(root.winTextSize(redImgBox.height), 24)
            font.bold: true
            style: Text.Outline
            styleColor: "#000000"
            renderType: Text.NativeRendering
        }
    }

    Rectangle {
        id: arenaNameBox
        parent: scaledRoot
        property int borderW: Math.max(1, root.styleVal("arena", "border_width", 1))
        property color borderCol: root.styleColor("arena", "border_color", "#555555", "border_opacity", 1.0)
        color: root._matchBg(arenaNameBox, root.styleColor("arena", "bg_color", "#222222", "bg_opacity", 1.0))
        visible: root.qmlPreviewEnabled && (editMode ? true : (backend && backend.overlayShowArenaName))
        opacity: (editMode && backend && !backend.overlayShowArenaName) ? 0.25 : 1.0
        border.color: "transparent"
        border.width: 0
        radius: root._matchRadius(arenaNameBox, 2)
        HoverHandler { id: arenaHover }
        ToolTip.visible: arenaHover.hovered
        ToolTip.text: "\uC544\uB808\uB098 \uC774\uB984"
        onVisibleChanged: scheduleBoundsUpdate()
        onXChanged: scheduleBoundsUpdate()
        onYChanged: scheduleBoundsUpdate()
        onWidthChanged: scheduleBoundsUpdate()
        onHeightChanged: scheduleBoundsUpdate()
        Text {
            anchors.centerIn: parent
            text: backend ? backend.arenaName : ""
            font.pixelSize: root.styleFontSize("arena", Math.max(12, Math.min(parent.height * 0.6, 20)))
            font.bold: root.styleVal("arena", "font_bold", true)
            font.weight: root.styleVal("arena", "font_weight", 700)
            font.family: root.styleVal("arena", "font_family", "Malgun Gothic")
            color: root.styleColor("arena", "text_color", "#ffffff", "text_opacity", 1.0)
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        Rectangle {
            visible: !root._touchingSide(arenaNameBox, "top")
            color: root._matchBorder(arenaNameBox, arenaNameBox.borderCol)
            x: 0
            y: 0
            width: arenaNameBox.width
            height: arenaNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(arenaNameBox, "bottom")
            color: root._matchBorder(arenaNameBox, arenaNameBox.borderCol)
            x: 0
            y: arenaNameBox.height - arenaNameBox.borderW
            width: arenaNameBox.width
            height: arenaNameBox.borderW
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(arenaNameBox, "left")
            color: root._matchBorder(arenaNameBox, arenaNameBox.borderCol)
            x: 0
            y: 0
            width: arenaNameBox.borderW
            height: arenaNameBox.height
            z: 6
        }
        Rectangle {
            visible: !root._touchingSide(arenaNameBox, "right")
            color: root._matchBorder(arenaNameBox, arenaNameBox.borderCol)
            x: arenaNameBox.width - arenaNameBox.borderW
            y: 0
            width: arenaNameBox.borderW
            height: arenaNameBox.height
            z: 6
        }
        MouseArea {
            anchors.fill: parent
            enabled: !editMode
            acceptedButtons: Qt.LeftButton
            property real pressX: 0
            property real pressY: 0
            property bool moved: false
            onPressed: {
                pressX = mouse.x
                pressY = mouse.y
                moved = false
            }
            onPositionChanged: {
                if (!moved && (mouse.buttons & Qt.LeftButton)) {
                    var dx = mouse.x - pressX
                    var dy = mouse.y - pressY
                    if ((dx * dx + dy * dy) > 36) {
                        moved = true
                        root.startSystemMove()
                    }
                }
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: editMode
            drag.target: parent
            onPressed: { root.activeDragItem = arenaNameBox; root.lastDragItem = arenaNameBox; root.selectedItem = arenaNameBox; keyFocus.forceActiveFocus() }
            onPositionChanged: {
                var p = root.snapPos(arenaNameBox, arenaNameBox.x, arenaNameBox.y)
                arenaNameBox.x = p.x
                arenaNameBox.y = p.y
            }
            onReleased: { root.activeDragItem = null; saveLayout() }
        }
        Rectangle {
            width: 10; height: 10; radius: 2
            color: "#ffffff"; border.color: "#333"
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            visible: editMode
            property real startW
            property real startH
            property real startX
            property real startY
            MouseArea {
                anchors.fill: parent
                onPressed: {
                    parent.startW = arenaNameBox.width
                    parent.startH = arenaNameBox.height
                    parent.startX = mouse.x
                    parent.startY = mouse.y
                }
                onPositionChanged: {
                    arenaNameBox.width = Math.max(1, root.snapValue(parent.startW + (mouse.x - parent.startX), root.gridSize))
                    arenaNameBox.height = Math.max(1, root.snapValue(parent.startH + (mouse.y - parent.startY), root.gridSize))
                }
                onReleased: saveLayout()
            }
        }
        Rectangle {
            width: 34; height: 14; radius: 2
            color: (backend && backend.overlayShowArenaName) ? "#ef4444" : "#22c55e"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 2
            anchors.topMargin: 2
            visible: editMode
            z: 50
            Text {
                anchors.centerIn: parent
                text: (backend && backend.overlayShowArenaName) ? "???" : "??뽯뻻"
                color: "#ffffff"
                font.pixelSize: 10
            }
            MouseArea {
                anchors.fill: parent
                onPressed: mouse.accepted = true
                onClicked: { if (editMode) pushHistory(); if (backend) backend.set_overlay_visible("arena_name", !backend.overlayShowArenaName); saveLayout() }
            }
        }
    }

}
