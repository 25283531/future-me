package com.junze.futureme.ui.letters

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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.futureme.R
import com.junze.futureme.data.api.LetterDto
import com.junze.futureme.data.api.VoiceDto
import com.junze.futureme.data.api.WishDto
import com.junze.futureme.data.audio.AudioPlayer
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import com.junze.futureme.ui.components.EmptyBox
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class LettersViewModel(
    private val repository: FutureMeRepository,
    private val settings: SettingsStore
) : ViewModel() {

    val letters: StateFlow<List<LetterDto>> = repository.letters
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val wishes: StateFlow<List<WishDto>> = repository.wishes
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val selectedVoiceId: StateFlow<String?> = settings.selectedVoiceId
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val _voices = MutableStateFlow<List<VoiceDto>>(emptyList())
    val voices: StateFlow<List<VoiceDto>> = _voices

    private val _isLoading = MutableStateFlow(false)
    val isLoading: StateFlow<Boolean> = _isLoading

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    private val _isGenerating = MutableStateFlow(false)
    val isGenerating: StateFlow<Boolean> = _isGenerating

    init {
        refresh()
        loadVoices()
    }

    fun refresh() {
        viewModelScope.launch {
            _isLoading.value = true
            repository.refreshLetters().onFailure {
                _notice.value = "网络不可用，显示的是上次保存的内容"
            }
            repository.refreshWishes()
            _isLoading.value = false
        }
    }

    fun loadVoices() {
        viewModelScope.launch {
            repository.getVoices()
                .onSuccess { _voices.value = it }
                .onFailure { _notice.value = "音色列表加载失败，请稍后重试" }
        }
    }

    fun generateLetter(wishId: String, onGenerated: (String) -> Unit) {
        viewModelScope.launch {
            _isGenerating.value = true
            val voiceId = settings.selectedVoiceId.first()
            repository.generateLetter(wishId, voiceId)
                .onSuccess {
                    _notice.value = "未来信已生成"
                    onGenerated(it.id)
                }
                .onFailure { _notice.value = "生成失败，请检查网络后重试" }
            _isGenerating.value = false
        }
    }

    fun selectVoice(voiceId: String) {
        viewModelScope.launch { settings.saveSelectedVoiceId(voiceId) }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

class LetterDetailViewModel(
    private val repository: FutureMeRepository,
    val audioPlayer: AudioPlayer
) : ViewModel() {

    private val _letter = MutableStateFlow<LetterDto?>(null)
    val letter: StateFlow<LetterDto?> = _letter

    fun load(letterId: String) {
        viewModelScope.launch {
            _letter.value = repository.getLetter(letterId)
            repository.refreshLetters()
            _letter.value = repository.getLetter(letterId)
        }
    }

    fun audioUrl(): String? = _letter.value?.let { repository.resolveAudioUrl(it) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LettersScreen(
    viewModel: LettersViewModel,
    onLetterClick: (String) -> Unit
) {
    val letters by viewModel.letters.collectAsState()
    val wishes by viewModel.wishes.collectAsState()
    val voices by viewModel.voices.collectAsState()
    val selectedVoiceId by viewModel.selectedVoiceId.collectAsState()
    val isGenerating by viewModel.isGenerating.collectAsState()
    val notice by viewModel.notice.collectAsState()

    var selectedWishId by remember { mutableStateOf<String?>(null) }
    var showVoicePicker by remember { mutableStateOf(false) }

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    val selectedVoice = voices.firstOrNull { it.id == selectedVoiceId }
    val selectedWish = wishes.firstOrNull { it.id == selectedWishId }
        ?: wishes.firstOrNull()

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = { TopAppBar(title = { Text(text = stringResource(R.string.letters_title)) }) }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surface
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "给一个愿望写封未来信",
                            style = MaterialTheme.typography.titleMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        if (wishes.isEmpty()) {
                            Text(
                                text = "先去许愿页写下一个愿望",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        } else {
                            WishSelector(
                                wishes = wishes,
                                selectedWishId = selectedWish?.id,
                                onSelect = { selectedWishId = it }
                            )
                            Spacer(modifier = Modifier.height(12.dp))
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Text(
                                    text = "${stringResource(R.string.voice_current)}：${selectedVoice?.name ?: "默认"}",
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                OutlinedButton(onClick = { showVoicePicker = true }) {
                                    Text(text = stringResource(R.string.pick_voice))
                                }
                            }
                            Spacer(modifier = Modifier.height(12.dp))
                            Button(
                                onClick = {
                                    val wishId = selectedWish?.id ?: return@Button
                                    viewModel.generateLetter(wishId, onLetterClick)
                                },
                                enabled = selectedWish != null && !isGenerating,
                                modifier = Modifier.fillMaxWidth().height(48.dp)
                            ) {
                                if (isGenerating) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.padding(end = 8.dp),
                                        strokeWidth = 2.dp
                                    )
                                    Text(text = stringResource(R.string.generating_letter))
                                } else {
                                    Text(text = stringResource(R.string.generate_letter))
                                }
                            }
                        }
                    }
                }
            }
            if (letters.isEmpty()) {
                item {
                    EmptyBox(
                        message = stringResource(R.string.letters_empty),
                        modifier = Modifier.height(120.dp)
                    )
                }
            }
            items(letters, key = { it.id }) { letter ->
                LetterCard(letter = letter, onClick = { onLetterClick(letter.id) })
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }
    }

    if (showVoicePicker) {
        VoicePickerDialog(
            voices = voices,
            selectedVoiceId = selectedVoiceId,
            onSelect = { viewModel.selectVoice(it) },
            onDismiss = { showVoicePicker = false }
        )
    }
}

