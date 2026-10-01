export const MIN_PASSWORD_LENGTH = 8;

export interface PasswordStrength {
  pct: number;
  label: string;
  color: string;
  hint: string;
  ok: boolean;
}

// Shared strength check for signup + password reset. `ok` is the submit bar:
// at least MIN_PASSWORD_LENGTH characters and a score of 40+.
export function checkPasswordStrength(p: string): PasswordStrength {
  if (!p) {
    return { pct: 0, label: '', color: 'var(--soft)', hint: '', ok: false };
  }

  let score = 0;
  if (p.length >= 10) score += 25;
  if (p.length >= 14) score += 25;
  if (/[A-Z]/.test(p)) score += 15;
  if (/[0-9]/.test(p)) score += 15;
  if (/[^A-Za-z0-9]/.test(p)) score += 20;

  const ok = p.length >= MIN_PASSWORD_LENGTH && score >= 40;

  if (score < 40) {
    return {
      pct: score,
      label: 'Too weak',
      color: '#ef4444',
      hint:
        p.length < MIN_PASSWORD_LENGTH
          ? `Use at least ${MIN_PASSWORD_LENGTH} characters`
          : 'Add more characters, plus a number or symbol',
      ok: false,
    };
  }
  if (score < 75) {
    return {
      pct: score,
      label: 'Fair',
      color: 'var(--warn)',
      hint: p.length >= MIN_PASSWORD_LENGTH ? '' : `Use at least ${MIN_PASSWORD_LENGTH} characters`,
      ok,
    };
  }
  return { pct: score, label: 'Strong', color: 'var(--ok)', hint: '', ok };
}
