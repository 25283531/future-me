package com.junze.futureme.ui.home

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.futureme.R
import com.junze.futureme.data.api.LetterDto
import com.junze.futureme.data.api.WishDto
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import com.junze.futureme.ui.components.EmptyBox
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit

/** The six wish categories, verbatim from PLAN.md (same values sent to the backend). */
val WISH_CATEGORIES =
    listOf("事业升职/换工作", "财富收入", "脱单恋爱", "健康身材", "学习考证", "家庭亲子")
val WISH_DURATIONS = listOf(30, 90, 365)

class HomeViewModel(
    private val repository: FutureMeRepository,
    private val settings: SettingsStore
) : ViewModel() {

    val wishes: StateFlow<List<WishDto>> = repository.wishes
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _isRefreshing = kotlinx.coroutines.flow.MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing

    private val _errorMessage = kotlinx.coroutines.flow.MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage

    private val _notice = kotlinx.coroutines.flow.MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    private val _isSubmitting = kotlinx.coroutines.flow.MutableStateFlow(false)
    val isSubmitting: StateFlow<Boolean> = _isSubmitting

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            repository.refreshWishes().onFailure {
                _errorMessage.value = "网络不可用，显示的是上次保存的内容"
            }
            _isRefreshing.value = false
        }
    }

    fun createWish(text: String, category: String, days: Int) {
        viewModelScope.launch {
            _isSubmitting.value = true
            repository.createWish(text.trim(), category, days)
                .onSuccess { _notice.value = "愿望已许下，未来在等你" }
                .onFailure { _errorMessage.value = "提交失败，请检查网络后重试" }
            _isSubmitting.value = false
        }
    }

    fun lettersForWish(wishId: String) = repository.lettersForWish(wishId)

    suspend fun loadWish(wishId: String): WishDto? = repository.getWish(wishId)

    /** Generates a letter for a wish using the voice saved in 我的 / 未来信. */
    suspend fun generateLetter(wishId: String): Result<LetterDto> {
        val voiceId = settings.selectedVoiceId.first()
        return repository.generateLetter(wishId, voiceId)
    }

    fun clearNotice() {
        _notice.value = null
        _errorMessage.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onWishClick: (String) -> Unit
) {
    val wishes by viewModel.wishes.collectAsState()
    val isRefreshing by viewModel.isRefreshing.collectAsState()
    val errorMessage by viewModel.errorMessage.collectAsState()
    val notice by viewModel.notice.collectAsState()
    val isSubmitting by viewModel.isSubmitting.collectAsState()

    var wishText by remember { mutableStateOf("") }
    var category by remember { mutableStateOf(WISH_CATEGORIES[0]) }
    var days by remember { mutableIntStateOf(90) }

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice, errorMessage) {
        val message = notice ?: errorMessage ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearNotice()
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = { viewModel.refresh() }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "刷新")
                    }
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
            item {
                Text(
                    text = "写下愿望，\n未来的自己会回信。",
                    style = MaterialTheme.typography.headlineMedium,
                    modifier = Modifier.padding(top = 8.dp, bottom = 4.dp)
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
                            value = wishText,
                            onValueChange = { if (it.length <= 100) wishText = it },
                            label = { Text(text = stringResource(R.string.wish_hint)) },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 3,
                            maxLines = 5
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = "分类",
                            style = MaterialTheme.typography.titleMedium
                        )
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.padding(top = 8.dp)
                        ) {
                            WISH_CATEGORIES.forEach { item ->
                                FilterChip(
                                    selected = category == item,
                                    onClick = { category = item },
                                    label = { Text(item) }
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "多久实现",
                            style = MaterialTheme.typography.titleMedium
                        )
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.padding(top = 8.dp)
                        ) {
                            WISH_DURATIONS.forEach { d ->
                                FilterChip(
                                    selected = days == d,
                                    onClick = { days = d },
                                    label = { Text("$d 天") }
                                )
                            }
                        }
                        Spacer(modifier = Modifier.height(16.dp))
                        Button(
                            onClick = {
                                if (wishText.isBlank()) return@Button
                                viewModel.createWish(wishText, category, days)
                                wishText = ""
                            },
                            enabled = wishText.isNotBlank() && !isSubmitting,
                            modifier = Modifier.fillMaxWidth().height(48.dp)
                        ) {
                            if (isSubmitting) {
                                CircularProgressIndicator(
                                    modifier = Modifier.padding(end = 8.dp),
                                    strokeWidth = 2.dp
                                )
                            }
                            Text(text = stringResource(R.string.wish_submit))
                        }
                    }
                }
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = stringResource(R.string.my_wishes),
                        style = MaterialTheme.typography.titleLarge
                    )
                    if (isRefreshing) CircularProgressIndicator()
                }
            }
            if (wishes.isEmpty() && !isRefreshing) {
                item {
                    EmptyBox(
                        message = stringResource(R.string.wish_empty),
                        modifier = Modifier.height(120.dp)
                    )
                }
            }
            items(wishes, key = { it.id }) { wish ->
                WishCard(wish = wish, onClick = { onWishClick(wish.id) })
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }
}

