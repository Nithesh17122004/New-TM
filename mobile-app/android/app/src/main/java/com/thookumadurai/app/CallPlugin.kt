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
