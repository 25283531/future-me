package com.junze.futureme.ui.daily

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.junze.futureme.R
import com.junze.futureme.data.api.CheckinStatusDto
import com.junze.futureme.data.prefs.SettingsStore
import com.junze.futureme.data.repository.FutureMeRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

class DailyViewModel(
    private val repository: FutureMeRepository,
    private val settings: SettingsStore
) : ViewModel() {

    private val _sentence = MutableStateFlow<String?>(null)
    val sentence: StateFlow<String?> = _sentence

    private val _status = MutableStateFlow<CheckinStatusDto?>(null)
    val status: StateFlow<CheckinStatusDto?> = _status

    private val _isCheckingIn = MutableStateFlow(false)
    val isCheckingIn: StateFlow<Boolean> = _isCheckingIn

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            // Cached sentence first so the screen is never empty offline.
            _sentence.value = settings.cachedDailySentence.first()
            repository.getDailySentence()
                .onSuccess { _sentence.value = it.text }
                .onFailure {
                    _notice.value = "网络不可用，显示的是上次保存的内容"
                }
            repository.getCheckinStatus()
                .onSuccess { _status.value = it }
                .onFailure { /* keep previous status */ }
        }
    }

    fun checkin() {
        viewModelScope.launch {
            _isCheckingIn.value = true
            repository.checkin()
                .onSuccess {
                    _status.value = it
                    _notice.value = "打卡成功，坚持就是胜利"
                }
                .onFailure { _notice.value = "打卡失败，请检查网络后重试" }
            _isCheckingIn.value = false
        }
    }

    fun clearNotice() {
        _notice.value = null
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DailyScreen(viewModel: DailyViewModel) {
    val sentence by viewModel.sentence.collectAsState()
    val status by viewModel.status.collectAsState()
    val isCheckingIn by viewModel.isCheckingIn.collectAsState()
    val notice by viewModel.notice.collectAsState()

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(notice) {
        notice?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearNotice()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = { TopAppBar(title = { Text(text = stringResource(R.string.daily_title)) }) }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Spacer(modifier = Modifier.height(8.dp))
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surface
                ),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(
                    modifier = Modifier.padding(20.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = "每日一句",
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = sentence ?: "加载中…",
                        style = MaterialTheme.typography.headlineMedium,
                        textAlign = TextAlign.Center
                    )
                }
            }

            val currentStatus = status
            if (currentStatus != null) {
                Row(horizontalArrangement = Arrangement.spacedBy(32.dp)) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "${currentStatus.streak}",
                            style = MaterialTheme.typography.headlineMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = stringResource(R.string.streak_days, currentStatus.streak),
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "${currentStatus.totalDays}",
                            style = MaterialTheme.typography.headlineMedium,
                            color = MaterialTheme.colorScheme.primary
                        )
                        Text(
                            text = stringResource(R.string.total_days, currentStatus.totalDays),
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.weight(1f))
            Button(
                onClick = { viewModel.checkin() },
                enabled = status?.checkedInToday != true && !isCheckingIn,
                modifier = Modifier.size(96.dp)
            ) {
                if (isCheckingIn) {
                    CircularProgressIndicator()
                } else {
                    Text(
                        text = if (status?.checkedInToday == true) {
                            stringResource(R.string.checkin_done)
                        } else {
                            stringResource(R.string.checkin)
                        },
                        style = MaterialTheme.typography.titleLarge
                    )
                }
            }
            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}
