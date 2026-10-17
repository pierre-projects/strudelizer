import { defineConfig } from 'vite';

// The build lands in the Python package, which serves it as static files, so
// `pip install` is enough to get the app: no Node needed at run time.
export default defineConfig({
  build: {
    outDir: '../static',
    emptyOutDir: true,
    target: 'es2020',
    // Fixed names, not content hashes: the build is committed, so every rebuild
    // should rewrite the same two files instead of adding a pair.
    rollupOptions: {
      output: {
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/app.[ext]',
      },
    },
  },
  esbuild: {
    jsx: 'automatic',
    jsxImportSource: 'preact',
  },
  server: {
    port: 5173,
    // `npm run dev` talks to `strudelize ui --no-browser` for the API.
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
});
