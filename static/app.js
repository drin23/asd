/**
 * Call Center AI Agent — Frontend Application
 * Handles microphone capture, WebSocket communication, and audio playback.
 */

// ============================================================
// PCM Audio Worklet Processor (inline, registered as blob URL)
// Captures mic audio and converts to 16-bit PCM at 16kHz
// ============================================================
const CAPTURE_WORKLET_CODE = `
class CaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buffer = [];
        this.bufferSize = 2048; // ~128ms at 16kHz
    }

    process(inputs) {
        const input = inputs[0];
        if (input.length === 0) return true;

        const channelData = input[0];
        for (let i = 0; i < channelData.length; i++) {
            this.buffer.push(channelData[i]);
        }

        while (this.buffer.length >= this.bufferSize) {
            const chunk = this.buffer.splice(0, this.bufferSize);
            const pcm16 = new Int16Array(chunk.length);
            for (let i = 0; i < chunk.length; i++) {
                const s = Math.max(-1, Math.min(1, chunk[i]));
                pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
        }
        return true;
    }
}
registerProcessor('capture-processor', CaptureProcessor);
`;

// ============================================================
// App State
// ============================================================
const state = {
    ws: null,
    audioContext: null,
    mediaStream: null,
    workletNode: null,
    isActive: false,
    callStartTime: null,
    timerInterval: null,
    // Seamless audio playback state
    playbackCtx: null,         // Single shared AudioContext at 24kHz
    nextPlayTime: 0,           // When the next chunk should start playing
    scheduledSources: [],      // Track active AudioBufferSourceNodes for barge-in
    audioChunksReceived: false, // Whether we're currently receiving audio
    sessionReady: false,       // Whether Gemini session is ready to receive audio
    currentUserTranscript: '',
    currentAgentTranscript: '',
    userTranscriptEl: null,
    agentTranscriptEl: null,
};

// ============================================================
// DOM Elements
// ============================================================
const $ = (sel) => document.querySelector(sel);
const btnMic = $('#btnMic');
const btnEnd = $('#btnEnd');
const companySelect = $('#companySelect');
const statusBadge = $('#statusBadge');
const statusText = $('#statusText');
const transcriptArea = $('#transcriptArea');
const transcriptEmpty = $('#transcriptEmpty');
const callTimer = $('#callTimer');
const visualizer = $('#visualizer');

// ============================================================
// Initialize
// ============================================================
async function init() {
    // Load companies
    try {
        const res = await fetch('/api/companies');
        const data = await res.json();
        companySelect.innerHTML = '';
        if (data.companies.length === 0) {
            companySelect.innerHTML = '<option value="">Keine Unternehmen verfügbar</option>';
            return;
        }
        data.companies.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = c.name;
            companySelect.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load companies:', e);
        companySelect.innerHTML = '<option value="">Fehler beim Laden</option>';
    }

    btnMic.addEventListener('click', toggleCall);
    btnEnd.addEventListener('click', endCall);
}

// ============================================================
// Toggle Call
// ============================================================
async function toggleCall() {
    if (state.isActive) {
        endCall();
    } else {
        await startCall();
    }
}

