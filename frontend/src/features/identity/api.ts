import { apiRequest } from '../../api/client';

// Typed calls to the Identity & Access service. Shapes mirror the backend schemas.

const svc = 'identity';

export interface UserBrief { id: string; display_name: string; status: string }
export interface OrganizationBrief {
  id: string; organization_code: string; name: string; organization_type: string; is_platform: boolean; status: string;
}
export interface MyOrganization { organization: OrganizationBrief; membership_id: string; membership_status: string; roles: string[] }
export interface TokenOut {
  access_token: string; expires_at: number; password_change_required: boolean; user: UserBrief;
  active_organization_id: string | null; organizations: MyOrganization[];
}
export interface PermissionsOut {
  organization_id: string | null; authz_version: number; roles: string[]; permissions: Record<string, string>;
}
export interface Page<T> { items: T[]; page: number; size: number; total: number }
export interface UserOut extends UserBrief { authz_version: number; last_login_at: string | null; created_at: string; version: number }
export interface IdentityOut { identity_type: string; identifier: string; verified: boolean; is_primary: boolean }
export interface MembershipRow {
  membership_id: string; organization_id: string; organization_name: string; organization_code: string;
  is_platform: boolean; status: string; version: number;
}
export interface UserDetail extends UserOut { identities: IdentityOut[]; memberships: MembershipRow[] }
export interface Assignment {
  id: string; role: { id: string; name: string; role_code: string; status: string; deleted: boolean };
  membership_id: string | null; organization: { id: string; name: string; is_platform: boolean } | null;
  scope_type: string; status: string; valid_until: string | null; version: number;
}
export interface Role {
  id: string; role_code: string; name: string; description: string | null; owner_organization_id: string | null;
  is_system: boolean; status: string; version: number; deleted_at: string | null;
}
export interface RoleDetail extends Role {
  permission_ids: string[]; permission_codes: string[]; holders: number;
  pending_request: { id: string; request_number: string; action_type: string; summary: string | null } | null;
}
export interface Permission {
  id: string; permission_code: string; description: string | null; module_code: string; resource_code: string;
  action_code: string; is_active: boolean; is_enforced: boolean; declared_by_service: string | null;
}
export interface ChangeOut {
  status: 'APPLIED' | 'PENDING_APPROVAL' | 'UNCHANGED'; entity_id: string;
  approval_request: { id: string; request_number: string; status: string } | null;
}
export interface MatrixCell { permission_id: string; permission_code: string; is_active: boolean; is_enforced: boolean; granted: boolean }
export interface Matrix {
  role: { id: string; name: string; role_code: string; version: number; status: string; is_system: boolean } | null;
  columns: { action_id: string; action_code: string; name: string }[];
  rows: { module_code: string; module_name: string; resource_id: string; resource_code: string; resource_name: string;
          is_active: boolean; cells: (MatrixCell | null)[] }[];
}
export interface Approval {
  id: string; request_number: string; entity_type: string; entity_id: string; entity_version: number; action_type: string;
  organization_id: string | null; subject_user_id: string | null; change_summary: string | null; maker_user_id: string;
  submitted_at: string; status: string; decision_reason: string | null; proposed_changes: Record<string, unknown> | null;
}
export interface ApprovalDetail extends Approval {
  actions: { action: string; actor_user_id: string; comment: string | null; acted_at: string }[];
  can_decide: boolean; can_withdraw: boolean;
}

const q = (params: Record<string, string | number | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') s.set(k, String(v)); });
  const text = s.toString();
  return text ? `?${text}` : '';
};

