import Foundation
import Capacitor

/// iOS counterpart of android/.../CallPlugin.kt — same JS-facing API so your
/// frontend bridge code (www/js/native-call-bridge.js) works unmodified on
/// both platforms.
@objc(CallPlugin)
public class CallPlugin: CAPPlugin {

    public override func load() {
        CallManager.shared.start()

        NotificationCenter.default.addObserver(
            self, selector: #selector(onVoipTokenUpdated(_:)),
            name: .thookuVoipTokenUpdated, object: nil)

        NotificationCenter.default.addObserver(
            self, selector: #selector(onCallAnswered(_:)),
            name: .thookuCallAnswered, object: nil)
    }

    @objc func getVoipToken(_ call: CAPPluginCall) {
        if let token = CallManager.shared.voipToken {
            call.resolve(["token": token])
        } else {
            // Token isn't available yet on first launch; JS should retry
            // after a short delay or listen for a token-updated event if
            // you want to add one symmetrically to Android's flow.
            call.reject("VoIP token not yet available")
        }
    }

    @objc private func onVoipTokenUpdated(_ note: Notification) {
        guard let token = note.object as? String else { return }
        notifyListeners("voipTokenUpdated", data: ["token": token])
    }

    @objc private func onCallAnswered(_ note: Notification) {
        guard let data = note.object as? [String: String] else { return }
        notifyListeners("incomingCallAnswered", data: data)
    }
}
