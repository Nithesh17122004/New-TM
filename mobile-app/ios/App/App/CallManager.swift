import Foundation
import PushKit
import CallKit
import UIKit

/// Owns the VoIP push registry (wakes the app even if fully terminated) and
/// the CallKit provider (native "incoming call" UI, works over the lock
/// screen, silent mode, everything). This is Apple's sanctioned mechanism
/// for exactly this use case — there is no other reliable way to ring an
/// iOS app in the background without it.
final class CallManager: NSObject, PKPushRegistryDelegate, CXProviderDelegate {

    static let shared = CallManager()

    private var pushRegistry: PKPushRegistry!
    private var provider: CXProvider!
    private let callController = CXCallController()

    // Latest call metadata, read by CallPlugin once JS asks for it after answer.
    private(set) var pendingAnsweredCall: [String: String]?

    override init() {
        super.init()
        let config = CXProviderConfiguration(localizedName: "Thooku Madurai")
        config.supportsVideo = false
        config.maximumCallGroups = 1
        config.maximumCallsPerCallGroup = 1
        config.supportedHandleTypes = [.generic]
        provider = CXProvider(configuration: config)
        provider.setDelegate(self, queue: nil)
    }

    func start() {
        pushRegistry = PKPushRegistry(queue: .main)
        pushRegistry.delegate = self
        pushRegistry.desiredPushTypes = [.voIP]
    }

    var voipToken: String? {
        pushRegistry?.pushToken(for: .voIP)?.map { String(format: "%02x", $0) }.joined()
    }

    // MARK: - PKPushRegistryDelegate

    func pushRegistry(_ registry: PKPushRegistry, didUpdate pushCredentials: PKPushCredentials, for type: PKPushType) {
        guard type == .voIP else { return }
        let token = pushCredentials.token.map { String(format: "%02x", $0) }.joined()
        UserDefaults.standard.set(token, forKey: "thooku_voip_token")
        NotificationCenter.default.post(name: .thookuVoipTokenUpdated, object: token)
    }

    func pushRegistry(_ registry: PKPushRegistry, didInvalidatePushTokenFor type: PKPushType) {
        UserDefaults.standard.removeObject(forKey: "thooku_voip_token")
    }

    /// This is the critical method: iOS calls it even if your app was fully
    /// killed, as long as this VoIP payload arrives. You MUST report a call
    /// to CallKit synchronously in here or Apple will kill your app for
    /// violating the PushKit contract.
    func pushRegistry(_ registry: PKPushRegistry,
                       didReceiveIncomingPushWith payload: PKPushPayload,
                       for type: PKPushType,
                       completion: @escaping () -> Void) {
        guard type == .voIP else { completion(); return }
        let data = payload.dictionaryPayload
        let callId = data["callId"] as? String ?? UUID().uuidString
        let orderId = data["orderId"] as? String ?? ""
        let callerName = data["callerName"] as? String ?? "Incoming Call"
        let callerRole = data["callerRole"] as? String ?? ""

        let update = CXCallUpdate()
        update.remoteHandle = CXHandle(type: .generic, value: callerName)
        update.hasVideo = false
        update.localizedCallerName = callerName

        let callUUID = UUID()
        pendingCallIds[callUUID] = ["callId": callId, "orderId": orderId, "callerName": callerName, "callerRole": callerRole]

        provider.reportNewIncomingCall(with: callUUID, update: update) { error in
            if let error = error {
                print("ThookuCall: reportNewIncomingCall error \(error)")
            }
            completion()
        }
    }

    private var pendingCallIds: [UUID: [String: String]] = [:]

    // MARK: - CXProviderDelegate

    func providerDidReset(_ provider: CXProvider) {}

    func provider(_ provider: CXProvider, perform action: CXAnswerCallAction) {
        // User tapped Answer on the native lock-screen call UI.
        if let data = pendingCallIds[action.callUUID] {
            pendingAnsweredCall = data
            NotificationCenter.default.post(name: .thookuCallAnswered, object: data)
        }
        action.fulfill()
    }

    func provider(_ provider: CXProvider, perform action: CXEndCallAction) {
        if let data = pendingCallIds[action.callUUID] {
            NotificationCenter.default.post(name: .thookuCallDeclinedOrEnded, object: data)
            pendingCallIds.removeValue(forKey: action.callUUID)
        }
        action.fulfill()
    }
}

extension Notification.Name {
    static let thookuVoipTokenUpdated = Notification.Name("thookuVoipTokenUpdated")
    static let thookuCallAnswered = Notification.Name("thookuCallAnswered")
    static let thookuCallDeclinedOrEnded = Notification.Name("thookuCallDeclinedOrEnded")
}