// ============================================================
// Start Call
// ============================================================
async function startCall() {
    const companyId = companySelect.value;
    if (!companyId) {
        alert('Bitte wählen Sie ein Unternehmen aus.');
        return;
    }

    try {
        // Request microphone access
        state.mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            }
        });

        // Create AudioContext at 16kHz for capture
        state.audioContext = new AudioContext({ sampleRate: 16000 });

        // Register worklet
        const blob = new Blob([CAPTURE_WORKLET_CODE], { type: 'application/javascript' });
        const workletUrl = URL.createObjectURL(blob);
        await state.audioContext.audioWorklet.addModule(workletUrl);
        URL.revokeObjectURL(workletUrl);

        // Connect mic → worklet
        const source = state.audioContext.createMediaStreamSource(state.mediaStream);
        state.workletNode = new AudioWorkletNode(state.audioContext, 'capture-processor');
        source.connect(state.workletNode);
        state.workletNode.connect(state.audioContext.destination); // Required for processing

        // Recv PCM chunks from worklet
        state.workletNode.port.onmessage = (e) => {
            if (state.ws && state.ws.readyState === WebSocket.OPEN && state.sessionReady) {
                const pcmBuffer = e.data;
                const b64 = arrayBufferToBase64(pcmBuffer);
                state.ws.send(JSON.stringify({ type: 'audio', data: b64 }));
            }
        };

        // Connect WebSocket
        const wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        state.ws = new WebSocket(`${wsProtocol}//${location.host}/ws/call/${companyId}`);

        state.ws.onopen = () => {
            console.log('WebSocket connected');
        };

        state.ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            handleServerMessage(msg);
        };

        state.ws.onerror = (e) => {
            console.error('WebSocket error:', e);
            addSystemMessage('Verbindungsfehler. Bitte versuchen Sie es erneut.');
        };

        state.ws.onclose = () => {
            console.log('WebSocket closed');
            if (state.isActive) {
                endCall();
            }
        };

        // UI updates
        state.isActive = true;
        btnMic.classList.add('active');
        btnMic.title = 'Gespräch aktiv';
        btnEnd.disabled = false;
        companySelect.disabled = true;
        transcriptEmpty.style.display = 'none';

        // Start timer
        state.callStartTime = Date.now();
        callTimer.classList.add('active');
        state.timerInterval = setInterval(updateTimer, 1000);

        setStatus('connecting', 'Verbinde...');

        // Reset transcripts
        state.currentUserTranscript = '';
        state.currentAgentTranscript = '';
        state.userTranscriptEl = null;
        state.agentTranscriptEl = null;

    } catch (err) {
        console.error('Failed to start call:', err);
        alert('Mikrofon-Zugriff fehlgeschlagen: ' + err.message);
        endCall();
    }
}

// ============================================================
// End Call
// ============================================================
function endCall() {
    state.isActive = false;
    state.sessionReady = false;

    // Stop audio capture
    if (state.workletNode) {
        state.workletNode.disconnect();
        state.workletNode = null;
    }
    if (state.audioContext) {
        state.audioContext.close();
        state.audioContext = null;
    }
    if (state.mediaStream) {
        state.mediaStream.getTracks().forEach(t => t.stop());
        state.mediaStream = null;
    }

    // Close WebSocket
    if (state.ws) {
        try {
            state.ws.send(JSON.stringify({ type: 'stop' }));
        } catch (e) {}
        state.ws.close();
        state.ws = null;
    }

    // Stop all playback
    stopAllPlayback();
    if (state.playbackCtx) {
        state.playbackCtx.close();
        state.playbackCtx = null;
    }

    // UI
    btnMic.classList.remove('active');
    btnMic.title = 'Mikrofon starten';
    btnEnd.disabled = true;
    companySelect.disabled = false;
    visualizer.classList.remove('active');

    // Stop timer
    clearInterval(state.timerInterval);
    callTimer.classList.remove('active');

    setStatus('disconnected', 'Getrennt');

    addSystemMessage('Gespräch beendet.');
}

// ============================================================
// Handle Server Messages
// ============================================================
function handleServerMessage(msg) {
    switch (msg.type) {
        case 'status':
            if (msg.message === 'connected') {
                state.sessionReady = true;
                setStatus('connected', 'Verbunden');
            }
            break;

        case 'audio':
            // Schedule audio chunk for seamless playback
            scheduleAudioChunk(base64ToArrayBuffer(msg.data));
            visualizer.classList.add('active');
            setStatus('speaking', 'Agent spricht...');
            break;

        case 'transcript_user':
            // Accumulate user transcript
            if (!state.userTranscriptEl) {
                state.currentUserTranscript = '';
                state.userTranscriptEl = addTranscriptMessage('user', '');
            }
            state.currentUserTranscript += msg.text;
            updateTranscriptBubble(state.userTranscriptEl, state.currentUserTranscript);
            break;

        case 'transcript_agent':
            // Accumulate agent transcript
            if (!state.agentTranscriptEl) {
                state.currentAgentTranscript = '';
                state.agentTranscriptEl = addTranscriptMessage('agent', '');
            }
            state.currentAgentTranscript += msg.text;
            updateTranscriptBubble(state.agentTranscriptEl, state.currentAgentTranscript);
            break;

        case 'turn_complete':
            // Finalize current transcripts
            state.userTranscriptEl = null;
            state.currentUserTranscript = '';
            state.agentTranscriptEl = null;
            state.currentAgentTranscript = '';
            break;

        case 'interrupted':
            // Barge-in: stop all scheduled audio immediately
            stopAllPlayback();
            visualizer.classList.remove('active');
            setStatus('connected', 'Verbunden');
            // Finalize agent transcript
            state.agentTranscriptEl = null;
            state.currentAgentTranscript = '';
            break;

        case 'tool_call':
            addSystemMessage(`🔍 Wissensdatenbank: ${msg.name}(${JSON.stringify(msg.args || {})})`);
            break;

        case 'error':
            addSystemMessage(`❌ Fehler: ${msg.message}`);
            console.error('Server error:', msg.message);
            break;
    }
}

