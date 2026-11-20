package com.junze.futureme.ui.account

import android.webkit.WebView
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.futureme.data.api.MeResponse
import com.junze.futureme.data.repository.FutureMeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import retrofit2.HttpException

/** Reads the backend {"detail": "..."} message out of an HTTP error. */
private fun Throwable.userMessage(): String {
    if (this is HttpException) {
        try {
            val body = response()?.errorBody()?.string()
            if (!body.isNullOrBlank()) {
                val detail = JSONObject(body).optString("detail", "")
                if (detail.isNotBlank()) return detail
            }
        } catch (_: Exception) {
            // fall through to the generic message
        }
        return when (code()) {
            429 -> "操作太频繁，请稍后再试"
            401 -> "登录已过期，请重新登录"
            else -> "请求失败（${code()}），请稍后再试"
        }
    }
    return message ?: "网络异常，请检查网络后重试"
}

enum class AuthMode { LOGIN, REGISTER, FORGOT }

class AccountViewModel(
    private val repository: FutureMeRepository
) : ViewModel() {

    private val _me = MutableStateFlow<MeResponse?>(null)
    val me: StateFlow<MeResponse?> = _me

    private val _mode = MutableStateFlow(AuthMode.LOGIN)
    val mode: StateFlow<AuthMode> = _mode

    private val _captchaSvg = MutableStateFlow<String?>(null)
    val captchaSvg: StateFlow<String?> = _captchaSvg

    private val _captchaChallengeId = MutableStateFlow<String?>(null)

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    init {
        refreshMe()
    }

    fun refreshMe() {
        viewModelScope.launch {
            repository.getMe().onSuccess { _me.value = it }
        }
    }

    fun setMode(mode: AuthMode) {
        _mode.value = mode
        _notice.value = null
        if (mode == AuthMode.REGISTER) loadCaptcha()
    }

    fun loadCaptcha() {
        viewModelScope.launch {
            repository.getCaptcha()
                .onSuccess {
                    _captchaChallengeId.value = it.challengeId
                    _captchaSvg.value = it.svg
                }
                .onFailure { _notice.value = "验证码加载失败，请检查网络" }
        }
    }

    fun login(email: String, password: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.login(email.trim(), password)
                .onSuccess {
                    _notice.value = "登录成功"
                    refreshMe()
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun register(email: String, password: String, captchaAnswer: String) {
        val challengeId = _captchaChallengeId.value
        if (challengeId.isNullOrBlank()) {
            _notice.value = "请先加载验证码"
            return
        }
        viewModelScope.launch {
            _busy.value = true
            repository.register(email.trim(), password, challengeId, captchaAnswer.trim())
                .onSuccess {
                    _notice.value = if (it.emailSent == true) {
                        "注册成功，验证邮件已发送，请查收"
                    } else {
                        "注册成功（验证邮件暂未发出，可先直接使用，验证请稍后再试）"
                    }
                    refreshMe()
                }
                .onFailure {
                    _notice.value = it.userMessage()
                    loadCaptcha() // a failed attempt consumes the challenge
                }
            _busy.value = false
        }
    }

    fun verifyEmail(code: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.verifyEmail(code.trim())
                .onSuccess {
                    _notice.value = "邮箱验证成功"
                    refreshMe()
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun resendVerification() {
        viewModelScope.launch {
            _busy.value = true
            repository.resendVerification()
                .onSuccess {
                    _notice.value = when {
                        it.alreadyVerified == true -> "邮箱已验证"
                        it.emailSent == true -> "验证邮件已发送，请查收"
                        else -> "验证邮件暂未发出（邮件服务未配置），可先直接使用"
                    }
                    refreshMe()
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun forgotPassword(email: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.forgotPassword(email.trim())
                .onSuccess { _notice.value = it.message ?: "如果该邮箱已注册且已验证，重置密码的邮件已发送" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun resetPassword(email: String, code: String, newPassword: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.resetPassword(email.trim(), code.trim(), newPassword)
                .onSuccess {
                    _notice.value = "密码已重置，请用新密码登录"
                    _mode.value = AuthMode.LOGIN
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun changePassword(current: String, new: String) {
        viewModelScope.launch {
            _busy.value = true
            repository.changePassword(current, new)
                .onSuccess { _notice.value = "密码已修改" }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun logout() {
        viewModelScope.launch {
            _busy.value = true
            repository.logout()
                .onSuccess {
                    _me.value = null
                    _notice.value = "已退出登录"
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun deleteAccount(password: String, onDone: () -> Unit) {
        viewModelScope.launch {
            _busy.value = true
            repository.deleteAccount(password)
                .onSuccess {
                    _me.value = null
                    _notice.value = "账号已注销，服务端数据已删除"
                    onDone()
                }
                .onFailure { _notice.value = it.userMessage() }
            _busy.value = false
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

/** Renders the SVG captcha (no extra dependency — plain WebView). */
@Composable
private fun CaptchaImage(svg: String, modifier: Modifier = Modifier) {
    AndroidView(
        modifier = modifier,
        factory = { context ->
            WebView(context).apply {
                settings.javaScriptEnabled = false
                setBackgroundColor(android.graphics.Color.TRANSPARENT)
            }
        },
        update = { webView ->
            webView.loadDataWithBaseURL(null, svg, "image/svg+xml", "utf-8", null)
        }
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AccountScreen(
    viewModel: AccountViewModel,
    onPrivacyClick: () -> Unit,
    onBack: () -> Unit
) {
    val me by viewModel.me.collectAsState()
    val mode by viewModel.mode.collectAsState()
    val captchaSvg by viewModel.captchaSvg.collectAsState()
    val busy by viewModel.busy.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var captchaAnswer by remember { mutableStateOf("") }
    var privacyChecked by remember { mutableStateOf(false) }
    var code by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }
    var currentPassword by remember { mutableStateOf("") }
    var showDeleteDialog by remember { mutableStateOf(false) }
    var deletePassword by remember { mutableStateOf("") }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(text = "账号") },
                navigationIcon = {
                    TextButton(onClick = onBack) { Text(text = "返回") }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { Spacer(modifier = Modifier.height(4.dp)) }

            val account = me?.account
            if (account == null) {
                // ---- Logged out: login / register / forgot ----
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(
                            onClick = { viewModel.setMode(AuthMode.LOGIN) },
                            enabled = mode != AuthMode.LOGIN
                        ) { Text(text = "登录") }
                        OutlinedButton(
                            onClick = { viewModel.setMode(AuthMode.REGISTER) },
                            enabled = mode != AuthMode.REGISTER
                        ) { Text(text = "注册") }
                        TextButton(onClick = { viewModel.setMode(AuthMode.FORGOT) }) {
                            Text(text = "忘记密码")
                        }
                    }
                }
                item {
                    OutlinedTextField(
                        value = email,
                        onValueChange = { email = it },
                        label = { Text(text = "邮箱") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true
                    )
                }
                when (mode) {
                    AuthMode.LOGIN -> {
                        item {
                            OutlinedTextField(
                                value = password,
                                onValueChange = { password = it },
                                label = { Text(text = "密码") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.login(email, password) },
                                enabled = !busy && email.isNotBlank() && password.isNotBlank(),
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "登录") }
                        }
                        item {
                            Text(
                                text = "未验证邮箱也可以正常使用；修改密码和找回密码需要先验证邮箱。",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                    AuthMode.REGISTER -> {
                        item {
                            OutlinedTextField(
                                value = password,
                                onValueChange = { password = it },
                                label = { Text(text = "密码（至少 8 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                if (captchaSvg != null) {
                                    CaptchaImage(
                                        svg = captchaSvg!!,
                                        modifier = Modifier
                                            .fillMaxWidth(0.6f)
                                            .height(60.dp)
                                    )
                                } else {
                                    CircularProgressIndicator()
                                }
                                OutlinedButton(onClick = { viewModel.loadCaptcha() }) {
                                    Text(text = "换一张")
                                }
                            }
                        }
                        item {
                            OutlinedTextField(
                                value = captchaAnswer,
                                onValueChange = { captchaAnswer = it },
                                label = { Text(text = "图中验证码（4 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(
                                    checked = privacyChecked,
                                    onCheckedChange = { privacyChecked = it }
                                )
                                Text(text = "我已阅读并同意")
                                Text(
                                    text = "《隐私协议》",
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.clickable { onPrivacyClick() }
                                )
                            }
                        }
                        item {
                            Button(
                                onClick = { viewModel.register(email, password, captchaAnswer) },
                                enabled = !busy && email.isNotBlank() && password.length >= 8 &&
                                    captchaAnswer.isNotBlank() && privacyChecked,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "注册") }
                        }
                    }
                    AuthMode.FORGOT -> {
                        item {
                            Text(
                                text = "输入注册邮箱，我们会发一封带验证码的邮件（仅已验证的邮箱能收到）",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.forgotPassword(email) },
                                enabled = !busy && email.isNotBlank(),
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "发送验证码") }
                        }
                        item {
                            OutlinedTextField(
                                value = code,
                                onValueChange = { code = it },
                                label = { Text(text = "邮箱验证码（6 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true
                            )
                        }
                        item {
                            OutlinedTextField(
                                value = newPassword,
                                onValueChange = { newPassword = it },
                                label = { Text(text = "新密码（至少 8 位）") },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation()
                            )
                        }
                        item {
                            Button(
                                onClick = { viewModel.resetPassword(email, code, newPassword) },
                                enabled = !busy && code.length == 6 && newPassword.length >= 8,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) { Text(text = "重置密码") }
                        }
                    }
                }
            } else {
                // ---- Logged in ----
                item {
                    Text(
                        text = account.email,
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = if (account.emailVerified) "邮箱已验证" else "邮箱未验证（可正常使用；改密码、找回密码需先验证）",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (!account.emailVerified) {
                    item {
                        OutlinedTextField(
                            value = code,
                            onValueChange = { code = it },
                            label = { Text(text = "邮箱验证码（6 位）") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(
                                onClick = { viewModel.verifyEmail(code) },
                                enabled = !busy && code.length == 6,
                                modifier = Modifier.weight(1f).height(48.dp)
                            ) { Text(text = "验证邮箱") }
                            OutlinedButton(
                                onClick = { viewModel.resendVerification() },
                                enabled = !busy,
                                modifier = Modifier.weight(1f).height(48.dp)
                            ) { Text(text = "重新发送") }
                        }
                    }
                }
                item {
                    Text(text = "修改密码", style = MaterialTheme.typography.titleMedium)
                }
                item {
                    OutlinedTextField(
                        value = currentPassword,
                        onValueChange = { currentPassword = it },
                        label = { Text(text = "当前密码") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation()
                    )
                }
                item {
                    OutlinedTextField(
                        value = newPassword,
                        onValueChange = { newPassword = it },
                        label = { Text(text = "新密码（至少 8 位）") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation()
                    )
                }
                item {
                    Button(
                        onClick = { viewModel.changePassword(currentPassword, newPassword) },
                        enabled = !busy && currentPassword.isNotBlank() && newPassword.length >= 8,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) { Text(text = "修改密码") }
                }
                item {
                    OutlinedButton(
                        onClick = { viewModel.logout() },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) { Text(text = "退出登录") }
                }
                item {
                    TextButton(onClick = { showDeleteDialog = true }) {
                        Text(text = "注销账号", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text(text = "注销账号") },
            text = {
                Column {
                    Text(text = "注销会删除该账号，以及关联设备在服务端保存的愿望、信件、打卡、记忆等数据，且无法恢复。确定吗？")
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedTextField(
                        value = deletePassword,
                        onValueChange = { deletePassword = it },
                        label = { Text(text = "输入密码确认") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation()
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showDeleteDialog = false
                        viewModel.deleteAccount(deletePassword) {}
                        deletePassword = ""
                    },
                    enabled = deletePassword.isNotBlank()
                ) { Text(text = "确认注销", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) { Text(text = "取消") }
            }
        )
    }
}
