import { config } from '../config';
import { ApiClient } from './client';

const transport = import.meta.env.DEV && config.apiMode === 'mock'
  ? (await import('./mock/transport')).createMockTransport()
  : fetch.bind(globalThis);

export const api = new ApiClient(config.apiBaseUrl, transport);
