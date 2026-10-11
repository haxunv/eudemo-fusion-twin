import { AppStreamer, StreamType } from '@nvidia/omniverse-webrtc-streaming-library';

let connecting = false;
let connected = false;
let requestId = 0;
const pending = new Map();
const diagnostics = { sent: 0, received: 0, timeouts: 0, lastEvent: null };

function receive(message) {
  const id = message?.id ?? message?.payload?.id;
  const entry = pending.get(id);
  diagnostics.lastEvent = message?.event_type;
  if (entry && message?.event_type === `${entry.name}_response`) {
    pending.delete(id);
    clearTimeout(entry.timer);
    diagnostics.received += 1;
    const payload = message.payload;
    if (payload?.error) entry.reject(new Error(payload.error));
    else entry.resolve(payload && Object.hasOwn(payload, 'response') ? payload.response : payload);
  }
  window.dispatchEvent(new CustomEvent('fusion:stream-message', { detail: message }));
}

function request(name, payload = {}, timeoutMs = 10000) {
  if (!connected) return Promise.reject(new Error('RTX data channel is disconnected'));
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      diagnostics.timeouts += 1;
      reject(new Error(`RTX request timed out: ${name}`));
    }, timeoutMs);
    pending.set(id, { name, resolve, reject, timer });
    diagnostics.sent += 1;
    AppStreamer.sendMessage(JSON.stringify({ event_type: `${name}_request`, payload: { ...payload, id } }))
      .then((result) => { if (result?.status === 'error') throw new Error(result.info); })
      .catch((error) => { clearTimeout(timer); pending.delete(id); reject(error); });
  });
}

async function connect({ onConnected, onDisconnected, onError } = {}) {
  if (connecting) return;
  connecting = true;
  const query = new URLSearchParams(location.search);
  const server = query.get('signalingServer') || '127.0.0.1';
  const port = Number(query.get('signalingPort') || 49100);
  const stopped = () => {
    connecting = false;
    connected = false;
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new Error('RTX data channel disconnected during request'));
    }
    pending.clear();
    onDisconnected?.();
  };
  let resolution = [2560, 1440];
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (response.ok) {
      const snapshot = await response.json();
      const configured = snapshot.renderer?.resolution;
      if (Array.isArray(configured) && configured.length === 2 && configured.every((value) => Number.isInteger(value) && value > 0)) resolution = configured;
    }
  } catch {
    // Use the QHD default when renderer metadata is temporarily unavailable.
  }
  AppStreamer.connect({
    streamSource: StreamType.DIRECT,
    streamConfig: {
      videoElementID: 'remote-video',
      audioElementID: 'remote-audio',
      signalingServer: server,
      signalingPort: port,
      mediaServer: query.get('mediaServer') || server,
      forceWSS: false,
      autoLaunch: true,
      cursor: 'free',
      mic: false,
      width: resolution[0],
      height: resolution[1],
      fps: 30,
      authenticate: false,
      maxReconnects: 5,
      nativeTouchEvents: true,
      localizeTextInput: true,
      onStart: (message) => {
        if (message?.action === 'start' && message?.status === 'success') {
          connected = true;
          onConnected?.();
        }
      },
      onCustomEvent: receive,
      onStop: stopped,
      onTerminate: stopped,
    },
  }).catch((error) => {
    stopped();
    onError?.(error);
  });
}

window.FusionStreamer = { connect, request, get connected() { return connected; },
  get diagnostics() { return { ...diagnostics, pending: pending.size }; } };
