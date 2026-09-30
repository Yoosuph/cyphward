import { useEffect, useState } from 'react';
import {
  Server,
  Search,
  Filter,
  Globe,
  Lock,
  ArrowUpRight,
  RefreshCw,
  Layers,
  ShieldAlert,
  Clock,
  CheckCircle2,
  AlertTriangle,
  X,
  Radio,
} from 'lucide-react';
import { getAssets, getAssetDetail } from '../lib/api';
import type { Asset, Finding } from '../types';
import { useToast } from '../components/Toast';
import { TableRowSkeleton, AssetDrawerSkeleton, AssetsSkeleton } from '../components/Skeleton';
import Drawer from '../components/Drawer';
import TopologyGraph from '../components/TopologyGraph';

export default function Assets() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [assetDetail, setAssetDetail] = useState<{ asset: Asset; findings: Finding[] } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'table' | 'topology'>('table');

  const toast = useToast();

  const loadAssets = async () => {
    setLoading(true);
    try {
      const res = await getAssets({
        search: search || undefined,
        asset_type: selectedType !== 'all' ? selectedType : undefined,
      });
      setAssets(res.assets);
    } catch (e) {
      toast('Failed to load assets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAssets();
  }, [selectedType]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadAssets();
  };

  const handleOpenDrawer = async (id: string) => {
    setSelectedAssetId(id);
    setDetailLoading(true);
    try {
      const res = await getAssetDetail(id);
      setAssetDetail(res);
    } catch (err) {
      toast('Failed to load asset details');
    } finally {
      setDetailLoading(false);
    }
  };

  const assetTypes = ['all', 'Web Endpoint', 'API Gateway', 'Mail Server', 'VPN Gateway'];

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 content-fade-in">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="live-dot" />
            <p className="eyebrow text-accent">ATTACK SURFACE INVENTORY</p>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-ink mt-1">
            External Assets & Endpoints
          </h1>
          <p className="text-xs mono text-soft mt-1">
            Passively discovered subdomains, IP bindings, network services, and active software footprints.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 sm:gap-3 w-full sm:w-auto">
          {/* View Mode Switcher */}
          <div className="flex items-center p-0.5 rounded border border-line bg-raised flex-1 sm:flex-none justify-center">
            <button
              onClick={() => setViewMode('table')}
              data-testid="view-mode-table"
              aria-label="Table Inventory view"
              className={`flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded text-xs mono transition-all btn-tactile ${
                viewMode === 'table'
                  ? 'bg-accent text-white font-medium shadow-sm shadow-accent/20'
                  : 'text-soft hover:text-ink'
              }`}
            >
              <Layers size={13} />
              <span className="hidden xs:inline">Table Inventory</span>
              <span className="xs:hidden">Table</span>
            </button>
            <button
              onClick={() => setViewMode('topology')}
              data-testid="view-mode-topology"
              aria-label="Topology Graph view"
              className={`flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded text-xs mono transition-all btn-tactile ${
                viewMode === 'topology'
                  ? 'bg-accent text-white font-medium shadow-sm shadow-accent/20'
                  : 'text-soft hover:text-ink'
              }`}
            >
              <Radio size={13} />
              <span className="hidden xs:inline">Topology Graph</span>
              <span className="xs:hidden">Topology</span>
            </button>
          </div>

          {viewMode === 'table' && (
            <button
              onClick={loadAssets}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs mono border border-line bg-raised hover:border-line-strong text-ink transition-colors btn-tactile ml-auto sm:ml-0"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
              <span>Refresh</span>
            </button>
          )}
        </div>
      </div>

      {viewMode === 'topology' ? (
        <div className="rounded-lg border border-line bg-raised overflow-hidden shadow-sm">
          <TopologyGraph />
        </div>
      ) : (
        <>
          {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row gap-3 items-center justify-between">
        <form onSubmit={handleSearchSubmit} className="relative w-full md:w-80">
          <Search size={14} className="absolute left-3 top-2.5 text-soft" />
          <input
            type="text"
            placeholder="Search hostname or IP..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 rounded bg-raised border border-line text-xs mono text-ink placeholder:text-soft focus:outline-none focus:border-accent"
          />
        </form>

        <div className="flex items-center gap-1.5 overflow-x-auto w-full md:w-auto pb-1 md:pb-0">
          <span className="text-xs mono text-soft mr-1 hidden sm:inline">Type:</span>
          {assetTypes.map(type => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              className={`px-2.5 py-1 rounded text-[11px] mono capitalize transition-all btn-tactile ${
                selectedType === type
                  ? 'bg-accent text-white font-medium shadow-sm shadow-accent/20'
                  : 'bg-raised border border-line text-soft hover:text-ink'
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Assets Inventory Table */}
      <div className="rounded-lg border border-line bg-raised overflow-hidden">
        <div className="overflow-x-auto w-full max-w-full">
          <table className="w-full text-left text-xs mono min-w-[760px]">
            <thead>
              <tr className="border-b border-line bg-inset/40 text-soft text-[11px]">
                <th className="py-3 px-4 font-medium">HOSTNAME & DOMAIN</th>
                <th className="py-3 px-4 font-medium">IP ADDRESS</th>
                <th className="py-3 px-4 font-medium">ASSET TYPE</th>
                <th className="py-3 px-4 font-medium">HTTP STATUS</th>
                <th className="py-3 px-4 font-medium">DETECTED TECH</th>
                <th className="py-3 px-4 font-medium">TLS / CIPHER</th>
                <th className="py-3 px-4 font-medium">RISKS</th>
                <th className="py-3 px-4 font-medium text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {loading ? (
                Array.from({ length: 7 }).map((_, i) => (
                  <TableRowSkeleton
                    key={i}
                    cols={[170, 110, 85, 45, 130, 105, 65, 24]}
                  />
                ))
              ) : assets.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-soft mono">
                    No assets found matching the selected filters.
                  </td>
                </tr>
              ) : (
                assets.map((asset, idx) => (
                  <tr
                    key={asset.id}
                    onClick={() => handleOpenDrawer(asset.id)}
                    className="hover:bg-inset/50 transition-colors cursor-pointer group stagger-row"
                    style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}
                  >
                    <td className="py-3 px-4 font-semibold text-ink">
                      <div className="flex items-center gap-2">
                        <Globe size={13} className="text-soft group-hover:text-accent transition-colors" />
                        <span>{asset.hostname}</span>
                      </div>
                      {asset.parent_domain && asset.parent_domain !== asset.hostname && (
                        <span className="text-[10px] text-soft font-normal block pl-5">
                          Zone: {asset.parent_domain}
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-soft font-mono">
                      {asset.ip_address || '—'}
                    </td>

                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded text-[10px] bg-inset border border-line text-soft">
                        {asset.asset_type}
                      </span>
                    </td>

                    <td className="py-3 px-4">
                      {asset.http_status ? (
                        <span
                          className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            asset.http_status >= 200 && asset.http_status < 300
                              ? 'bg-ok/10 text-ok border border-ok/30'
                              : asset.http_status >= 300 && asset.http_status < 400
                              ? 'bg-blue-500/10 text-blue-500 border border-blue-500/30'
                              : 'bg-accent-soft text-accent border border-accent/30'
                          }`}
                        >
                          {asset.http_status}
                        </span>
                      ) : (
                        <span className="text-soft text-[10px]">TCP Port</span>
                      )}
                    </td>

                    <td className="py-3 px-4">
                      <div className="flex flex-wrap gap-1 max-w-[180px]">
                        {(asset.technologies || []).slice(0, 3).map((tech, i) => (
                          <span
                            key={i}
                            className="px-1.5 py-0.5 rounded text-[9.5px] bg-inset border border-line text-ink"
                          >
                            {tech.name}
                          </span>
                        ))}
                        {(asset.technologies || []).length > 3 && (
                          <span className="text-[9px] text-soft">
                            +{asset.technologies!.length - 3}
                          </span>
                        )}
                        {(!asset.technologies || asset.technologies.length === 0) && (
                          <span className="text-soft text-[10px]">—</span>
                        )}
                      </div>
                    </td>

                    <td className="py-3 px-4">
                      {asset.tls_info?.valid ? (
                        <div className="flex items-center gap-1.5 text-ok text-[11px]">
                          <Lock size={11} />
                          <span>{asset.tls_info.protocol || 'TLS 1.3'}</span>
                          <span className="text-soft text-[10px]">
                            ({asset.tls_info.days_remaining}d)
                          </span>
                        </div>
                      ) : (
                        <span className="text-soft text-[10px]">Unencrypted / None</span>
                      )}
                    </td>

                    <td className="py-3 px-4">
                      {asset.critical_findings_count && asset.critical_findings_count > 0 ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-accent text-white">
                          {asset.critical_findings_count} CRIT
                        </span>
                      ) : asset.findings_count && asset.findings_count > 0 ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-500 border border-amber-500/30">
                          {asset.findings_count} Risks
                        </span>
                      ) : (
                        <span className="text-ok text-[11px] flex items-center gap-1">
                          <CheckCircle2 size={11} /> Clean
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-4 text-right">
                      <button
                        onClick={e => {
                          e.stopPropagation();
                          handleOpenDrawer(asset.id);
                        }}
                        className="p-1 rounded hover:bg-inset text-soft hover:text-ink transition-colors"
                      >
                        <ArrowUpRight size={14} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
        </>
      )}

      {/* Asset Detail Drawer */}
      <Drawer
        open={!!selectedAssetId}
        onClose={() => setSelectedAssetId(null)}
        size="xl"
        eyebrow="ATTACK SURFACE"
        title="ASSET TELEMETRY PROFILE"
        icon={<Server size={16} />}
      >
        {detailLoading || !assetDetail ? (
          <AssetDrawerSkeleton />
        ) : (
          <div className="space-y-6 pt-2 text-xs content-fade-in">
            {/* Host Identity Card */}
            <div className="p-4 rounded-lg bg-inset/50 border border-line space-y-3">
              <div className="flex items-center justify-between">
                <span className="mono text-xs font-bold text-ink">{assetDetail.asset.hostname}</span>
                <span className="px-2 py-0.5 rounded text-[10px] mono bg-ok/10 text-ok border border-ok/30">
                  {assetDetail.asset.status.toUpperCase()}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-soft mono text-[11px]">
                <div>IP: <span className="text-ink font-semibold">{assetDetail.asset.ip_address || '—'}</span></div>
                <div>Type: <span className="text-ink">{assetDetail.asset.asset_type}</span></div>
                <div>HTTP Status: <span className="text-ink font-semibold">{assetDetail.asset.http_status || '—'}</span></div>
                <div>Zone: <span className="text-ink">{assetDetail.asset.parent_domain || '—'}</span></div>
              </div>
            </div>

            {/* Technology Footprint */}
            <div className="space-y-2">
              <h4 className="mono text-[11px] font-semibold text-soft uppercase tracking-wider">
                Discovered Technologies
              </h4>
              <div className="grid grid-cols-2 gap-2">
                {(assetDetail.asset.technologies || []).map((t, idx) => (
                  <div key={idx} className="p-2.5 rounded bg-inset border border-line flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-ink">{t.name}</div>
                      <div className="text-[10px] text-soft">{t.category || 'Component'}</div>
                    </div>
                    {t.version && (
                      <span className="mono text-[10px] px-1.5 py-0.5 rounded bg-raised border border-line text-soft">
                        v{t.version}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* TLS & Cryptography */}
            {assetDetail.asset.tls_info && (
              <div className="space-y-2">
                <h4 className="mono text-[11px] font-semibold text-soft uppercase tracking-wider">
                  SSL/TLS Certificate State
                </h4>
                <div className="p-3 rounded bg-inset border border-line space-y-2 mono text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-soft">Protocol:</span>
                    <span className="text-ink font-semibold">{assetDetail.asset.tls_info.protocol || 'TLS 1.3'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-soft">Issuer:</span>
                    <span className="text-ink">{assetDetail.asset.tls_info.issuer || "Let's Encrypt"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-soft">Days Remaining:</span>
                    <span className={assetDetail.asset.tls_info.days_remaining! < 30 ? 'text-accent font-bold' : 'text-ok font-semibold'}>
                      {assetDetail.asset.tls_info.days_remaining} Days
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-soft">Cipher:</span>
                    <span className="text-ink truncate max-w-[220px]">{assetDetail.asset.tls_info.cipher || 'AES-256-GCM'}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Associated Findings */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="mono text-[11px] font-semibold text-soft uppercase tracking-wider">
                  Associated Security Findings ({assetDetail.findings.length})
                </h4>
              </div>

              {assetDetail.findings.length === 0 ? (
                <div className="p-4 rounded bg-inset/40 border border-line text-center text-soft mono text-xs">
                  No security vulnerabilities or misconfigurations discovered on this asset.
                </div>
              ) : (
                <div className="space-y-2">
                  {assetDetail.findings.map(f => (
                    <div
                      key={f.id}
                      className="p-3 rounded bg-inset border border-line space-y-1 hover:border-line-strong transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-ink">{f.title}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[9.5px] uppercase font-bold ${
                            f.severity === 'critical'
                              ? 'bg-accent text-white'
                              : f.severity === 'high'
                              ? 'bg-amber-600 text-white'
                              : 'bg-amber-400 text-black'
                          }`}
                        >
                          {f.severity}
                        </span>
                      </div>
                      <p className="text-soft text-[11.5px] leading-relaxed line-clamp-2">
                        {f.description}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