// ============================================================
// Seamless Audio Playback (24kHz PCM from Gemini)
// Uses a single AudioContext and precise scheduling to eliminate
// gaps/clicks between chunks — matches AI Studio quality.
// ============================================================
function ensurePlaybackContext() {
    if (!state.playbackCtx || state.playbackCtx.state === 'closed') {
        state.playbackCtx = new AudioContext({ sampleRate: 24000 });
        state.nextPlayTime = 0;
        state.scheduledSources = [];
    }
    return state.playbackCtx;
}

function scheduleAudioChunk(pcmData) {
    try {
        const ctx = ensurePlaybackContext();

        // Convert raw 16-bit PCM to float32
        const int16Array = new Int16Array(pcmData);
        const float32Array = new Float32Array(int16Array.length);
        for (let i = 0; i < int16Array.length; i++) {
            float32Array[i] = int16Array[i] / 32768.0;
        }

        // Create audio buffer
        const audioBuffer = ctx.createBuffer(1, float32Array.length, 24000);
        audioBuffer.getChannelData(0).set(float32Array);

        // Calculate when this chunk should start playing
        // If nextPlayTime is in the past, start from now (with tiny buffer)
        const now = ctx.currentTime;
        if (state.nextPlayTime < now) {
            state.nextPlayTime = now + 0.02; // 20ms buffer for smoothness
        }

        // Create and schedule the source node
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);

        // Schedule precisely — this is the key to seamless audio
        source.start(state.nextPlayTime);

        // Track this source for barge-in cancellation
        state.scheduledSources.push(source);

        // The next chunk should start exactly when this one ends
        state.nextPlayTime += audioBuffer.duration;

        // Clean up finished sources and detect end of speech
        source.onended = () => {
            state.scheduledSources = state.scheduledSources.filter(s => s !== source);
            // If no more sources are playing, agent finished speaking
            if (state.scheduledSources.length === 0) {
                visualizer.classList.remove('active');
                if (state.isActive) {
                    setStatus('connected', 'Verbunden');
                }
            }
        };

    } catch (e) {
        console.error('Audio scheduling error:', e);
    }
}

function stopAllPlayback() {
    // Immediately stop all scheduled audio sources (for barge-in)
    for (const source of state.scheduledSources) {
        try {
            source.stop();
        } catch (e) {} // May already have ended
    }
    state.scheduledSources = [];
    state.nextPlayTime = 0;
}

// ============================================================
// Transcript UI
// ============================================================
function addTranscriptMessage(role, text) {
    const div = document.createElement('div');
    div.className = `transcript-message ${role}`;

    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = role === 'user' ? '👤 Kunde' : '🤖 Agent';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;

    div.appendChild(label);
    div.appendChild(bubble);
    transcriptArea.appendChild(div);
    transcriptArea.scrollTop = transcriptArea.scrollHeight;

    return bubble;
}

function updateTranscriptBubble(bubbleEl, text) {
    if (bubbleEl) {
        bubbleEl.textContent = text;
        transcriptArea.scrollTop = transcriptArea.scrollHeight;
    }
}

function addSystemMessage(text) {
    const div = document.createElement('div');
    div.className = 'transcript-message system';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.textContent = text;

    div.appendChild(bubble);
    transcriptArea.appendChild(div);
    transcriptArea.scrollTop = transcriptArea.scrollHeight;
}

// ============================================================
// Status
// ============================================================
function setStatus(type, text) {
    statusBadge.className = `status-badge ${type}`;
    statusText.textContent = text;
}

// ============================================================
// Timer
// ============================================================
function updateTimer() {
    if (!state.callStartTime) return;
    const elapsed = Math.floor((Date.now() - state.callStartTime) / 1000);
    const minutes = Math.floor(elapsed / 60).toString().padStart(2, '0');
    const seconds = (elapsed % 60).toString().padStart(2, '0');
    callTimer.textContent = `${minutes}:${seconds}`;
}

// ============================================================
// Helpers
// ============================================================
function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

function base64ToArrayBuffer(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}

// ============================================================
// Start
// ============================================================
document.addEventListener('DOMContentLoaded', init);
