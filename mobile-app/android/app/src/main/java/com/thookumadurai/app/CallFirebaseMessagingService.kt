package com.thookumadurai.app

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import android.util.Log

/**
 * Receives FCM DATA (not notification) messages sent with priority "high".
 * A data-only high-priority message is delivered even if the app process was
 * killed by the OS, which is what lets us show a real incoming-call screen
 * instead of relying on the page being open.
 *
 * Expected payload from the backend (see backend-patch/push_calls.py):
 *   {
 *     "type": "incoming_call",
 *     "callId": "...",
 *     "orderId": "...",
 *     "callerName": "Karthik R.",
 *     "callerRole": "rider" | "customer"
 *   }
 */
class CallFirebaseMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        if (data["type"] != "incoming_call") return

        Log.d("ThookuCall", "Incoming call push received: ${data["callId"]}")

        IncomingCallActivity.launchFullScreen(
            context = applicationContext,
            callId = data["callId"] ?: return,
            orderId = data["orderId"] ?: "",
            callerName = data["callerName"] ?: "Incoming Call",
            callerRole = data["callerRole"] ?: "rider"
        )
    }

    override fun onNewToken(token: String) {
        // Forward the refreshed token up to JS the next time the WebView is
        // active; CallPlugin.getToken() also re-reads this on demand.
        TokenStore.save(applicationContext, token)
    }
}
