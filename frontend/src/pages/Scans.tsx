import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Clock,
  Code,
  Globe,
  Layers,
  Lock,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { getScans, getScanDetail, launchScan, getDomains } from "../lib/api";
import type { Scan, Domain, StageInfo } from "../types";
import { useToast } from "../components/Toast";
import { useAuth } from "../lib/auth";
import { Skeleton, ScanDrawerSkeleton } from "../components/Skeleton";
import Modal from "../components/Modal";
import Drawer from "../components/Drawer";
import "./Scans.css";

type Observation = { stage: string; raw_data: any };
type Detail = { scan: Scan; raw_results: Observation[] };
const CHECKS = [
  {
    key: "discovery",
    label: "Asset discovery",
    desc: "Public records and subdomains",
    icon: Search,
  },
  {
    key: "dns",
    label: "DNS records",
    desc: "A, MX, TXT, SPF and DMARC records",
    icon: Globe,
  },
  {
    key: "http",
    label: "Website checks",
    desc: "Responses, headers and public pages",
    icon: Server,
  },
  {
    key: "ports",
    label: "Open ports",
    desc: "Top 100 TCP ports",
    icon: Layers,
  },
  {
    key: "tls",
    label: "TLS certificates",
    desc: "Certificates and encryption protocols",
    icon: Lock,
  },
  {
    key: "nuclei",
    label: "Known vulnerabilities",
    desc: "Checks for known security issues",
    icon: ShieldAlert,
  },
  {
    key: "security_checks",
    label: "Security checks",
    desc: "Headers, email policies and certificates",
    icon: ShieldCheck,
  },
] as const;
const PROCESSING = [
  {
    key: "normalization",
    label: "Organize results",
    desc: "Group and normalize observations",
    icon: Layers,
  },
  {
    key: "scoring",
    label: "Security score",
    desc: "Score based on known organization findings",
    icon: ShieldCheck,
  },
  {
    key: "ai_analysis",
    label: "AI summary",
    desc: "Plain-language explanations",
    icon: Sparkles,
  },
] as const;
type Stage = (typeof CHECKS)[number] | (typeof PROCESSING)[number];
const progress = (scan: Scan, key: string): StageInfo | undefined =>
  (scan.stage_progress as unknown as Record<string, StageInfo>)?.[key];
const finished = (scan: Scan) =>
  ["completed", "failed", "cancelled"].includes(scan.status);
const incomplete = (scan: Scan) =>
  CHECKS.filter((check) =>
    ["failed", "skipped"].includes(progress(scan, check.key)?.status || ""),
  );
