package com.thookumadurai.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
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
 * or for delivery offers:
 *   {
 *     "type": "delivery_offer",
 *     "orderId": "...",
 *     "restaurantName": "...",
 *     "total": "123",
 *     "distanceKm": "2.4",
 *     "farOffer": "0" | "1"
 *   }
 */
class CallFirebaseMessagingService : FirebaseMessagingService() {

    private val offerChannelId = "thooku_delivery_offers"

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        when (data["type"]) {
            "incoming_call" -> {
                Log.d("ThookuCall", "Incoming call push received: ${data["callId"]}")

                IncomingCallActivity.launchFullScreen(
                    context = applicationContext,
                    callId = data["callId"] ?: return,
                    orderId = data["orderId"] ?: "",
                    callerName = data["callerName"] ?: "Incoming Call",
                    callerRole = data["callerRole"] ?: "rider"
                )
            }
            "delivery_offer" -> {
                Log.d("ThookuCall", "Delivery offer push received: ${data["orderId"]}")
                showDeliveryOfferNotification(data)
            }
        }
    }

    private fun showDeliveryOfferNotification(data: Map<String, String>) {
        val orderId = data["orderId"] ?: return
        val restaurantName = data["restaurantName"] ?: "Restaurant"
        val distance = data["distanceKm"].orEmpty()
        val far = data["farOffer"] == "1"

        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                offerChannelId, "Delivery Offers", NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "New delivery order offers (accept or reject)"
                enableVibration(true)
            }
            nm.createNotificationChannel(channel)
        }

        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, orderId.hashCode(), openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val body = buildString {
            append("Pick up from $restaurantName")
            if (distance.isNotBlank() && distance != "0") append(" · ${distance} km away")
            if (far) append(" · Far from you (nearest available rider)")
            append(". Open the app to accept or reject.")
        }

        val notification = NotificationCompat.Builder(this, offerChannelId)
            .setSmallIcon(android.R.drawable.ic_menu_agenda)
            .setContentTitle("New delivery offer 🛵")
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setVibrate(longArrayOf(0, 300, 150, 300))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        nm.notify(orderId.hashCode(), notification)
    }

    override fun onNewToken(token: String) {
        // Forward the refreshed token up to JS the next time the WebView is
        // active; CallPlugin.getToken() also re-reads this on demand.
        TokenStore.save(applicationContext, token)
    }
}
