import type { ReactNode } from 'react';
import { createBrowserRouter, Link, NavLink, Outlet, RouterProvider } from 'react-router-dom';

import { config } from '../config/env';
import { ApprovalsPage } from '../features/admin/ApprovalsPage';
import { MatrixPage } from '../features/admin/MatrixPage';
import { visibleNav } from '../features/admin/nav';
import { PermissionsPage } from '../features/admin/PermissionsPage';
import { RolesPage } from '../features/admin/RolesPage';
import { UsersPage } from '../features/admin/UsersPage';
import { AuthProvider, useAuth } from '../features/auth/AuthContext';
import { ChangePasswordPage } from '../features/auth/ChangePasswordPage';
import { LoginPage } from '../features/auth/LoginPage';
import { OrganizationSelectPage, OrganizationSwitcher } from '../features/auth/OrganizationPicker';
import { ReferenceDataPage } from '../features/reference/ReferenceDataPage';
import { SystemStatusPage } from '../features/system-status/SystemStatusPage';
import { NotFoundPage } from '../shared/NotFoundPage';

// Business feature areas (candidate, employer, jobs, applications, learning,
// engagement) come in their own phases. This phase adds sign-in, organization
// context and the Identity administration screens, all driven by permissions.

function TopBar() {
  const { session, signOut } = useAuth();
  return (
    <header className="topbar">
      <Link to="/" className="brand">Job<span>Sarathi</span></Link>
      <div className="topbar-right">
        <OrganizationSwitcher />
        {session && <span className="who">{session.user.display_name}</span>}
        {session && <button className="ghost" onClick={() => void signOut()}>Sign out</button>}
        <span className="env">{config.appEnv}</span>
      </div>
    </header>
  );
}

/** Decides what a visitor may see: sign-in, forced password change, organization choice, then the app. */
function SessionGate({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <p className="muted" role="status">Loading…</p>;
  if (!session) return <LoginPage />;
  if (session.passwordChangeRequired) return <ChangePasswordPage />;
  if (session.activeOrganizationId === null && session.organizations.length > 1) return <OrganizationSelectPage />;
  return <>{children}</>;
}

function Layout() {
  const { session, can } = useAuth();
  const nav = session && !session.passwordChangeRequired ? visibleNav(can) : [];
  return (
    <div className="shell">
      <TopBar />
      {nav.length > 0 && (
        <nav className="subnav" aria-label="Administration">
          {nav.map((item) => <NavLink key={item.path} to={item.path}>{item.label}</NavLink>)}
        </nav>
      )}
      <main className="content">
        <SessionGate><Outlet /></SessionGate>
      </main>
    </div>
  );
}

function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(permission)) {
    return <p className="error" role="alert">You do not have permission to open this page.</p>;
  }
  return <>{children}</>;
}

function HomePage() {
  const { session, can } = useAuth();
  const nav = visibleNav(can);
  const org = session?.organizations.find((o) => o.organization.id === session.activeOrganizationId);
  return (
    <section>
      <h1>Welcome, {session?.user.display_name}</h1>
      <p className="muted">{org ? `Acting for ${org.organization.name}.` : 'No organization selected.'}</p>
      {nav.length === 0 ? <p>There is nothing to manage here yet with your current access.</p> : (
        <ul className="cards">
          {nav.map((item) => <li key={item.path}><Link to={item.path}>{item.label}</Link></li>)}
        </ul>
      )}
    </section>
  );
}

const guarded = (permission: string, element: ReactNode) => <RequirePermission permission={permission}>{element}</RequirePermission>;

export const routes = [
  { path: '/status', element: <div className="shell"><main className="content"><SystemStatusPage /></main></div> },
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'admin/users', element: guarded('USER.VIEW', <UsersPage />) },
      { path: 'admin/roles', element: guarded('ROLE.VIEW', <RolesPage />) },
      { path: 'admin/permissions', element: guarded('ROLE.VIEW', <PermissionsPage />) },
      { path: 'admin/matrix', element: guarded('ROLE.VIEW', <MatrixPage />) },
      { path: 'admin/reference', element: guarded('REFERENCE.EDIT', <ReferenceDataPage />) },
      { path: 'admin/approvals', element: guarded('MAKER_CHECKER.VIEW', <ApprovalsPage />) },
      { path: 'account/password', element: <ChangePasswordPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

const router = () => createBrowserRouter(routes, {
  future: { v7_relativeSplatPath: true, v7_fetcherPersist: true, v7_normalizeFormMethod: true, v7_partialHydration: true,
            v7_skipActionErrorRevalidation: true },
});

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router()} future={{ v7_startTransition: true }} />
    </AuthProvider>
  );
}
