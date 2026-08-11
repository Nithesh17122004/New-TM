package com.thookumadurai.app

import android.content.Context

object TokenStore {
    private const val PREFS = "thooku_call_prefs"
    private const val KEY_TOKEN = "fcm_token"
    private const val KEY_AUTH = "auth_token"

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
}
