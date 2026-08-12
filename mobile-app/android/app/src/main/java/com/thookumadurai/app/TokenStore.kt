package com.thookumadurai.app

import android.content.Context

object TokenStore {
    private const val PREFS = "thooku_call_prefs"
    private const val KEY_TOKEN = "fcm_token"
    private const val KEY_AUTH = "auth_token"
    private const val KEY_PENDING_CALL_ID = "pending_call_id"
    private const val KEY_PENDING_ORDER_ID = "pending_order_id"
    private const val KEY_PENDING_CALLER_NAME = "pending_caller_name"
    private const val KEY_PENDING_CALLER_ROLE = "pending_caller_role"

    fun save(context: Context, token: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_TOKEN, token).apply()
    }

    fun read(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_TOKEN, null)

    fun saveAuth(context: Context, token: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_AUTH, token).apply()
    }

    fun readAuth(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_AUTH, null)

    /**
     * Persist the "user tapped Answer" payload so it survives the cold-start
     * race: if the WebView/JS listener is not ready yet when the intent
     * arrives, the JS bridge pulls this via CallPlugin.takePendingCall() once
     * the page finishes loading.
     */
    fun savePendingCall(context: Context, callId: String, orderId: String,
                        callerName: String, callerRole: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_PENDING_CALL_ID, callId)
            .putString(KEY_PENDING_ORDER_ID, orderId)
            .putString(KEY_PENDING_CALLER_NAME, callerName)
            .putString(KEY_PENDING_CALLER_ROLE, callerRole)
            .apply()
    }

    fun readPendingCall(context: Context): PendingCall? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val callId = prefs.getString(KEY_PENDING_CALL_ID, null) ?: return null
        return PendingCall(
            callId = callId,
            orderId = prefs.getString(KEY_PENDING_ORDER_ID, "") ?: "",
            callerName = prefs.getString(KEY_PENDING_CALLER_NAME, "") ?: "",
            callerRole = prefs.getString(KEY_PENDING_CALLER_ROLE, "") ?: "",
        )
    }

    fun clearPendingCall(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_PENDING_CALL_ID)
            .remove(KEY_PENDING_ORDER_ID)
            .remove(KEY_PENDING_CALLER_NAME)
            .remove(KEY_PENDING_CALLER_ROLE)
            .apply()
    }
}

data class PendingCall(
    val callId: String,
    val orderId: String,
    val callerName: String,
    val callerRole: String,
)
