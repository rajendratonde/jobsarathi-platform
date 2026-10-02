import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <section className="page">
      <h1>Page not found</h1>
      <p className="muted">This page does not exist.</p>
      <Link to="/">Go to system status</Link>
    </section>
  );
}
