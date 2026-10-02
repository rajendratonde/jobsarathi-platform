import { createBrowserRouter, Link, Outlet, RouterProvider } from 'react-router-dom';

import { config } from '../config/env';
import { SystemStatusPage } from '../features/system-status/SystemStatusPage';
import { NotFoundPage } from '../shared/NotFoundPage';

// Feature areas (candidate, employer, jobs, applications, learning, engagement,
// admin) and the auth / organization-context / permissions modules are added in
// their own phases. Foundation provides only the shell and the status page.

function Layout() {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          Job<span>Sarathi</span>
        </Link>
        <span className="env">{config.appEnv}</span>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}

export const routes = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <SystemStatusPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export function App() {
  return <RouterProvider router={createBrowserRouter(routes)} />;
}
