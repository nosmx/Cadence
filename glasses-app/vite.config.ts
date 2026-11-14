import { defineConfig } from 'vite';

// host: true exposes the dev server on your LAN so the simulator,
// or the Even app on your phone (via `npm run qr`), can load it.
export default defineConfig({
  // Relative asset paths so the packaged .ehpk works wherever the Even app loads it from.
  base: './',
  server: { host: true, port: 5173, strictPort: true },
});
