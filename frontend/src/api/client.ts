import { config } from '../config/env';
import { ApiError, toApiError } from './errors';

// One API client for the whole app: base URL from config, a correlation ID per
// user action, JSON in and out, and every failure turned into an ApiError.
// The access token lives only in memory (never localStorage); the refresh token
// is an httpOnly cookie the browser sends to Identity on its own.

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
  /** Optimistic locking: sent as If-Match on PUT/PATCH/DELETE of versioned records. */
  version?: number;
  correlationId?: string;
  /** Skip the Authorization header and the stale-token retry (sign-in and refresh calls). */
  anonymous?: boolean;
  /** Do not refresh-and-retry on 401 (used while a refresh is already running). */
  noRetry?: boolean;
}

interface AuthHooks {
  token: () => string | null;
  /** Called once when the server says the token is stale or expired; returns true if a new token was obtained. */
  refresh: () => Promise<boolean>;
}

let auth: AuthHooks = { token: () => null, refresh: async () => false };

export function setAuthHooks(hooks: AuthHooks): void {
  auth = hooks;
}

export function newCorrelationId(): string {
  return crypto.randomUUID().replace(/-/g, '');
}

async function send(service: string, path: string, options: RequestOptions, correlationId: string): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', 'X-Correlation-Id': correlationId };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.version !== undefined) headers['If-Match'] = String(options.version);
  const token = options.anonymous ? null : auth.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    return await fetch(`${config.apiBaseUrl}/${service}${path}`, {
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
}

export async function apiRequest<T>(service: string, path: string, options: RequestOptions = {}): Promise<T> {
  const correlationId = options.correlationId ?? newCorrelationId();
  let response = await send(service, path, options, correlationId);
  if (response.status === 401 && !options.anonymous && !options.noRetry && auth.token()) {
    // TOKEN_STALE (access changed) or an expired token: refresh once, then retry.
    const error = await toApiError(response.clone());
    if (['TOKEN_STALE', 'UNAUTHENTICATED'].includes(error.code) && (await auth.refresh())) {
      response = await send(service, path, options, correlationId);
    }
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
