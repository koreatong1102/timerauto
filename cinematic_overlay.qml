import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: root
    title: "timerauto cinematic overlay"
    visible: true
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus

    property bool tekkenPreset: backend && backend.overlayPreset === "tekken8"
    property bool cinematicEnabled: backend && backend.overlayShowCinematic
    property bool roundEnabled: backend && backend.overlayShowRound
    property string _vsKey: ""
    property string _roundIntroKey: ""
    property real _vsOpacity: 0
    property real _vsScale: 0.9
    property real _introOpacity: 0
    property real _introScale: 0.9
    property string _introText: ""
    property string _introSubText: ""
    property real _koOpacity: 0
    property real _koScale: 0.8
    property real _koKOpacity: 0
    property real _koOOpacity: 0
    property real _koKScale: 1
    property real _koOScale: 1
    property real _koKY: -240
    property real _koOY: -240
    property real _koKRot: -12
    property real _koORot: 12
    property real _koShakeX: 0
    property bool _koSplitMode: true
    property string _koText: ""

    Rectangle {
        anchors.fill: parent
        color: "#000000"
        opacity: root.tekkenPreset && root.cinematicEnabled ? 0.005 : 0
    }

    function sideName(side) {
        if (!backend)
            return side === "blue" ? "BLUE" : "RED"
        var name = side === "blue" ? backend.blueName : backend.redName
        name = String(name || "").trim()
        if (name.length <= 0)
            return side === "blue" ? "BLUE" : "RED"
        return name
    }

    function maybeStartVsIntro() {
        if (!tekkenPreset || !cinematicEnabled || !roundEnabled || !backend)
            return
        var key = String(backend.blueName || "") + "\u001f" + String(backend.redName || "")
        if (key === "\u001f" || key === _vsKey)
            return
        _vsKey = key
        vsIntroAnim.restart()
    }

    function maybeStartRoundIntro(force) {
        if (!tekkenPreset || !cinematicEnabled || !backend)
            return
        var key = String(backend.roundText || "")
        if (key === "" || (!force && key === _roundIntroKey))
            return
        _roundIntroKey = key
        _introText = roundTitle(key)
        _introSubText = "READY"
        roundIntroAnim.restart()
    }

    function roundTitle(raw) {
        var s = String(raw || "")
        var m = s.match(/RD\\s*(\\d+)/i)
        if (m && m.length > 1)
            return "ROUND " + m[1]
        return s.replace("\n", " ").toUpperCase()
    }

    Item {
        anchors.fill: parent
        visible: root.tekkenPreset && root.cinematicEnabled

        Item {
            anchors.fill: parent
            opacity: root._vsOpacity
            scale: root._vsScale

            Rectangle {
                anchors.fill: parent
                color: "#020617"
                opacity: 0.72
            }

            Image {
                source: "image://players/blue?rev=" + (backend ? backend.blueImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                fillMode: Image.PreserveAspectFit
                width: Math.min(parent.width * 0.28, 430)
                height: Math.min(parent.height * 0.62, 620)
                x: parent.width * 0.075
                y: parent.height * 0.13
            }

            Image {
                source: "image://players/red?rev=" + (backend ? backend.redImageRev : 0)
                cache: false
                asynchronous: true
                smooth: true
                mirror: true
                fillMode: Image.PreserveAspectFit
                width: Math.min(parent.width * 0.28, 430)
                height: Math.min(parent.height * 0.62, 620)
                x: parent.width - width - parent.width * 0.075
                y: parent.height * 0.13
            }

            Rectangle {
                id: vsBlueNameplate
                x: parent.width * 0.05
                y: parent.height * 0.72
                width: parent.width * 0.33
                height: 74
                color: "#020617"
                opacity: 0.72
                border.color: "#3b82f6"
                border.width: 2
                transform: Rotation { origin.x: vsBlueNameplate.width * 0.5; origin.y: 37; angle: -2 }
            }

            Rectangle {
                id: vsRedNameplate
                x: parent.width * 0.62
                y: parent.height * 0.72
                width: parent.width * 0.33
                height: 74
                color: "#020617"
                opacity: 0.72
                border.color: "#ef4444"
                border.width: 2
                transform: Rotation { origin.x: vsRedNameplate.width * 0.5; origin.y: 37; angle: 2 }
            }

            Text {
                x: parent.width * 0.065
                y: parent.height * 0.735
                width: parent.width * 0.30
                text: root.sideName("blue")
                color: "#dbeafe"
                font.pixelSize: Math.max(34, Math.min(62, parent.width / 28))
                font.bold: true
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#020617"
            }

            Text {
                x: parent.width * 0.635
                y: parent.height * 0.735
                width: parent.width * 0.30
                text: root.sideName("red")
                color: "#fee2e2"
                horizontalAlignment: Text.AlignRight
                font.pixelSize: Math.max(34, Math.min(62, parent.width / 28))
                font.bold: true
                elide: Text.ElideRight
                style: Text.Outline
                styleColor: "#020617"
            }

            Text {
                anchors.centerIn: parent
                text: "VS"
                color: "#fef3c7"
                font.pixelSize: Math.max(120, Math.min(220, parent.width / 7))
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }
        }

        Text {
            anchors.centerIn: parent
            text: root._introText
            opacity: root._introOpacity
            scale: root._introScale
            color: "#fefce8"
            font.pixelSize: Math.max(88, Math.min(170, parent.width / 10))
            font.bold: true
            style: Text.Outline
            styleColor: "#1e293b"
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.verticalCenter
            anchors.topMargin: Math.max(58, parent.height * 0.095)
            text: root._introSubText
            opacity: root._introOpacity
            scale: root._introScale
            color: "#facc15"
            font.pixelSize: Math.max(46, Math.min(92, parent.width / 18))
            font.bold: true
            style: Text.Outline
            styleColor: "#1e293b"
        }

        Item {
            id: koLayer
            anchors.centerIn: parent
            width: parent.width
            height: Math.max(180, Math.min(320, parent.width / 5))
            opacity: root._koOpacity
            x: root._koShakeX
            visible: root._koOpacity > 0.01

            Text {
                id: koSingleText
                anchors.centerIn: parent
                visible: !root._koSplitMode
                text: root._koText
                scale: root._koScale
                color: "#fff7ed"
                font.pixelSize: Math.max(130, Math.min(260, koLayer.width / 7))
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }

            Text {
                id: koKText
                visible: root._koSplitMode
                text: "K"
                opacity: root._koKOpacity
                x: koLayer.width * 0.5 - width - Math.max(8, koLayer.width * 0.012)
                y: (koLayer.height - height) * 0.5 + root._koKY
                scale: root._koKScale
                rotation: root._koKRot
                color: "#fff7ed"
                font.pixelSize: Math.max(150, Math.min(285, koLayer.width / 6.2))
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }

            Text {
                id: koDotText
                visible: root._koSplitMode && root._koOOpacity > 0.01
                text: "."
                opacity: Math.min(root._koKOpacity, root._koOOpacity)
                anchors.verticalCenter: parent.verticalCenter
                x: koLayer.width * 0.5 - width * 0.5
                color: "#facc15"
                font.pixelSize: Math.max(82, Math.min(150, koLayer.width / 12))
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }

            Text {
                id: koOText
                visible: root._koSplitMode
                text: "O"
                opacity: root._koOOpacity
                x: koLayer.width * 0.5 + Math.max(8, koLayer.width * 0.012)
                y: (koLayer.height - height) * 0.5 + root._koOY
                scale: root._koOScale
                rotation: root._koORot
                color: "#fff7ed"
                font.pixelSize: Math.max(150, Math.min(285, koLayer.width / 6.2))
                font.bold: true
                style: Text.Outline
                styleColor: "#7f1d1d"
            }
        }
    }

    Connections {
        target: backend
        function onOverlayPresetChanged() {
            root.tekkenPreset = backend && backend.overlayPreset === "tekken8"
            if (!root.tekkenPreset || !root.cinematicEnabled) {
                root._vsOpacity = 0
                root._introOpacity = 0
                root._koOpacity = 0
            }
        }
        function onOverlayShowCinematicChanged() {
            root.cinematicEnabled = backend && backend.overlayShowCinematic
            if (!root.cinematicEnabled) {
                root._vsOpacity = 0
                root._introOpacity = 0
                root._koOpacity = 0
            }
        }
        function onOverlayShowRoundChanged() {
            root.roundEnabled = backend && backend.overlayShowRound
            if (!root.roundEnabled) {
                roundIntroAnim.stop()
                root._introOpacity = 0
            }
        }
        function onVsIntroResetRequested() {
            root._vsKey = ""
            root.maybeStartVsIntro()
        }
        function onRoundIntroRequested() { root.maybeStartRoundIntro(true) }
        function onSpectatorEffectRequested(side, kind) {
            if (!root.tekkenPreset || !root.cinematicEnabled)
                return
            if (kind === "knockdown") {
                root._koText = "KNOCK DOWN"
                root._koSplitMode = false
                koAnim.restart()
            } else if (kind === "tko") {
                root._koText = "TECHNICAL KNOCKOUT"
                root._koSplitMode = false
                koAnim.restart()
            }
        }
    }

    SequentialAnimation {
        id: vsIntroAnim
        ScriptAction { script: { root._vsOpacity = 0; root._vsScale = 0.86 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_vsOpacity"; to: 1; duration: 140 }
            NumberAnimation { target: root; property: "_vsScale"; to: 1.0; duration: 180; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 1400 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_vsOpacity"; to: 0; duration: 300; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_vsScale"; to: 1.12; duration: 300; easing.type: Easing.InQuad }
        }
    }

    SequentialAnimation {
        id: roundIntroAnim
        ScriptAction { script: { root._introOpacity = 0; root._introScale = 0.82 } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_introOpacity"; to: 1; duration: 120 }
            NumberAnimation { target: root; property: "_introScale"; to: 1.06; duration: 160; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 880 }
        ScriptAction { script: { root._introText = "FIGHT"; root._introSubText = "" } }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_introOpacity"; from: 0.5; to: 1; duration: 70 }
            NumberAnimation { target: root; property: "_introScale"; from: 0.82; to: 1.15; duration: 120; easing.type: Easing.OutBack }
        }
        PauseAnimation { duration: 620 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_introOpacity"; to: 0; duration: 260 }
            NumberAnimation { target: root; property: "_introScale"; to: 1.34; duration: 260 }
        }
    }

    SequentialAnimation {
        id: koAnim
        ScriptAction {
            script: {
                root._koOpacity = 1
                root._koScale = root._koSplitMode ? 1.0 : 0.55
                root._koKOpacity = root._koSplitMode ? 0 : 0
                root._koOOpacity = root._koSplitMode ? 0 : 0
                root._koKScale = 2.2
                root._koOScale = 2.2
                root._koKY = -260
                root._koOY = -260
                root._koKRot = -18
                root._koORot = 18
                root._koShakeX = 0
            }
        }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_koKOpacity"; to: root._koSplitMode ? 1 : 0; duration: 55 }
            NumberAnimation { target: root; property: "_koKY"; to: 0; duration: 170; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_koKScale"; to: 1.0; duration: 170; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_koKRot"; to: -3; duration: 170; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_koOpacity"; to: 1; duration: 50 }
            NumberAnimation { target: root; property: "_koScale"; to: root._koSplitMode ? 1.0 : 1.16; duration: 140; easing.type: Easing.OutBack }
        }
        SequentialAnimation {
            NumberAnimation { target: root; property: "_koShakeX"; to: -18; duration: 24 }
            NumberAnimation { target: root; property: "_koShakeX"; to: 14; duration: 30 }
            NumberAnimation { target: root; property: "_koShakeX"; to: 0; duration: 42 }
        }
        PauseAnimation { duration: 80 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_koOOpacity"; to: root._koSplitMode ? 1 : 0; duration: 55 }
            NumberAnimation { target: root; property: "_koOY"; to: 0; duration: 170; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_koOScale"; to: 1.0; duration: 170; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_koORot"; to: 3; duration: 170; easing.type: Easing.OutBack }
            NumberAnimation { target: root; property: "_koScale"; to: root._koSplitMode ? 1.0 : 1.2; duration: 120; easing.type: Easing.OutBack }
        }
        SequentialAnimation {
            NumberAnimation { target: root; property: "_koShakeX"; to: 20; duration: 24 }
            NumberAnimation { target: root; property: "_koShakeX"; to: -12; duration: 30 }
            NumberAnimation { target: root; property: "_koShakeX"; to: 0; duration: 48 }
        }
        PauseAnimation { duration: 950 }
        ParallelAnimation {
            NumberAnimation { target: root; property: "_koOpacity"; to: 0; duration: 400; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_koScale"; to: 1.38; duration: 400; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_koKScale"; to: 1.25; duration: 400; easing.type: Easing.InQuad }
            NumberAnimation { target: root; property: "_koOScale"; to: 1.25; duration: 400; easing.type: Easing.InQuad }
        }
    }
}
