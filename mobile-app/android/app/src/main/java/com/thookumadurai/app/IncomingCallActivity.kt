package com.thookumadurai.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import java.net.HttpURLConnection
import java.net.URL

const val EXTRA_CALL_ID = "callId"
const val EXTRA_ORDER_ID = "orderId"
const val EXTRA_CALLER_NAME = "callerName"
const val EXTRA_CALLER_ROLE = "callerRole"
const val ACTION_CALL_ANSWERED = "com.thookumadurai.app.CALL_ANSWERED"

private const val CHANNEL_ID = "thooku_incoming_calls"
// Point this at your deployed backend.
private const val API_BASE = "https://thookumadurai.onrender.com"

class IncomingCallActivity : AppCompatActivity() {

    private var ringtone: Ringtone? = null
    private var vibrator: Vibrator? = null

    companion object {
        /**
         * Shows the incoming-call UI even if the screen is locked / app was
         * killed. Called from CallFirebaseMessagingService.onMessageReceived.
         */
        fun launchFullScreen(
            context: Context,
            callId: String,
            orderId: String,
            callerName: String,
            callerRole: String
        ) {
            val fullScreenIntent = Intent(context, IncomingCallActivity::class.java).apply {
                putExtra(EXTRA_CALL_ID, callId)
                putExtra(EXTRA_ORDER_ID, orderId)
                putExtra(EXTRA_CALLER_NAME, callerName)
                putExtra(EXTRA_CALLER_ROLE, callerRole)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
            }
            val pendingIntent = PendingIntent.getActivity(
                context, callId.hashCode(), fullScreenIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val channel = NotificationChannel(
                    CHANNEL_ID, "Incoming Calls", NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = "Rider / customer call notifications"
                    setBypassDnd(true)
                    enableVibration(true)
                }
                nm.createNotificationChannel(channel)
            }

            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.sym_call_incoming)
                .setContentTitle(callerName)
                .setContentText("Incoming call \u2013 Thooku Madurai")
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setFullScreenIntent(pendingIntent, true) // pops the activity even when locked
                .setAutoCancel(true)
                .build()

            nm.notify(callId.hashCode(), notification)

            // Also try to launch directly \u2014 covers the case where the app
            // process is already alive in the foreground/background.
            context.startActivity(fullScreenIntent)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Show over the lock screen and turn the screen on, like a real call.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                android.view.WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                android.view.WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
            )
        }

        setContentView(R.layout.activity_incoming_call)

        val callId = intent.getStringExtra(EXTRA_CALL_ID) ?: ""
        val orderId = intent.getStringExtra(EXTRA_ORDER_ID) ?: ""
        val callerName = intent.getStringExtra(EXTRA_CALLER_NAME) ?: "Incoming Call"
        val callerRole = intent.getStringExtra(EXTRA_CALLER_ROLE) ?: ""

        findViewById<TextView>(R.id.callerName).text = callerName

        startRinging()

        findViewById<Button>(R.id.answerBtn).setOnClickListener {
            stopRinging()
            // Hand off to MainActivity (the Capacitor WebView). CallPlugin
            // picks this intent up in onNewIntent/onResume and fires a JS
            // event that your existing tracking.html / rider-dashboard.html
            // WebRTC accept flow (acceptCall()) already knows how to handle
            // once it fetches the stored SDP offer.
            val mainIntent = Intent(this, MainActivity::class.java).apply {
                action = ACTION_CALL_ANSWERED
                putExtra(EXTRA_CALL_ID, callId)
                putExtra(EXTRA_ORDER_ID, orderId)
                putExtra(EXTRA_CALLER_NAME, callerName)
                putExtra(EXTRA_CALLER_ROLE, callerRole)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            startActivity(mainIntent)
            finish()
        }

        findViewById<Button>(R.id.declineBtn).setOnClickListener {
            stopRinging()
            postDeclineAsync(callId, orderId)
            finish()
        }
    }

    private fun startRinging() {
        try {
            val uri = RingtoneManager.getActualDefaultRingtoneUri(this, RingtoneManager.TYPE_RINGTONE)
            ringtone = RingtoneManager.getRingtone(this, uri)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                ringtone?.audioAttributes = AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            }
            ringtone?.play()

            vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            val pattern = longArrayOf(0, 500, 300, 500, 300)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(VibrationEffect.createWaveform(pattern, 0))
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(pattern, 0)
            }
        } catch (e: Exception) {
            // Non-fatal \u2014 UI still works without sound/vibration.
        }
    }

    private fun stopRinging() {
        ringtone?.stop()
        vibrator?.cancel()
    }

    override fun onDestroy() {
        stopRinging()
        super.onDestroy()
    }

    /** Fire-and-forget decline call, mirrors POST /api/v1/push/call-declined */
    private fun postDeclineAsync(callId: String, orderId: String) {
        Thread {
            try {
                val url = URL("$API_BASE/api/v1/push/call-declined")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                val body = """{"callId":"$callId","orderId":"$orderId"}"""
                conn.outputStream.write(body.toByteArray())
                conn.responseCode // triggers the request
                conn.disconnect()
            } catch (e: Exception) {
                // Best-effort only.
            }
        }.start()
    }
}