function coverageLabel(scan: Scan) {
  if (incomplete(scan).length) return "Limited coverage";
  if (
    scan.status === "completed" &&
    CHECKS.some((check) => progress(scan, check.key)?.status !== "completed")
  )
    return "Coverage unavailable";
  return null;
}
function duration(ms?: number) {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return "<1 sec";
  if (ms < 60000) return `${Math.round(ms / 1000)} sec`;
  return `${Math.floor(ms / 60000)} min${ms % 60000 >= 1000 ? ` ${Math.floor((ms % 60000) / 1000)} sec` : ""}`;
}
function date(value: string) {
  return new Date(value).toLocaleString([], {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
function scanDuration(scan: Scan) {
  if (!scan.started_at || !scan.completed_at) return null;
  const elapsed =
    new Date(scan.completed_at).getTime() - new Date(scan.started_at).getTime();
  return elapsed >= 0 ? duration(elapsed) : null;
}
function StatusBadge({
  label,
  tone = "neutral",
}: {
  label: string;
  tone?: string;
}) {
  const Icon =
    tone === "success"
      ? CheckCircle2
      : ["warning", "danger"].includes(tone)
        ? AlertCircle
        : Clock;
  return (
    <span className={`scan-badge scan-badge--${tone}`}>
      <Icon size={13} aria-hidden="true" />
      {label}
    </span>
  );
}
function ScanStatus({ scan }: { scan: Scan }) {
  const quality = coverageLabel(scan);
  if (scan.status === "completed" && quality)
    return (
      <StatusBadge
        label={quality}
        tone={quality === "Limited coverage" ? "warning" : "neutral"}
      />
    );
  const label = {
    completed: "Completed",
    running: "Running",
    queued: "Queued",
    failed: "Failed",
    cancelled: "Cancelled",
  }[scan.status];
  return (
    <StatusBadge
      label={label}
      tone={
        scan.status === "completed"
          ? "success"
          : scan.status === "failed"
            ? "danger"
            : scan.status === "running"
              ? "warning"
              : "neutral"
      }
    />
  );
}
function CheckRow({
  scan,
  stage,
  observations,
}: {
  scan: Scan;
  stage: Stage;
  observations: Observation[];
}) {
  const info = progress(scan, stage.key);
  const state = info?.status;
  const label =
    state === "completed"
      ? "Done"
      : state === "failed"
        ? "Failed"
        : state === "skipped"
          ? "Skipped"
          : state === "running"
            ? "Running"
            : !info && finished(scan)
              ? "Not recorded"
              : "Pending";
  const raw = observations.find(
    (result) => result.stage === stage.key,
  )?.raw_data;
  const coverage =
    Array.isArray(raw?.successful_hosts) && Array.isArray(raw?.attempted_hosts)
      ? `${raw.successful_hosts.length} of ${raw.attempted_hosts.length} targets checked`
      : null;
  const Icon = stage.icon;
  return (
    <details className="scan-check" data-stage={stage.key}>
      <summary>
        <Icon size={17} className="scan-check-icon" aria-hidden="true" />
        <span className="scan-check-label">
          {stage.label}
          {coverage && <small>{coverage}</small>}
        </span>
        <StatusBadge
          label={label}
          tone={
            state === "completed"
              ? "success"
              : state === "failed" || state === "skipped"
                ? "warning"
                : "neutral"
          }
        />
        <span className="scan-check-time">{duration(info?.duration_ms)}</span>
        <ChevronRight size={15} className="scan-chevron" aria-hidden="true" />
      </summary>
      <div className="scan-check-detail">
        <p>{stage.desc}</p>
        {info?.items != null && (
          <p>
            {info.items} observations recorded · {duration(info.duration_ms)}
          </p>
        )}
        {info?.error && <p className="scan-check-error">{info.error}</p>}
        {raw?.failed_hosts && Object.keys(raw.failed_hosts).length > 0 && (
          <ul>
            {Object.entries(raw.failed_hosts).map(([host, reason]) => (
              <li key={host}>
                <strong>{host}</strong>: {String(reason)}
              </li>
            ))}
          </ul>
        )}
        {!info && <p>No check result recorded for this scan.</p>}
      </div>
    </details>
  );
}
function CheckList({
  scan,
  observations,
}: {
  scan: Scan;
  observations: Observation[];
}) {
  const processing = PROCESSING.map((stage) => progress(scan, stage.key));
  const processLabel = processing.some((info) => info?.status === "failed")
    ? "Needs attention"
    : processing.every((info) => info?.status === "completed")
      ? "Completed"
      : processing.some((info) => info?.status === "running")
        ? "Running"
        : finished(scan)
          ? "Not completed"
          : "Pending";
  return (
    <>
      <div className="scan-check-list">
        {CHECKS.map((stage) => (
          <CheckRow
            key={`${scan.id}-${stage.key}`}
            scan={scan}
            stage={stage}
            observations={observations}
          />
        ))}
      </div>
      <details className="scan-processing" key={`${scan.id}-processing`}>
        <summary>
          <Layers size={17} aria-hidden="true" />
          <span>
            Result processing
            <small>Organizing results, scoring and AI summary</small>
          </span>
          <StatusBadge
            label={processLabel}
            tone={
              processLabel === "Completed"
                ? "success"
                : processLabel === "Needs attention"
                  ? "warning"
                  : "neutral"
            }
          />
          <ChevronRight size={15} className="scan-chevron" aria-hidden="true" />
        </summary>
        {PROCESSING.map((stage) => (
          <CheckRow
            key={stage.key}
            scan={scan}
            stage={stage}
            observations={observations}
          />
        ))}
      </details>
      <details className="scan-evidence" key={`${scan.id}-evidence`}>
        <summary>
          <Code size={17} aria-hidden="true" />
          <span>
            Technical evidence
            <small>Recorded observations and scan identity</small>
          </span>
          <ChevronRight size={15} className="scan-chevron" aria-hidden="true" />
        </summary>
        <div className="scan-check-detail">
          <p className="mono">Scan ID: {scan.id}</p>
          <p>{observations.length} stage records available.</p>
        </div>
        {observations.length ? (
          <pre tabIndex={0} aria-label="Raw scan observations">
            {JSON.stringify(observations, null, 2)}
          </pre>
        ) : (
          <p className="scan-check-detail">No raw observations available.</p>
        )}
      </details>
    </>
  );
}
function ScanSummary({
  scan,
  observations,
  onCoverage,
  onDetails,
  onFindings,
  selected = false,
}: {
  scan: Scan;
  observations: Observation[];
  onCoverage: () => void;
  onDetails?: () => void;
  onFindings: () => void;
  selected?: boolean;
}) {
  const missing = incomplete(scan);
  const quality = coverageLabel(scan);
  const discovery = observations.find(
    (result) => result.stage === "discovery",
  )?.raw_data;
  const hosts = Array.isArray(discovery)
    ? discovery.length
    : progress(scan, "discovery")?.items;
  const elapsed = scanDuration(scan);
  const score =
    scan.score != null && Number.isFinite(scan.score) ? scan.score : null;
  const orgScore = progress(scan, "scoring")?.scope === "organization";
  return (
    <>
      <div className="scan-summary-heading">
        <div>
          <p className="scan-section-label">
            {selected ? "Selected scan" : "Latest scan"}
          </p>
          <h2>{scan.domain || "Domain unavailable"}</h2>
          <p className="scan-meta">
            {date(scan.started_at || scan.created_at)}
            {elapsed && ` · Finished in ${elapsed}`}
          </p>
        </div>
        <div className="scan-summary-status">
          {scan.status === "completed" && quality && (
            <span className="scan-lifecycle">Scan completed</span>
          )}
          <ScanStatus scan={scan} />
        </div>
      </div>
      <div className="scan-metrics">
        <div>
          <span>Findings recorded</span>
          <strong>{scan.findings_discovered ?? "—"}</strong>
        </div>
        <div>
          <span>Hosts discovered</span>
          <strong>{hosts ?? "—"}</strong>
        </div>
        <div className="scan-score">
          <span>
            {orgScore
              ? "Organization score at completion"
              : "Legacy scan score"}
          </span>
          <strong>
            {score != null ? (
              <>
                {score}
                <small> / 100</small>
              </>
            ) : (
              "Not assessed"
            )}
          </strong>
          <small>
            {score != null
              ? "Based on known findings"
              : "A score is available after assessment."}
          </small>
        </div>
      </div>
      {quality && (
        <div className="scan-coverage-notice" role="status">
          <AlertCircle size={21} aria-hidden="true" />
          <div>
            <strong>
              {quality === "Limited coverage"
                ? scan.status === "completed"
                  ? "Completed with limited coverage"
                  : "Some checks were not completed"
                : "Coverage is unavailable"}
            </strong>
            <p>
              {missing.length
                ? `${missing.map((stage) => stage.label).join(", ")}: ${missing.length === 1 ? "this check was" : "these checks were"} not fully completed. Completed checks remain available.`
                : "This scan does not have a complete check record. Review the available evidence."}
            </p>
            <p className="scan-coverage-note">
              An incomplete check does not prove a system is secure.
            </p>
          </div>
          <button
            className="scan-button scan-button--outline"
            onClick={onCoverage}
          >
            Review coverage
          </button>
        </div>
      )}
      {scan.error_message && (
        <p className="scan-check-error">{scan.error_message}</p>
      )}
      <div className="scan-summary-actions">
        <button
          className="scan-button scan-button--primary"
          onClick={onFindings}
        >
          View findings
          <ArrowRight size={15} aria-hidden="true" />
        </button>
        {onDetails && (
          <button className="scan-button" onClick={onDetails}>
            View scan details
          </button>
        )}
        <span className="scan-scope-note">
          Findings opens the workspace issue list.
        </span>
      </div>
    </>
  );
}

export default function Scans() {
  const { organization } = useAuth();
  const orgId = organization?.id;
  const toast = useToast();
  const navigate = useNavigate();
  const canManageScans = ["owner", "admin"].includes(
    organization?.membership_role || "member",
  );
  const [scans, setScans] = useState<Scan[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [domainsLoading, setDomainsLoading] = useState(true);
  const [domainId, setDomainId] = useState("");
  const [launchOpen, setLaunchOpen] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [domainFilter, setDomainFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [checksOpen, setChecksOpen] = useState(
    () => window.matchMedia("(min-width: 901px)").matches,
  );
  const workspace = useRef(orgId);
  workspace.current = orgId;
  const listRequest = useRef(0);
  const detailRequest = useRef(0);
  const coverageRef = useRef<HTMLDetailsElement>(null);
  const listRef = useRef<Scan[]>([]);
  useEffect(() => {
    if (!drawerOpen && !launchOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const selector = launchOpen ? ".modal-backdrop" : ".drawer.open";
    const focusable = () => {
      const root = document.querySelector<HTMLElement>(selector);
      return root
        ? [
            ...root.querySelectorAll<HTMLElement>(
              'button:not([disabled]), select:not([disabled]), a[href], summary, [tabindex="0"]',
            ),
          ].filter((element) => element.getClientRects().length > 0)
        : [];
    };
    const focusDialog = () => {
      document
        .querySelector(selector)
        ?.setAttribute(
          "aria-label",
          launchOpen ? "Start security scan" : "Scan details",
        );
      const first = focusable()[0];
      first?.focus();
      return !!first;
    };
    const observer = new MutationObserver(() => {
      if (focusDialog()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const frame = requestAnimationFrame(() => {
      if (focusDialog()) observer.disconnect();
    });
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0],
        last = items[items.length - 1];
      const root = document.querySelector(selector);
      if (
        !root?.contains(document.activeElement) ||
        (event.shiftKey
          ? document.activeElement === first
          : document.activeElement === last)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("keydown", trap);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [drawerOpen, launchOpen]);
  const loadScans = useCallback(async () => {
    if (workspace.current !== orgId) return;
    const request = ++listRequest.current;
    setLoading(true);
    try {
      const result = await getScans();
      if (request !== listRequest.current || workspace.current !== orgId)
        return;
      listRef.current = result;
      setScans(result);
      setListError(false);
      setSelectedId((current) =>
        result.some((scan) => scan.id === current)
          ? current
          : result[0]?.id || null,
      );
    } catch {
      if (request === listRequest.current) setListError(true);
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [orgId]);
  const loadDetail = useCallback(
    async (id: string) => {
      if (workspace.current !== orgId) return;
      const request = ++detailRequest.current;
      setDetailLoading(true);
      try {
        const result = await getScanDetail(id);
        if (request !== detailRequest.current || workspace.current !== orgId)
          return;
        setDetail(result);
        setDetailError(false);
      } catch {
        if (request === detailRequest.current) setDetailError(true);
      } finally {
        if (request === detailRequest.current) setDetailLoading(false);
      }
    },
    [orgId],
  );
  useEffect(() => {
    const media = window.matchMedia("(min-width: 901px)");
    const update = () => setChecksOpen(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    let current = true;
    listRef.current = [];
    setScans([]);
    setDetail(null);
    setSelectedId(null);
    setListError(false);
    setDetailError(false);
    setDomains([]);
    setDomainId("");
    setDomainsLoading(true);
    setDrawerOpen(false);
    setLaunchOpen(false);
    setDomainFilter("all");
    setStatusFilter("all");
    void loadScans();
    void getDomains()
      .then((result) => {
        if (!current) return;
        const verified = result.filter(
          (domain) => domain.verification_status === "verified",
        );
        setDomains(verified);
        setDomainId(verified[0]?.id || "");
      })
      .finally(() => {
        if (current) setDomainsLoading(false);
      });
    return () => {
      current = false;
      listRequest.current++;
      detailRequest.current++;
    };
  }, [orgId, loadScans]);
  useEffect(() => {
    if (selectedId) {
      setDetailError(false);
      void loadDetail(selectedId);
    }
    return () => {
      detailRequest.current++;
    };
  }, [selectedId, loadDetail]);
  const shouldPoll =
    scans.some((scan) => !finished(scan)) ||
    (detail?.scan.id === selectedId &&
      detail != null &&
      !finished(detail.scan));
  useEffect(() => {
    if (!shouldPoll) return;
    let polling = false;
    const timer = setInterval(() => {
      if (polling) return;
      polling = true;
      void Promise.all([
        loadScans(),
        selectedId ? loadDetail(selectedId) : Promise.resolve(),
      ]).finally(() => {
        polling = false;
      });
    }, 3000);
    return () => clearInterval(timer);
  }, [shouldPoll, selectedId, loadScans, loadDetail]);
  const activeScan =
    detail?.scan.id === selectedId
      ? detail.scan
      : scans.find((scan) => scan.id === selectedId) || scans[0];
  const observations =
    detail && detail.scan.id === activeScan?.id ? detail.raw_results : [];
  const openDetails = (id: string) => {
    setSelectedId(id);
    setDrawerOpen(true);
  };
  const reviewCoverage = () => {
    if (!coverageRef.current) return;
    coverageRef.current.open = true;
    const failed = coverageRef.current.querySelector<HTMLDetailsElement>(
      '[data-stage="' +
        ((activeScan && incomplete(activeScan)[0]?.key) || "nuclei") +
        '"]',
    );
    if (failed) failed.open = true;
    coverageRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    coverageRef.current
      .querySelector<HTMLElement>("summary")
      ?.focus({ preventScroll: true });
  };
  const handleLaunch = async () => {
    if (!canManageScans || !domainId || launching) return;
    setLaunching(true);
    setLaunchError("");
    try {
      const result = await launchScan(domainId);
      if (workspace.current !== orgId) return;
      toast(`Scan started for ${result.domain}.`);
      setLaunchOpen(false);
      await loadScans();
      if (
        result.scan?.id &&
        listRef.current.some((scan) => scan.id === result.scan.id)
      )
        setSelectedId(result.scan.id);
    } catch (error: any) {
      setLaunchError(
        error.message || "Failed to start scan. Please try again.",
      );
    } finally {
      setLaunching(false);
    }
  };
  const launchButton = canManageScans && (
    <button
      className="scan-button scan-button--primary scan-start"
      disabled={domainsLoading}
      aria-label={domains.length ? "Start scan" : "Verify domain"}
      onClick={() => {
        setLaunchError("");
        domains.length ? setLaunchOpen(true) : navigate("/domains");
      }}
    >
      <Plus size={18} aria-hidden="true" />
      {domainsLoading
        ? "Loading domains…"
        : domains.length
          ? "Start scan"
          : "Verify domain"}
    </button>
  );
  const filteredScans = scans.filter(
    (scan) =>
      (domainFilter === "all" || scan.domain === domainFilter) &&
      (statusFilter === "all" ||
        (statusFilter === "limited"
          ? coverageLabel(scan) === "Limited coverage"
          : scan.status === statusFilter)),
  );
  const completeChecks = activeScan
    ? CHECKS.filter(
        (stage) => progress(activeScan, stage.key)?.status === "completed",
      ).length
    : 0;
  const ai = observations.find(
    (result) => result.stage === "ai_analysis",
  )?.raw_data;
  return (
    <div className="scans-page content-fade-in">
      <header className="scans-heading">
        <div>
          <h1>Scans</h1>
          <p>Monitor your domains and review security checks.</p>
        </div>
        <div className="scans-heading-actions">
          <button
            className="scan-button scan-refresh"
            aria-label="Refresh scans"
            onClick={() => {
              void loadScans();
              if (selectedId) void loadDetail(selectedId);
            }}
          >
            <RefreshCw
              size={17}
              className={loading || detailLoading ? "animate-spin" : ""}
              aria-hidden="true"
            />
            <span>Refresh</span>
          </button>
          {launchButton}
        </div>
      </header>
      {listError && (
        <div role="alert" className="scan-load-notice">
          <AlertCircle size={18} />
          <span>
            {scans.length
              ? "Refresh failed. Showing the last available scans."
              : "Scans could not be loaded. Please try again."}
          </span>
          <button className="scan-button" onClick={() => void loadScans()}>
            Retry
          </button>
        </div>
      )}
      {loading && !scans.length ? (
        <div
          className="scan-panel scan-loading"
          role="status"
          aria-label="Loading scans"
        >
          <Skeleton height={24} width="35%" />
          <Skeleton height={70} />
          <Skeleton height={100} />
        </div>
      ) : !activeScan ? (
        !listError && (
          <section className="scan-panel scan-empty">
            <Radar size={36} aria-hidden="true" />
            <h2>Your first scan starts here</h2>
            <p>
              {canManageScans
                ? domains.length
                  ? "Scan a verified domain to discover assets and review security findings."
                  : "Verify a domain before running your first security scan."
                : "An owner or administrator can start a scan for a verified domain."}
            </p>
            {launchButton}
          </section>
        )
      ) : (
        <>
          <section
            className="scan-panel scan-summary"
            aria-label="Scan summary"
          >
            <ScanSummary
              scan={activeScan}
              observations={observations}
              selected={activeScan.id !== scans[0]?.id}
              onCoverage={reviewCoverage}
              onDetails={() => openDetails(activeScan.id)}
              onFindings={() => navigate("/findings")}
            />
            {activeScan.id !== scans[0]?.id && (
              <button
                className="scan-link"
                onClick={() => setSelectedId(scans[0].id)}
              >
                Back to latest scan
                <ArrowRight size={14} />
              </button>
            )}
            {detailError && (
              <div className="scan-load-notice" role="alert">
                <span>
                  Scan details could not be refreshed. Available results are
                  shown.
                </span>
                <button
                  className="scan-button"
                  onClick={() => void loadDetail(activeScan.id)}
                >
                  Retry details
                </button>
              </div>
            )}
          </section>
          <div className="scans-workspace">
            <details
              className="scan-panel scan-checks-panel"
              ref={coverageRef}
              open={checksOpen}
              onToggle={(event) => setChecksOpen(event.currentTarget.open)}
            >
              <summary className="scan-panel-heading">
                <span>
                  <h2>Scan checks</h2>
                  <small>
                    {completeChecks} of {CHECKS.length} checks completed
                  </small>
                </span>
                <ChevronRight size={18} className="scan-chevron" />
              </summary>
              <div className="scan-checks-body">
                <CheckList scan={activeScan} observations={observations} />
              </div>
            </details>
            <section
              className="scan-panel scan-history"
              aria-label="Scan history"
            >
              <div className="scan-history-heading">
                <div>
                  <h2>Scan history</h2>
                  <small>
                    {filteredScans.length} of {scans.length} scans
                  </small>
                </div>
                <div className="scan-filters">
                  <select
                    aria-label="Filter scans by domain"
                    value={domainFilter}
                    onChange={(event) => setDomainFilter(event.target.value)}
                  >
                    <option value="all">All domains</option>
                    {[
                      ...new Set(
                        scans.map((scan) => scan.domain).filter(Boolean),
                      ),
                    ].map((domain) => (
                      <option key={domain} value={domain}>
                        {domain}
                      </option>
                    ))}
                  </select>
                  <select
                    aria-label="Filter scans by status"
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                  >
                    <option value="all">All statuses</option>
                    <option value="limited">Limited coverage</option>
                    {[
                      "completed",
                      "running",
                      "queued",
                      "failed",
                      "cancelled",
                    ].map((status) => (
                      <option key={status} value={status}>
                        {status[0].toUpperCase() + status.slice(1)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {!filteredScans.length ? (
                <p className="scan-history-empty">
                  No scans match these filters.
                </p>
              ) : (
                <>
                  <div
                    className="scan-history-desktop"
                    tabIndex={0}
                    role="region"
                    aria-label="Scan history entries"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>Domain / date</th>
                          <th>Status</th>
                          <th>Score</th>
                          <th>
                            <span className="sr-only">Action</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredScans.map((scan) => (
                          <tr
                            key={scan.id}
                            className={
                              scan.id === activeScan.id
                                ? "scan-history-selected"
                                : ""
                            }
                          >
                            <td>
                              <strong>{scan.domain || "Unknown domain"}</strong>
                              <small>{date(scan.created_at)}</small>
                            </td>
                            <td>
                              <ScanStatus scan={scan} />
                            </td>
                            <td className="scan-history-score">
                              {scan.score != null ? scan.score : "—"}
                              {scan.score != null && (
                                <small>
                                  {progress(scan, "scoring")?.scope ===
                                  "organization"
                                    ? "Organization at scan completion"
                                    : "Legacy scan score"}
                                </small>
                              )}
                            </td>
                            <td>
                              <button
                                className="scan-button scan-button--outline"
                                aria-label={`View scan ${scan.id}`}
                                onClick={() => openDetails(scan.id)}
                              >
                                View
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div
                    className="scan-history-mobile"
                    tabIndex={0}
                    role="region"
                    aria-label="Scan history entries"
                  >
                    {filteredScans.map((scan) => (
                      <article
                        className={`scan-history-card ${scan.id === activeScan.id ? "scan-history-selected" : ""}`}
                        key={scan.id}
                      >
                        <div>
                          <strong>{scan.domain || "Unknown domain"}</strong>
                          <ScanStatus scan={scan} />
                        </div>
                        <p className="scan-meta">{date(scan.created_at)}</p>
                        <div className="scan-history-card-footer">
                          <span>
                            <small>
                              {progress(scan, "scoring")?.scope ===
                              "organization"
                                ? "Organization at scan completion"
                                : "Legacy scan score"}
                            </small>
                            <strong>
                              {scan.score != null
                                ? `${scan.score} / 100`
                                : "Not assessed"}
                            </strong>
                          </span>
                          <button
                            className="scan-button scan-button--outline"
                            aria-label={`View scan ${scan.id}`}
                            onClick={() => openDetails(scan.id)}
                          >
                            View
                            <ChevronRight size={15} aria-hidden="true" />
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                </>
              )}
            </section>
          </div>
        </>
      )}
      {drawerOpen && (
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          size="2xl"
          eyebrow="SCAN DETAILS"
          title={activeScan?.domain || "Scan details"}
          icon={<Radar size={17} />}
        >
          {!activeScan ||
          (detailLoading && detail?.scan.id !== activeScan.id) ? (
            <ScanDrawerSkeleton />
          ) : (
            <div className="scans-page scan-detail-content">
              <ScanSummary
                scan={activeScan}
                observations={observations}
                selected
                onCoverage={() => {
                  setDrawerOpen(false);
                  requestAnimationFrame(reviewCoverage);
                }}
                onFindings={() => navigate("/findings")}
              />
              {detailError && (
                <div role="alert" className="scan-load-notice">
                  Details could not be loaded.
                  <button
                    className="scan-button"
                    onClick={() => void loadDetail(activeScan.id)}
                  >
                    Retry details
                  </button>
                </div>
              )}
              <section aria-label="Detailed scan checks">
                <h2>Scan checks</h2>
                <CheckList scan={activeScan} observations={observations} />
              </section>
              {ai?.executive_summary?.board_summary && (
                <section className="scan-ai">
                  <h2>
                    <Sparkles size={17} />
                    AI summary
                  </h2>
                  <p>{ai.executive_summary.board_summary}</p>
                  {ai.executive_summary.critical_action_items?.length > 0 && (
                    <ul>
                      {ai.executive_summary.critical_action_items.map(
                        (item: any, index: number) => (
                          <li key={index}>
                            <strong>{item.priority}: </strong>
                            {item.title}
                          </li>
                        ),
                      )}
                    </ul>
                  )}
                </section>
              )}
            </div>
          )}
        </Drawer>
      )}
      <Modal
        open={launchOpen}
        onClose={() => {
          if (!launching) setLaunchOpen(false);
        }}
        title="Start security scan"
        icon={<Radar size={18} />}
        maxWidth="max-w-md"
      >
        <div className="scans-page scan-launch">
          <p>
            Choose a verified domain. We’ll check its public assets and security
            settings, then summarize the results.
          </p>
          <label htmlFor="scan-domain">Domain to scan</label>
          <select
            id="scan-domain"
            value={domainId}
            onChange={(event) => setDomainId(event.target.value)}
          >
            {domains.map((domain) => (
              <option key={domain.id} value={domain.id}>
                {domain.domain}
              </option>
            ))}
          </select>
          <p className="scan-launch-note">
            <Lock size={16} />
            Only verified domains can be scanned. This uses one scan from your
            workspace allowance.
          </p>
          {launchError && (
            <p className="scan-check-error" role="alert">
              {launchError}
            </p>
          )}
          <div className="scan-launch-actions">
            <button
              className="scan-button"
              disabled={launching}
              onClick={() => setLaunchOpen(false)}
            >
              Cancel
            </button>
            <button
              className="scan-button scan-button--primary"
              disabled={launching || !domainId}
              onClick={handleLaunch}
            >
              {launching ? (
                <RefreshCw size={16} className="animate-spin" />
              ) : (
                <Plus size={17} />
              )}
              {launching ? "Starting…" : "Start scan"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
