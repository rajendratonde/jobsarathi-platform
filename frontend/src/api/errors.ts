// Mirrors the backend error model (Implementation Blueprint §21).
export interface FieldError {
  field: string;
  code: string;
  message: string;
}

export interface ErrorBody {
  type: string;
  status: number;
  code: string;
  message: string;
  errors: FieldError[];
  details: Record<string, unknown>;
  correlation_id: string | null;
  timestamp: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldError[];
  readonly correlationId: string | null;

  constructor(status: number, code: string, message: string, fieldErrors: FieldError[] = [], correlationId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.correlationId = correlationId;
  }

  /** Message for one form field, if the server named it. */
  forField(field: string): string | undefined {
    return this.fieldErrors.find((e) => e.field === field)?.message;
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  return typeof value === 'object' && value !== null && 'code' in value && 'status' in value && 'message' in value;
}

export async function toApiError(response: Response): Promise<ApiError> {
  const correlationId = response.headers.get('x-correlation-id');
  try {
    const body: unknown = await response.json();
    if (isErrorBody(body)) {
      return new ApiError(body.status, body.code, body.message, body.errors ?? [], body.correlation_id ?? correlationId);
    }
  } catch {
    // not JSON (e.g. a proxy error page)
  }
  return new ApiError(response.status, 'HTTP_ERROR', 'Something went wrong. Please try again.', [], correlationId);
}
