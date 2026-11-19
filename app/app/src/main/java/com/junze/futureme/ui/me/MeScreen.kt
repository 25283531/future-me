package com.junze.futureme.ui.me

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.futureme.R
import com.junze.futureme.data.api.ActivityDto
import com.junze.futureme.data.api.CheckinStatusDto
import com.junze.futureme.data.api.MembershipStatusDto
import com.junze.futureme.data.api.MessageDto
import com.junze.futureme.data.api.WishDto
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import com.junze.futureme.ui.home.daysUntil
import com.junze.futureme.ui.theme.AmberDark
import com.junze.futureme.ui.theme.CreamBg
import com.junze.futureme.ui.theme.OrangeLight
import com.junze.futureme.ui.theme.OrangePrimary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MeViewModel(
    private val repository: FutureMeRepository,
    private val settings: SettingsStore
) : ViewModel() {

    val wishes: StateFlow<List<WishDto>> = repository.wishes
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val baseUrl: StateFlow<String> = settings.baseUrl
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    private val _membership = MutableStateFlow<MembershipStatusDto?>(null)
    val membership: StateFlow<MembershipStatusDto?> = _membership

    private val _messages = MutableStateFlow<List<MessageDto>>(emptyList())
    val messages: StateFlow<List<MessageDto>> = _messages

    private val _activities = MutableStateFlow<List<ActivityDto>>(emptyList())
    val activities: StateFlow<List<ActivityDto>> = _activities

    private val _checkinStatus = MutableStateFlow<CheckinStatusDto?>(null)
    val checkinStatus: StateFlow<CheckinStatusDto?> = _checkinStatus

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    init {
        refresh()
    }

    /** Fetch-on-open: messages / activities are pulled when the app opens. */
    fun refresh() {
        viewModelScope.launch {
            repository.refreshWishes()
            repository.getMembershipStatus().onSuccess { _membership.value = it }
            repository.getMessages()
                .onSuccess { _messages.value = it }
                .onFailure { _notice.value = "消息拉取失败，请检查网络" }
            repository.getActivities().onSuccess { _activities.value = it }
            repository.getCheckinStatus().onSuccess { _checkinStatus.value = it }
        }
    }

    /** Changing the server forces a fresh device auth against the new host. */
    fun saveBaseUrl(url: String) {
        viewModelScope.launch {
            val normalized = url.trim().trimEnd('/')
            settings.saveBaseUrl(normalized)
            settings.saveToken(null)
            repository.updateBaseUrl(normalized)
            _notice.value = "服务器地址已保存，正在重新连接"
            refresh()
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MeScreen(viewModel: MeViewModel) {
    val wishes by viewModel.wishes.collectAsState()
    val membership by viewModel.membership.collectAsState()
    val messages by viewModel.messages.collectAsState()
    val activities by viewModel.activities.collectAsState()
    val checkinStatus by viewModel.checkinStatus.collectAsState()
    val baseUrl by viewModel.baseUrl.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    var serverUrlText by remember(baseUrl) { mutableStateOf(baseUrl) }
    var isSavingImage by remember { mutableStateOf(false) }
    val graphicsLayer = rememberGraphicsLayer()

    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    val currentWish = wishes.firstOrNull { it.status != "done" && it.status != "completed" }
        ?: wishes.firstOrNull()

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = { TopAppBar(title = { Text(text = stringResource(R.string.nav_me)) }) }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item { Spacer(modifier = Modifier.height(4.dp)) }

            // ---- Membership ----
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = stringResource(R.string.me_membership),
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = membershipText(membership),
                            style = MaterialTheme.typography.bodyLarge,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            text = stringResource(R.string.me_membership_plan),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }

            // ---- Vision board ----
            item {
                Text(
                    text = stringResource(R.string.vision_board),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            item {
                if (currentWish == null) {
                    Text(
                        text = stringResource(R.string.vision_board_no_wish),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                } else {
                    VisionBoardCard(
                        wish = currentWish,
                        streak = checkinStatus?.streak ?: 0,
                        graphicsLayerModifier = Modifier.drawWithContent {
                            graphicsLayer.record { this@drawWithContent.drawContent() }
                            drawContent()
                        }
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Button(
                        onClick = {
                            isSavingImage = true
                            scope.launch {
                                val bitmap = graphicsLayer.toImageBitmap().asAndroidBitmap()
                                val ok = saveBitmapToGallery(
                                    context = context,
                                    bitmap = bitmap,
                                    displayName = "未来我-愿景板-${System.currentTimeMillis()}.png"
                                )
                                snackbarHostState.showSnackbar(
                                    if (ok) "已保存到相册" else "保存失败，请检查存储权限"
                                )
                                isSavingImage = false
                            }
                        },
                        enabled = !isSavingImage,
                        modifier = Modifier.fillMaxWidth().height(48.dp)
                    ) {
                        if (isSavingImage) {
                            CircularProgressIndicator(
                                modifier = Modifier.padding(end = 8.dp),
                                strokeWidth = 2.dp
                            )
                        }
                        Text(text = stringResource(R.string.vision_board_save))
                    }
                }
            }

            // ---- Server address ----
            item {
                Text(
                    text = stringResource(R.string.server_address),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        OutlinedTextField(
                            value = serverUrlText,
                            onValueChange = { serverUrlText = it },
                            label = { Text(text = stringResource(R.string.server_address_hint)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(
                                onClick = {
                                    serverUrlText = "http://100.72.221.19:8000"
                                    viewModel.saveBaseUrl(serverUrlText)
                                }
                            ) { Text(text = "Tailscale") }
                            OutlinedButton(
                                onClick = {
                                    serverUrlText = "http://10.0.1.1:8000"
                                    viewModel.saveBaseUrl(serverUrlText)
                                }
                            ) { Text(text = "局域网") }
                            Button(
                                onClick = { viewModel.saveBaseUrl(serverUrlText) },
                                modifier = Modifier.weight(1f)
                            ) { Text(text = stringResource(R.string.action_save)) }
                        }
                    }
                }
            }

            // ---- Messages & activities (fetch-on-open) ----
            item {
                Text(
                    text = stringResource(R.string.messages),
                    style = MaterialTheme.typography.titleLarge
                )
            }
            if (messages.isEmpty() && activities.isEmpty()) {
                item {
                    Text(
                        text = stringResource(R.string.messages_empty),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            items(activities, key = { "a-${it.id}" }) { activity ->
                MessageRow(title = activity.title, content = activity.content, tag = "活动")
            }
            items(messages, key = { "m-${it.id}" }) { message ->
                MessageRow(title = message.title, content = message.content, tag = "消息")
            }

            // ---- About ----
            item {
                Divider()
                Text(
                    text = stringResource(R.string.about_title),
                    style = MaterialTheme.typography.titleLarge
                )
                Text(
                    text = stringResource(R.string.about_text),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = stringResource(R.string.version),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))
            }
        }
    }
}

@Composable
private fun membershipText(membership: MembershipStatusDto?): String {
    return when (membership?.status) {
        "trial" -> "试用中 · 还剩 ${membership.trialDaysLeft ?: 0} 天"
        "active" -> "订阅中 · ${membership.expiresAt?.take(10) ?: ""} 到期"
        "expired" -> "试用已过期 · 第一阶段全部免费"
        else -> "免费体验中 · 第一阶段全部免费"
    }
}

@Composable
private fun MessageRow(title: String, content: String, tag: String) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    text = tag,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.primary
                )
                Text(text = title, fontWeight = FontWeight.Medium)
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = content,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/**
 * The shareable vision-board card: current wish + target date + streak,
 * drawn with a sunrise motif in the app palette. It is rendered through
 * [graphicsLayerModifier] so the same pixels can be saved to the gallery.
 */
@Composable
fun VisionBoardCard(
    wish: WishDto,
    streak: Int,
    graphicsLayerModifier: Modifier = Modifier
) {
    val daysLeft = daysUntil(wish.targetDate)
    Box(
        modifier = graphicsLayerModifier
            .fillMaxWidth()
            .background(CreamBg)
            .padding(16.dp)
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.fillMaxWidth()
        ) {
            Canvas(modifier = Modifier.size(56.dp)) {
                drawCircle(
                    color = OrangePrimary,
                    radius = size.minDimension / 2f,
                    center = Offset(size.width / 2f, size.height / 2f)
                )
                drawCircle(
                    color = OrangeLight,
                    radius = size.minDimension / 3f,
                    center = Offset(size.width / 2f, size.height / 2f)
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "未来我",
                style = MaterialTheme.typography.titleLarge,
                color = AmberDark
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = wish.text,
                style = MaterialTheme.typography.headlineMedium,
                textAlign = TextAlign.Center,
                color = MaterialTheme.colorScheme.onBackground
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "目标日 ${wish.targetDate}" +
                    if (daysLeft != null && daysLeft >= 0) " · 还有 $daysLeft 天" else "",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "已坚持 $streak 天",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** Saves a PNG into Pictures/未来我 via MediaStore (no storage permission needed on API 29+). */
suspend fun saveBitmapToGallery(
    context: Context,
    bitmap: Bitmap,
    displayName: String
): Boolean = withContext(Dispatchers.IO) {
    val resolver = context.contentResolver
    val values = ContentValues().apply {
        put(MediaStore.Images.Media.DISPLAY_NAME, displayName)
        put(MediaStore.Images.Media.MIME_TYPE, "image/png")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            put(
                MediaStore.Images.Media.RELATIVE_PATH,
                Environment.DIRECTORY_PICTURES + "/未来我"
            )
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
    }
    val uri = resolver.insert(
        MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values
    ) ?: return@withContext false
    try {
        resolver.openOutputStream(uri)?.use { out ->
            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)) {
                return@withContext false
            }
        } ?: return@withContext false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val done = ContentValues().apply {
                put(MediaStore.Images.Media.IS_PENDING, 0)
            }
            resolver.update(uri, done, null, null)
        }
        true
    } catch (e: Exception) {
        try {
            resolver.delete(uri, null, null)
        } catch (_: Exception) {
            // best effort cleanup
        }
        false
    }
}
