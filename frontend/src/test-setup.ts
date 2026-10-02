import '@testing-library/jest-dom/vitest';
import { beforeEach } from 'vitest';

// Tests start as a returning visitor so the session-resume path is exercised.
beforeEach(() => localStorage.setItem('js_session_hint', '1'));