export const identityApi = {
  // auth
  login: (email: string, password: string) =>
    apiRequest<TokenOut>(svc, '/v1/auth/password/login', { method: 'POST', body: { email, password }, anonymous: true }),
  requestOtp: (mobile: string) =>
    apiRequest<{ challenge_id: string; expires_at: string; resend_after_seconds: number; sent_to: string }>(
      svc, '/v1/auth/otp/request', { method: 'POST', body: { mobile, purpose: 'LOGIN' }, anonymous: true }),
  verifyOtp: (challenge_id: string, mobile: string, code: string) =>
    apiRequest<TokenOut>(svc, '/v1/auth/otp/verify', { method: 'POST', body: { challenge_id, mobile, code }, anonymous: true }),
  refresh: () => apiRequest<TokenOut>(svc, '/v1/auth/refresh', { method: 'POST', anonymous: true }),
  changePassword: (current_password: string, new_password: string) =>
    apiRequest<TokenOut>(svc, '/v1/auth/password/change', { method: 'POST', body: { current_password, new_password } }),
  logout: () => apiRequest<void>(svc, '/v1/auth/logout', { method: 'POST' }),
  switchOrganization: (organization_id: string) =>
    apiRequest<{ token: TokenOut; permissions: PermissionsOut }>(svc, '/v1/me/organization/switch',
      { method: 'POST', body: { organization_id } }),
  permissions: (noRetry = false) => apiRequest<PermissionsOut>(svc, '/v1/me/permissions', { noRetry }),

  // users
  users: (params: { q?: string; page?: number }) => apiRequest<Page<UserOut>>(svc, `/v1/users${q(params)}`),
  user: (id: string) => apiRequest<UserDetail>(svc, `/v1/users/${id}`),
  createUser: (body: { display_name: string; email: string; organization_id?: string | null }) =>
    apiRequest<{ user: UserOut; membership_id: string; temporary_password: string }>(svc, '/v1/users', { method: 'POST', body }),
  setUserStatus: (id: string, status: string) =>
    apiRequest<UserOut>(svc, `/v1/users/${id}/status`, { method: 'PATCH', body: { status } }),
  resetPassword: (id: string) =>
    apiRequest<{ temporary_password: string }>(svc, `/v1/users/${id}/password/reset`, { method: 'POST' }),
  userRoles: (id: string) => apiRequest<Assignment[]>(svc, `/v1/users/${id}/roles`),
  assignRole: (id: string, body: { role_id: string; membership_id: string | null; scope_type: string }) =>
    apiRequest<ChangeOut>(svc, `/v1/users/${id}/roles`, { method: 'POST', body }),
  revokeRole: (id: string, assignmentId: string) =>
    apiRequest<void>(svc, `/v1/users/${id}/roles/${assignmentId}`, { method: 'DELETE' }),

  // roles and permissions
  roles: (params: { q?: string; page?: number; size?: number }) => apiRequest<Page<Role>>(svc, `/v1/roles${q(params)}`),
  role: (id: string) => apiRequest<RoleDetail>(svc, `/v1/roles/${id}`),
  createRole: (body: { name: string; description?: string; permission_ids: string[] }) =>
    apiRequest<ChangeOut>(svc, '/v1/roles', { method: 'POST', body }),
  setRolePermissions: (id: string, permission_ids: string[], version: number) =>
    apiRequest<ChangeOut>(svc, `/v1/roles/${id}/permissions`, { method: 'PUT', body: { permission_ids, version } }),
  setRoleStatus: (id: string, status: string, version: number) =>
    apiRequest<ChangeOut>(svc, `/v1/roles/${id}/status`, { method: 'PATCH', body: { status, version } }),
  permissionList: () => apiRequest<Permission[]>(svc, '/v1/permissions'),
  setPermissionStatus: (id: string, is_active: boolean) =>
    apiRequest<ChangeOut>(svc, `/v1/permissions/${id}/status`, { method: 'PATCH', body: { is_active } }),
  matrix: (roleId?: string) => apiRequest<Matrix>(svc, `/v1/rbac/matrix${q({ role_id: roleId })}`),

  // approvals
  approvals: (status: string) => apiRequest<Page<Approval>>(svc, `/v1/approvals${q({ status, size: 50 })}`),
  approval: (id: string) => apiRequest<ApprovalDetail>(svc, `/v1/approvals/${id}`),
  approve: (id: string, reviewed_version: number) =>
    apiRequest<ApprovalDetail>(svc, `/v1/approvals/${id}/approve`, { method: 'POST', body: { reviewed_version } }),
  reject: (id: string, reviewed_version: number, reason: string) =>
    apiRequest<ApprovalDetail>(svc, `/v1/approvals/${id}/reject`, { method: 'POST', body: { reviewed_version, reason } }),
  withdraw: (id: string) => apiRequest<ApprovalDetail>(svc, `/v1/approvals/${id}/withdraw`, { method: 'POST' }),
};
