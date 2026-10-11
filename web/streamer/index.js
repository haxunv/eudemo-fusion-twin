import { AppStreamer, StreamType } from '@nvidia/omniverse-webrtc-streaming-library';

let connecting = false;

async function connect({ onConnected, onDisconnected, onError } = {}) {
  if (connecting) return;
  connecting = true;
  const query = new URLSearchParams(location.search);
  const server = query.get('signalingServer') || '127.0.0.1';
  const port = Number(query.get('signalingPort') || 49100);
  const stopped = () => {
    connecting = false;
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
        if (message?.action === 'start' && message?.status === 'success') onConnected?.();
      },
      onStop: stopped,
      onTerminate: stopped,
    },
  }).catch((error) => {
    connecting = false;
    onError?.(error);
  });
}

window.FusionStreamer = { connect };
