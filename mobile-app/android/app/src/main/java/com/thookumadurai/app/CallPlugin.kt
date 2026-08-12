package com.thookumadurai.app

import android.content.Context
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.google.firebase.FirebaseApp
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

    /**
     * Currently playing native ringtone — allows the WebView to use the
     * phone's actual default ringtone (not the Web-Audio chime) for an
     * in-foreground incoming call.
     */
    private var activeRingtone: Ringtone? = null

    @PluginMethod
    fun getFcmToken(call: PluginCall) {
        // No google-services.json / Firebase project configured yet: fail
        // cleanly instead of letting FirebaseMessaging.getInstance() throw
        // IllegalStateException and crash the whole app. The JS bridge treats
        // a rejected call as "push not available" and keeps working.
        if (FirebaseApp.getApps(context).isEmpty()) {
            call.reject("Firebase is not initialized. Add google-services.json to enable push notifications.")
            return
        }
        try {
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
        } catch (e: Exception) {
            call.reject("FCM token error: ${e.message}")
        }
    }

    /** Plays the device's DEFAULT ringtone (what the user chose for calls). */
    @PluginMethod
    fun playRingtone(call: PluginCall) {
        runCatching { activeRingtone?.stop() }
        try {
            val uri = RingtoneManager.getActualDefaultRingtoneUri(activity, RingtoneManager.TYPE_RINGTONE)
            val ringtone = RingtoneManager.getRingtone(context, uri)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.LOLLIPOP) {
                ringtone.audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            }
            ringtone.isLooping = true
            ringtone.play()
            activeRingtone = ringtone
            call.resolve(JSObject().put("playing", true))
        } catch (e: Exception) {
            call.reject("Ringtone error: ${e.message}")
        }
    }

    @PluginMethod
    fun stopRingtone(call: PluginCall) {
        runCatching { activeRingtone?.stop() }
        activeRingtone = null
        call.resolve()
    }

    /**
     * Stores the user's app JWT so the native incoming-call screen can send
     * an authenticated POST /api/v1/push/call-declined when the user taps
     * Decline (that endpoint now rejects unauthenticated requests).
     * The WebView calls this after login / on page load with the token.
     */
    @PluginMethod
    fun setAuthToken(call: PluginCall) {
        val token = call.getString("token") ?: ""
        if (token.isBlank()) {
            call.resolve()
            return
        }
        TokenStore.saveAuth(context, token)
        call.resolve()
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

    /**
     * Cold-start safety net: the native "Answer" tap is persisted to
     * SharedPreferences by IncomingCallActivity before the app launches. On a
     * cold start the WebView's JS listener may not be ready when the
     * 'incomingCallAnswered' event fires, so the page pulls the pending
     * answer here once it is loaded. Returns null when nothing is pending.
     */
    @PluginMethod
    fun takePendingCall(call: PluginCall) {
        val pending = TokenStore.readPendingCall(context)
        if (pending == null) {
            call.resolve()
            return
        }
        TokenStore.clearPendingCall(context)
        val ret = JSObject()
        ret.put("callId", pending.callId)
        ret.put("orderId", pending.orderId)
        ret.put("callerName", pending.callerName)
        ret.put("callerRole", pending.callerRole)
        call.resolve(ret)
    }
}
