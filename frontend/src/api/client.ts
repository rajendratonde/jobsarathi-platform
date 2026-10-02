import { config } from '../config/env';
import { ApiError, toApiError } from './errors';

// One API client for the whole app: base URL from config, a correlation ID per
// user action, JSON in and out, and every failure turned into an ApiError.
// Authentication headers are added in the Identity phase (T4 is still open).

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** Optimistic locking: sent as If-Match on PUT/PATCH/DELETE of versioned records. */
  version?: number;
  correlationId?: string;
}

export function newCorrelationId(): string {
  return crypto.randomUUID().replace(/-/g, '');
}

export async function apiRequest<T>(service: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Correlation-Id': options.correlationId ?? newCorrelationId(),
  };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.version !== undefined) headers['If-Match'] = String(options.version);

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}/${service}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      credentials: 'include',
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the server. Check your connection and try again.');
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
