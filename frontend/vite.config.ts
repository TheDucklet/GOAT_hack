import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  if (command === 'build' && env.VITE_API_MODE === 'mock') {
    throw new Error('Mock API is only available in development. Build with VITE_API_MODE=http.');
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api(?=\/|$)/, ''),
        },
      },
    },
    preview: { port: 4173, strictPort: true },
  };
});
