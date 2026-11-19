package com.junze.futureme.data.audio

import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Thin ExoPlayer wrapper for streaming a letter's audio URL.
 * One player per app; call [release] from Application.onTerminate / when done.
 */
class AudioPlayer(context: Context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    private val player: ExoPlayer = ExoPlayer.Builder(context.applicationContext).build()

    private val _isPlaying = MutableStateFlow(false)
    val isPlaying: StateFlow<Boolean> = _isPlaying.asStateFlow()

    private val _positionMs = MutableStateFlow(0L)
    val positionMs: StateFlow<Long> = _positionMs.asStateFlow()

    private val _durationMs = MutableStateFlow(0L)
    val durationMs: StateFlow<Long> = _durationMs.asStateFlow()

    private val _currentUrl = MutableStateFlow<String?>(null)
    val currentUrl: StateFlow<String?> = _currentUrl.asStateFlow()

    private var positionJobActive = false

    init {
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                _isPlaying.value = isPlaying
                if (isPlaying) startPositionPolling()
            }

            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) {
                    _durationMs.value = player.duration.coerceAtLeast(0L)
                }
                if (state == Player.STATE_ENDED) {
                    _isPlaying.value = false
                    _positionMs.value = 0L
                }
            }
        })
    }

    fun play(url: String) {
        if (_currentUrl.value != url) {
            player.setMediaItem(MediaItem.fromUri(url))
            player.prepare()
            _currentUrl.value = url
        }
        player.play()
    }

    fun pause() {
        player.pause()
    }

    fun toggle(url: String) {
        if (_currentUrl.value == url && _isPlaying.value) pause() else play(url)
    }

    fun seekTo(positionMs: Long) {
        player.seekTo(positionMs)
        _positionMs.value = positionMs
    }

    fun stop() {
        player.stop()
        _isPlaying.value = false
        _positionMs.value = 0L
        _currentUrl.value = null
    }

    fun release() {
        scope.cancel()
        player.release()
    }

    private fun startPositionPolling() {
        if (positionJobActive) return
        positionJobActive = true
        scope.launch {
            while (_isPlaying.value) {
                _positionMs.value = player.currentPosition.coerceAtLeast(0L)
                val duration = player.duration
                if (duration > 0) _durationMs.value = duration
                delay(500)
            }
            positionJobActive = false
        }
    }
}
