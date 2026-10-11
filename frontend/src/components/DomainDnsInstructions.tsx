import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { useToast } from './Toast';

export default function DomainDnsInstructions({ domain, token }: { domain: string; token?: string }) {
  const [zone, setZone] = useState(domain);
  const [copied, setCopied] = useState<string | null>(null);
  const toast = useToast();
  const dnsZone = zone.trim().toLowerCase().replace(/\.$/, '');
  const validZone = !!dnsZone && (domain === dnsZone || domain.endsWith(`.${dnsZone}`));
  const fullName = `_cyphward.${domain}`;
  const prefix = validZone && domain !== dnsZone ? domain.slice(0, -(dnsZone.length + 1)) : '';
  const host = prefix ? `_cyphward.${prefix}` : '_cyphward';
  const value = token?.startsWith('cyphward-verification=') ? token : `cyphward-verification=${token || ''}`;

  const copy = async (text: string, kind: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
      setTimeout(() => setCopied(current => current === kind ? null : current), 2000);
      toast(`${kind === 'instructions' ? 'DNS instructions' : 'Record ' + kind} copied.`);
    } catch {
      toast('Could not copy. Select and copy the text below instead.');
    }
  };

  if (!token) return <p role="alert" className="text-xs text-accent">Verification instructions are unavailable. Reload this page to retrieve the domain's token.</p>;

  const instructions = `Verify domain ownership for ${domain} on Cyphward.\nDNS zone: ${dnsZone}\nType: TXT\nName / Host: ${host}\nFull record name: ${fullName}\nValue: ${value}\nTTL: 300 seconds (or provider default)\nSave the record, then return to Cyphward and click Verify domain. DNS changes may take time to appear.`;
  const row = (label: string, text: string, kind: string, ariaLabel: string) => (
    <div>
      <p className="text-[10px] mono text-soft">{label}</p>
      <div className="flex items-center gap-2">
        <p className="text-xs mono font-medium text-ink break-all min-w-0 flex-1 select-text">{text}</p>
        <button type="button" disabled={!validZone} onClick={() => copy(text, kind)} aria-label={ariaLabel} title={ariaLabel} className="flex-none min-h-[44px] min-w-[44px] flex items-center justify-center rounded hover:bg-accent/10 text-soft hover:text-ink disabled:opacity-40">
          {copied === kind ? <Check size={14} className="text-ok" /> : <Copy size={14} />}
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="field">
        <label htmlFor="dns-zone">DNS ZONE MANAGED BY YOUR PROVIDER</label>
        <input id="dns-zone" value={zone} onChange={event => setZone(event.target.value)} autoCapitalize="none" spellCheck={false} aria-describedby="dns-zone-help" />
        <p id="dns-zone-help" className="text-xs text-soft mt-1">Use the zone shown in your DNS panel. For www.example.com, this is usually example.com. If your provider manages www.example.com as its own zone, enter that instead.</p>
      </div>
      {!validZone && <p role="alert" className="text-xs text-accent">Enter {domain} or a parent DNS zone containing this domain.</p>}
      <div className="p-3 bg-inset rounded border border-line space-y-1">
        <p className="text-[10px] mono text-soft">DNS RECORD TO ADD · TXT</p>
        {row('NAME / HOST', validZone ? host : 'Choose a valid DNS zone above', 'host', 'Copy DNS host name')}
        {row('FULL RECORD NAME', fullName, 'full name', 'Copy full DNS record name')}
        {row('VALUE', value, 'value', 'Copy DNS TXT value')}
        <p className="text-xs text-soft">TTL: 300 seconds, or your provider's default.</p>
      </div>
      <p className="text-xs text-soft">If your provider appends the zone automatically, use Name / Host. If it expects the complete name, use Full record name. After saving, allow time for DNS to update, then verify. If you do not manage DNS, copy these instructions for your administrator and explore the dashboard while they complete setup.</p>
      <button type="button" disabled={!validZone} onClick={() => copy(instructions, 'instructions')} className="btn w-full justify-center min-h-[44px]">
        <Copy size={14} /> COPY INSTRUCTIONS FOR MY DNS ADMIN
      </button>
    </div>
  );
}