@Composable
fun WishCard(wish: WishDto, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = wish.text,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(
                    onClick = {},
                    label = { Text(wish.category) }
                )
                AssistChip(
                    onClick = {},
                    label = { Text("${stringResource(R.string.wish_target_date)} ${wish.targetDate}") }
                )
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = wishStatusText(wish),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** "进行中 · 还有 42 天" / "已完成" — computed from target_date. */
@Composable
fun wishStatusText(wish: WishDto): String {
    val status = when (wish.status) {
        "done", "completed", "finished" -> stringResource(R.string.wish_status_done)
        else -> stringResource(R.string.wish_status_active)
    }
    val daysLeft = daysUntil(wish.targetDate)
    val countdown = when {
        daysLeft == null -> ""
        daysLeft < 0 -> " · ${stringResource(R.string.wish_days_overdue)}"
        else -> " · ${stringResource(R.string.wish_days_left, daysLeft)}"
    }
    return status + countdown
}

fun daysUntil(targetDate: String): Long? {
    return try {
        val target = LocalDate.parse(targetDate.take(10))
        ChronoUnit.DAYS.between(LocalDate.now(), target)
    } catch (e: DateTimeParseException) {
        null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WishDetailScreen(
    wishId: String,
    viewModel: HomeViewModel,
    onLetterClick: (String) -> Unit,
    onBack: () -> Unit
) {
    var wish by remember { mutableStateOf<WishDto?>(null) }
    val letters by viewModel.lettersForWish(wishId).collectAsState(initial = emptyList())
    var isGenerating by remember { mutableStateOf(false) }
    var generateError by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(wishId) {
        wish = viewModel.loadWish(wishId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "愿望详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            val current = wish
            if (current == null) {
                Text(text = stringResource(R.string.loading))
                return@Column
            }
            WishCard(wish = current, onClick = {})
            Button(
                onClick = {
                    isGenerating = true
                    generateError = null
                    scope.launch {
                        viewModel.generateLetter(wishId)
                            .onSuccess { letter -> onLetterClick(letter.id) }
                            .onFailure {
                                generateError = "生成失败，请检查网络后重试"
                            }
                        isGenerating = false
                    }
                },
                enabled = !isGenerating,
                modifier = Modifier.fillMaxWidth().height(48.dp)
            ) {
                if (isGenerating) {
                    CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp), strokeWidth = 2.dp)
                    Text(text = stringResource(R.string.generating_letter))
                } else {
                    Text(text = stringResource(R.string.generate_letter))
                }
            }
            generateError?.let { Text(text = it, color = MaterialTheme.colorScheme.error) }
            Text(
                text = "收到的未来信（${letters.size}）",
                style = MaterialTheme.typography.titleLarge
            )
            letters.forEach { letter ->
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onLetterClick(letter.id) },
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Text(
                        text = letter.text.take(120) + if (letter.text.length > 120) "…" else "",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(16.dp)
                    )
                }
            }
        }
    }
}
