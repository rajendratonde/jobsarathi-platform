import { apiRequest } from '../../api/client';
import type { ChangeOut, Page } from '../identity/api';

// Reference Data service. Field definitions come from the server, so the screens
// render any list without list-specific code.

const svc = 'reference';

export interface FieldDef {
  name: string; label: string; kind: 'int' | 'parent' | 'text'; required: boolean; immutable: boolean;
  parent_list: string | null;
}
export interface ListDef {
  list: string; label: string; requires_approval: boolean; active: number; total: number; searchable: boolean;
  fields: FieldDef[];
}
export interface AdminValue {
  id: string; code: string; name: string; name_hi: string | null; sort_order: number; is_active: boolean;
  version: number; updated_at: string;
  pending_request: { id: string; request_number: string; action_type: string; summary: string | null } | null;
  [extra: string]: unknown;
}
export interface PublicValue { code: string; name: string; name_hi: string | null }

const q = (params: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') s.set(k, String(v)); });
  return s.toString() ? `?${s}` : '';
};

export const referenceApi = {
  lists: () => apiRequest<ListDef[]>(svc, '/v1/admin/reference'),
  values: (list: string, params: { q?: string; state?: string; page?: number }) =>
    apiRequest<Page<AdminValue>>(svc, `/v1/admin/reference/${list}${q(params)}`),
  create: (list: string, body: Record<string, unknown>) =>
    apiRequest<ChangeOut>(svc, `/v1/admin/reference/${list}`, { method: 'POST', body }),
  update: (list: string, id: string, body: Record<string, unknown>, version: number) =>
    apiRequest<ChangeOut>(svc, `/v1/admin/reference/${list}/${id}`, { method: 'PUT', body: { ...body, version } }),
  setActive: (list: string, id: string, is_active: boolean, version: number) =>
    apiRequest<ChangeOut>(svc, `/v1/admin/reference/${list}/${id}/status`, { method: 'PATCH', body: { is_active, version } }),
  publicList: (list: string) => apiRequest<{ items: PublicValue[] }>(svc, `/v1/reference/${list}`, { anonymous: true }),
};
