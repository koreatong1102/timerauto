import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: ctrl
    width: 300
    height: 60
    visible: true
    color: "#1e1e1e"
    title: "Timer Controls"
    flags: Qt.Window | Qt.WindowStaysOnTopHint

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Button {
            text: backend.startLabel
            Layout.fillWidth: true
            onClicked: backend.toggle_timer()
        }
        Button {
            text: "Reset"
            Layout.fillWidth: true
            onClicked: backend.reset_timer()
        }
        Button {
            text: "Settings"
            Layout.fillWidth: true
            onClicked: backend.open_settings()
        }
    }
}
