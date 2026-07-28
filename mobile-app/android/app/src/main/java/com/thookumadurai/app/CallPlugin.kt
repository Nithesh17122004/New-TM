package com.thookumadurai.app

import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.google.firebase.messaging.FirebaseMessaging

/**
 * JS-facing bridge. In your frontend:
 *
 *   import { registerPlugin } from '@capacitor/core';
 *   const ThookuCalls = registerPlugin('CallPlugin');
 *
 *   const { token } = await ThookuCalls.getFcmToken();
 *   // POST token to /api/v1/push/register-device (see backend-patch/)
 *
 *   ThookuCalls.addListener('incomingCallAnswered', (data) => {
 *     // data: { callId, orderId, callerName, callerRole }
 *     // Feed straight into your existing acceptCall() flow after fetching
 *     // the stored SDP offer from /api/v1/push/pending-offer/<callId>.
 *   });
 */
@CapacitorPlugin(name = "CallPlugin")
class CallPlugin : Plugin() {

    @PluginMethod
    fun getFcmToken(call: PluginCall) {
        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
            if (!task.isSuccessful) {
                call.reject("Could not get FCM token", task.exception)
                return@addOnCompleteListener
            }
            val token = task.result
            TokenStore.save(context, token)
            val ret = JSObject()
            ret.put("token", token)
            call.resolve(ret)
        }
    }

    /** Called by MainActivity when the app was opened from the native Answer button. */
    fun notifyIncomingCallAnswered(callId: String, orderId: String, callerName: String, callerRole: String) {
        val data = JSObject()
        data.put("callId", callId)
        data.put("orderId", orderId)
        data.put("callerName", callerName)
        data.put("callerRole", callerRole)
        notifyListeners("incomingCallAnswered", data)
    }
}
