// All environment-specific values come from Vite env variables (VITE_*), never from code.
export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/svc',
  appEnv: (import.meta.env.VITE_APP_ENV as string | undefined) ?? 'local',
};

export const SERVICES = [
  { key: 'identity', name: 'Identity & Access' },
  { key: 'candidate', name: 'Candidate & Resume' },
  { key: 'employer', name: 'Employer' },
  { key: 'job', name: 'Job' },
  { key: 'application', name: 'Application' },
  { key: 'learning', name: 'Learning' },
  { key: 'engagement', name: 'Engagement' },
  { key: 'reference', name: 'Reference Data' },
] as const;

export type ServiceKey = (typeof SERVICES)[number]['key'];
