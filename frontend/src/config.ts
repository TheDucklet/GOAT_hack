const mode = import.meta.env.VITE_API_MODE || 'http';
if (mode !== 'http' && mode !== 'mock') throw new Error('VITE_API_MODE must be http or mock');
if (mode === 'mock' && !import.meta.env.DEV) throw new Error('Mock API requires development mode');

export const config = {
  apiMode: mode as 'http' | 'mock',
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || '/api',
};
