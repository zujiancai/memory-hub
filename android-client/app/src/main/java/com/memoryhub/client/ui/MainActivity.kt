package com.memoryhub.client.ui

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.memoryhub.client.MemoryHubApp
import com.memoryhub.client.api.ApiClient
import com.memoryhub.client.api.LoginRequest
import com.memoryhub.client.api.TokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val tokenStore = TokenStore(this)
        val settingsStore = SettingsStore(this)
        setContent {
            MaterialTheme {
                Scaffold(topBar = { TopAppBar(title = { Text("Memory Hub") }) }) { padding ->
                    Root(
                        tokenStore = tokenStore,
                        settingsStore = settingsStore,
                        contentPadding = padding,
                    )
                }
            }
        }
    }
}

@Composable
private fun Root(
    tokenStore: TokenStore,
    settingsStore: SettingsStore,
    contentPadding: PaddingValues,
) {
    var loggedIn by remember { mutableStateOf(tokenStore.accessToken != null) }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (!loggedIn) {
            var email by remember { mutableStateOf("") }
            var password by remember { mutableStateOf("") }
            var error by remember { mutableStateOf<String?>(null) }
            var baseUrl by remember { mutableStateOf(settingsStore.load().baseUrl) }

            Text("Sign in", style = MaterialTheme.typography.headlineSmall)
            OutlinedTextField(baseUrl, { baseUrl = it }, label = { Text("API base URL") })
            OutlinedTextField(email, { email = it }, label = { Text("Email") })
            OutlinedTextField(password, { password = it }, label = { Text("Password") })
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Button(onClick = {
                scope.launch {
                    settingsStore.update { it.copy(baseUrl = baseUrl) }
                    val api = ApiClient.buildBare(baseUrl)
                    val resp = withContext(Dispatchers.IO) {
                        runCatching { api.login(LoginRequest(email, password)) }
                    }.getOrNull()
                    val body = resp?.body()
                    if (resp?.isSuccessful == true && body != null) {
                        tokenStore.accessToken = body.accessToken
                        tokenStore.refreshToken = body.refreshToken
                        loggedIn = true
                    } else {
                        error = "Login failed (${resp?.code() ?: "network"})"
                    }
                }
            }) { Text("Sign in") }
        } else {
            LoggedInScreen(
                tokenStore = tokenStore,
                settingsStore = settingsStore,
                onSignOut = { tokenStore.clear(); loggedIn = false },
            )
        }
    }
}

@Composable
private fun LoggedInScreen(
    tokenStore: TokenStore,
    settingsStore: SettingsStore,
    onSignOut: () -> Unit,
) {
    var settings by remember { mutableStateOf(settingsStore.load()) }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val activity = ctx as? Activity
    val db = (ctx.applicationContext as MemoryHubApp).database
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    var pending by remember { mutableStateOf<List<String>>(emptyList()) }
    LaunchedEffect(Unit) {
        pending = db.uploadStateDao().all().map {
            "${it.state} — ${it.uri.take(80)}"
        }
    }

    val folderPicker = androidx.activity.compose.rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocumentTree()
    ) { uri: Uri? ->
        if (uri != null) {
            settingsStore.persistUriPermission(ctx, uri)
            settingsStore.addWatchFolder(uri.toString())
            settings = settingsStore.load()
        }
    }

    Text("Signed in", style = MaterialTheme.typography.headlineSmall)
    Text("Watch folders: ${settings.watchFolders.size}")

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(onClick = { folderPicker.launch(null) }) { Text("Add folder") }
        Button(onClick = onSignOut) { Text("Sign out") }
    }

    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Wi-Fi only")
        Switch(checked = settings.wifiOnly, onCheckedChange = {
            settingsStore.update { s -> s.copy(wifiOnly = it) }
            settings = settingsStore.load()
        })
        Text("Charging only")
        Switch(checked = settings.requiresCharging, onCheckedChange = {
            settingsStore.update { s -> s.copy(requiresCharging = it) }
            settings = settingsStore.load()
        })
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Delete local after upload")
        Switch(checked = settings.deleteLocalOnSuccess, onCheckedChange = {
            settingsStore.update { s -> s.copy(deleteLocalOnSuccess = it) }
            settings = settingsStore.load()
        })
    }

    Text("Upload queue", style = MaterialTheme.typography.titleMedium)
    LazyColumn(modifier = Modifier.fillMaxSize()) {
        items(pending) { line -> Text(line) }
    }
}