@Composable
private fun WishSelector(
    wishes: List<WishDto>,
    selectedWishId: String?,
    onSelect: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        wishes.forEach { wish ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onSelect(wish.id) },
                verticalAlignment = Alignment.CenterVertically
            ) {
                RadioButton(
                    selected = wish.id == selectedWishId,
                    onClick = { onSelect(wish.id) }
                )
                Text(
                    text = wish.text,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 2
                )
            }
        }
    }
}

@Composable
fun LetterCard(letter: LetterDto, onClick: () -> Unit) {
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
                text = letter.text.take(100) + if (letter.text.length > 100) "…" else "",
                style = MaterialTheme.typography.bodyMedium
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = letter.createdAt?.take(10) ?: "",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
fun VoicePickerDialog(
    voices: List<VoiceDto>,
    selectedVoiceId: String?,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(text = stringResource(R.string.pick_voice)) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                if (voices.isEmpty()) {
                    Text(text = "音色列表加载中…")
                }
                // Group by provider; within each group show tier badges.
                voices.groupBy { it.provider }.forEach { (provider, group) ->
                    Text(
                        text = provider,
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                    group.forEach { voice ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onSelect(voice.id) },
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            RadioButton(
                                selected = voice.id == selectedVoiceId,
                                onClick = { onSelect(voice.id) }
                            )
                            Column(modifier = Modifier.weight(1f)) {
                                Text(text = voice.name, fontWeight = FontWeight.Medium)
                                voice.description?.let {
                                    Text(
                                        text = it,
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                            FilterChip(
                                selected = false,
                                onClick = {},
                                label = {
                                    Text(
                                        if (voice.tier.equals("member", ignoreCase = true)) {
                                            stringResource(R.string.voice_member)
                                        } else {
                                            stringResource(R.string.voice_free)
                                        }
                                    )
                                }
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(text = stringResource(R.string.action_confirm))
            }
        }
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LetterDetailScreen(
    viewModel: LetterDetailViewModel,
    onBack: () -> Unit
) {
    val letter by viewModel.letter.collectAsState()
    val isPlaying by viewModel.audioPlayer.isPlaying.collectAsState()
    val positionMs by viewModel.audioPlayer.positionMs.collectAsState()
    val durationMs by viewModel.audioPlayer.durationMs.collectAsState()
    val currentUrl by viewModel.audioPlayer.currentUrl.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = stringResource(R.string.letters_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        val current = letter
        if (current == null) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = stringResource(R.string.letter_ai_label),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = current.text,
                        style = MaterialTheme.typography.bodyLarge
                    )
                }
            }

            // Audio player
            val audioUrl = viewModel.audioUrl()
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant
                )
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    if (audioUrl == null) {
                        Text(
                            text = stringResource(R.string.audio_no_audio),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            IconButton(
                                onClick = {
                                    if (currentUrl == audioUrl && isPlaying) {
                                        viewModel.audioPlayer.pause()
                                    } else {
                                        viewModel.audioPlayer.play(audioUrl)
                                    }
                                }
                            ) {
                                Icon(
                                    imageVector = Icons.Filled.PlayArrow,
                                    contentDescription = if (isPlaying) {
                                        stringResource(R.string.audio_pause)
                                    } else {
                                        stringResource(R.string.audio_play)
                                    }
                                )
                            }
                            Column(modifier = Modifier.weight(1f)) {
                                val duration = durationMs.coerceAtLeast(1L)
                                Slider(
                                    value = positionMs.toFloat().coerceIn(0f, duration.toFloat()),
                                    onValueChange = { viewModel.audioPlayer.seekTo(it.toLong()) },
                                    valueRange = 0f..duration.toFloat()
                                )
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween
                                ) {
                                    Text(
                                        text = formatMs(positionMs),
                                        style = MaterialTheme.typography.bodyMedium
                                    )
                                    Text(
                                        text = formatMs(durationMs),
                                        style = MaterialTheme.typography.bodyMedium
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun formatMs(ms: Long): String {
    val totalSeconds = (ms / 1000).toInt().coerceAtLeast(0)
    return "%d:%02d".format(totalSeconds / 60, totalSeconds % 60)
}
