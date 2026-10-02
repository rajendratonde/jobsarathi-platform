// Admin navigation is data: each entry names the permission that unlocks it.
// No role name appears in the UI; what a user sees comes from /me/permissions.

export interface NavItem {
  path: string;
  label: string;
  permission: string;
}

export const ADMIN_NAV: NavItem[] = [
  { path: '/admin/users', label: 'Users', permission: 'USER.VIEW' },
  { path: '/admin/roles', label: 'Roles', permission: 'ROLE.VIEW' },
  { path: '/admin/permissions', label: 'Permissions', permission: 'ROLE.VIEW' },
  { path: '/admin/matrix', label: 'Permission matrix', permission: 'ROLE.VIEW' },
  { path: '/admin/approvals', label: 'Approvals', permission: 'MAKER_CHECKER.VIEW' },
];

export function visibleNav(can: (permission: string) => boolean): NavItem[] {
  return ADMIN_NAV.filter((item) => can(item.permission));
}
