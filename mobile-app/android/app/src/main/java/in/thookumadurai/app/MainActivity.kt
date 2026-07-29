package in.thookumadurai.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.getcapacitor.BridgeActivity

class MainActivity : BridgeActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        registerPlugin(CallPlugin::class.java)
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        handleAnsweredCallIntent(intent)
    }

    /**
     * On Android 13+ (API 33+), declaring POST_NOTIFICATIONS in the manifest
     * is NOT enough — the user must grant it at runtime, or notifications
     * (including the full-screen incoming-call one) never show, silently.
     * Without this, the whole feature looks "broken" with no error anywhere.
     */
    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            ActivityCompat.requestPermissions(
                this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1001
            )
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleAnsweredCallIntent(intent)
    }

    private fun handleAnsweredCallIntent(intent: Intent?) {
        if (intent?.action != ACTION_CALL_ANSWERED) return
        val callId = intent.getStringExtra(EXTRA_CALL_ID) ?: return
        val orderId = intent.getStringExtra(EXTRA_ORDER_ID) ?: ""
        val callerName = intent.getStringExtra(EXTRA_CALLER_NAME) ?: ""
        val callerRole = intent.getStringExtra(EXTRA_CALLER_ROLE) ?: ""

        // Give the WebView/plugin bridge a moment to finish initializing on
        // cold start before dispatching the JS event.
        bridge?.webView?.post {
            val plugin = bridge.getPlugin("CallPlugin")?.instance as? CallPlugin
            plugin?.notifyIncomingCallAnswered(callId, orderId, callerName, callerRole)
        }
    }
}
