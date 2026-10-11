import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  build: {
    lib: {
      entry: fileURLToPath(new URL('./index.js', import.meta.url)),
      name: 'FusionStreamer',
      fileName: () => 'fusion-streamer.js',
      formats: ['iife'],
    },
    outDir: fileURLToPath(new URL('../vendor', import.meta.url)),
    emptyOutDir: false,
  },
});
