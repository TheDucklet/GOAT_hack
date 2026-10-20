import { config } from '../config';
import { HttpClient } from './http';

const transport = import.meta.env.DEV && config.apiMode === 'mock'
  ? (await import('./mock/transport')).createMockTransport()
  : fetch.bind(globalThis);

export const http = new HttpClient(config.apiBaseUrl, transport);
