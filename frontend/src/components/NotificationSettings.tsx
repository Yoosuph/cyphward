/* Settings › Notifications (notifications phase 1). One row per category with two switches: in the app, and by
 * email. Notification email is sent for critical events; the compliance email switch also stops the compliance
 * reminder emails (lib/notifications.ts PREFS_NOTE). A change saves at once; a failed save puts the switch back and
 * says so in reviewed wording. `focusCategory` (from the email's settings link) scrolls to and highlights a row.
 */
import { useEffect, useRef, useState } from 'react';
import { getNotificationPreferences, setNotificationPreference } from '../lib/api';
import { PREFS_ERROR, PREFS_NOTE, PREFS_SAVE_ERROR, type NotificationPreference } from '../lib/notifications';

type Channel = 'in_app' | 'email';

export default function NotificationSettings({ focusCategory }: { focusCategory?: string | null }) {
  const [prefs, setPrefs] = useState<NotificationPreference[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const focused = useRef<HTMLLIElement>(null);

  const load = async () => {
    setFailed(false);
    try {
      setPrefs(await getNotificationPreferences());
    } catch {
      setFailed(true);
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { if (prefs && focusCategory) focused.current?.scrollIntoView({ block: 'center' }); }, [prefs, focusCategory]);

  const toggle = async (category: string, channel: Channel) => {
    if (!prefs || busy) return;
    const before = prefs;
    const current = prefs.find(p => p.category === category);
    if (!current) return;
    const value = !current[channel];
    setBusy(`${category}:${channel}`);
    setSaveError(false);
    setPrefs(prefs.map(p => (p.category === category ? { ...p, [channel]: value } : p)));
    try {
      const saved = await setNotificationPreference(category, { [channel]: value });
      if (saved) setPrefs(list => list && list.map(p => (p.category === category ? { ...p, in_app: saved.in_app, email: saved.email } : p)));
    } catch {
      setPrefs(before);
      setSaveError(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="notif-settings-heading" data-testid="notif-settings-panel">
      <h2 id="notif-settings-heading" className="text-sm font-semibold text-ink">Notifications</h2>
      <p className="text-xs text-soft mt-1 max-w-2xl">
        Choose what reaches you. The bell in the header shows notifications for the organisation you are in. {PREFS_NOTE}
      </p>
      {saveError && <p className="text-xs text-accent mt-3" role="alert" data-testid="notif-save-error">{PREFS_SAVE_ERROR}</p>}
      {failed && (
        <div className="mt-4 text-sm text-soft space-y-2" role="alert">
          <p>{PREFS_ERROR}</p>
          <button type="button" className="btn-mini" onClick={load}>Try again</button>
        </div>
      )}
      {!failed && prefs === null && <p className="mt-4 text-sm text-soft">Loading…</p>}
      {!failed && prefs !== null && prefs.length === 0 && (
        <p className="mt-4 text-sm text-soft">Notification settings are not available right now.</p>
      )}
      {!failed && prefs && prefs.length > 0 && (
        <ul className="mt-4 divide-y divide-line border border-line rounded">
          {prefs.map(p => (
            <li key={p.category} ref={p.category === focusCategory ? focused : undefined}
                className={`notif-pref ${p.category === focusCategory ? 'is-focus' : ''}`} data-testid="notif-pref" data-category={p.category}>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{p.label}</p>
                <p className="text-xs text-soft">{p.hint}</p>
              </div>
              <div className="notif-pref-switches">
                {(['in_app', 'email'] as Channel[]).map(channel => (
                  <button key={channel} type="button" role="switch" aria-checked={p[channel]}
                          className={`notif-switch ${p[channel] ? 'is-on' : ''}`}
                          disabled={busy === `${p.category}:${channel}`}
                          aria-label={`${p.label}: ${channel === 'in_app' ? 'in the app' : 'by email'}`}
                          data-testid={`notif-switch-${channel}`} onClick={() => toggle(p.category, channel)}>
                    <span className="notif-switch-track" aria-hidden="true"><span className="notif-switch-knob" /></span>
                    <span className="notif-switch-label">{channel === 'in_app' ? 'In app' : 'Email'}: {p[channel] ? 'on' : 'off'}</span>
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
