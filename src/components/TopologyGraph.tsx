import { useEffect, useRef, useState } from 'react';
import {
  ZoomIn, ZoomOut, RotateCcw, Play, Pause, ShieldAlert,
  ShieldCheck, Radio, Server, Activity, ArrowRight, Zap, X
} from 'lucide-react';
import { useToast } from './Toast';

export interface TopologyNode {
  id: string;
  label: string;
  type: 'workstation' | 'gateway' | 'switch' | 'cloud' | 'threat' | 'router';
  ip: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx: number | null;
  fy: number | null;
  status: 'hot' | 'warn' | 'ok';
  role: string;
  traffic: string;
  connections: number;
  radius: number;
}

export interface TopologyLink {
  source: string;
  target: string;
  alert?: boolean;
  speed: string;
}

interface Packet {
  sourceId: string;
  targetId: string;
  progress: number;
  speed: number;
  alert?: boolean;
}

const INITIAL_NODES: TopologyNode[] = [
  {
    id: 'kano-03',
    label: 'kano-03.workstation',
    type: 'workstation',
    ip: '192.168.4.103',
    x: 180,
    y: 160,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'hot',
    role: 'Trade Desk Workstation (Compromised via T1566 Phishing)',
    traffic: '14.2 MB/s',
    connections: 2,
    radius: 12,
  },
  {
    id: '185.220.x.x',
    label: '185.220.101.5 [C2]',
    type: 'threat',
    ip: '185.220.101.5',
    x: 80,
    y: 90,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'hot',
    role: 'Hostile Tor Exit Node / Active C2 Command Channel',
    traffic: '8.4 KB/s',
    connections: 1,
    radius: 13,
  },
  {
    id: 'kano-01',
    label: 'kano-01.teller',
    type: 'workstation',
    ip: '192.168.4.101',
    x: 220,
    y: 270,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Kano Main Cash Office Teller Terminal',
    traffic: '1.2 MB/s',
    connections: 1,
    radius: 9,
  },
  {
    id: 'kano-02',
    label: 'kano-02.atm-ctrl',
    type: 'workstation',
    ip: '192.168.4.102',
    x: 140,
    y: 330,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Branch ATM Cash Dispenser Controller',
    traffic: '420 KB/s',
    connections: 1,
    radius: 9,
  },
  {
    id: 'core-router',
    label: 'core-router.kano-edge',
    type: 'router',
    ip: '10.200.0.1',
    x: 380,
    y: 220,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Kano Edge SD-WAN Aggregation Core Gateway',
    traffic: '148.6 MB/s',
    connections: 7,
    radius: 16,
  },
  {
    id: 'ussd-gw-2',
    label: 'ussd-gw-02.switch',
    type: 'gateway',
    ip: '10.200.12.4',
    x: 320,
    y: 370,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'warn',
    role: 'Telco VAS USSD Gateway (*901# PIN Enumeration Alert)',
    traffic: '22.8 MB/s',
    connections: 2,
    radius: 13,
  },
  {
    id: 'nibss-switch',
    label: 'nibss-instant.gw',
    type: 'switch',
    ip: '10.140.2.1',
    x: 520,
    y: 340,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'NIBSS Direct Instant Payment Clearance Rail',
    traffic: '84.2 MB/s',
    connections: 2,
    radius: 14,
  },
  {
    id: 'paystack-api',
    label: 'paystack-webhook.int',
    type: 'gateway',
    ip: '10.140.8.12',
    x: 560,
    y: 240,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Merchant Settlement API Webhook Ingestion',
    traffic: '32.1 MB/s',
    connections: 1,
    radius: 10,
  },
  {
    id: 'siem',
    label: 'siem-cluster.enclave',
    type: 'cloud',
    ip: '10.250.1.5',
    x: 540,
    y: 110,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Cyphward L5 Detection & Forensic SIEM Enclave',
    traffic: '64.5 MB/s',
    connections: 2,
    radius: 15,
  },
  {
    id: 'copilot',
    label: 'copilot-agent.l5',
    type: 'cloud',
    ip: '10.250.1.9',
    x: 670,
    y: 140,
    vx: 0,
    vy: 0,
    fx: null,
    fy: null,
    status: 'ok',
    role: 'Autonomous AI Incident Triage Agent Enclave',
    traffic: '8.1 MB/s',
    connections: 1,
    radius: 12,
  },
];

const INITIAL_LINKS: TopologyLink[] = [
  { source: 'kano-03', target: '185.220.x.x', alert: true, speed: '8.4 KB/s' },
  { source: 'kano-03', target: 'core-router', speed: '14.2 MB/s' },
  { source: 'kano-01', target: 'core-router', speed: '1.2 MB/s' },
  { source: 'kano-02', target: 'core-router', speed: '420 KB/s' },
  { source: 'ussd-gw-2', target: 'core-router', speed: '22.8 MB/s' },
  { source: 'ussd-gw-2', target: 'nibss-switch', speed: '18.4 MB/s' },
  { source: 'core-router', target: 'nibss-switch', speed: '84.2 MB/s' },
  { source: 'core-router', target: 'paystack-api', speed: '32.1 MB/s' },
  { source: 'core-router', target: 'siem', speed: '64.5 MB/s' },
  { source: 'siem', target: 'copilot', speed: '8.1 MB/s' },
];

export default function TopologyGraph() {
  const toast = useToast();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const nodesRef = useRef<TopologyNode[]>(JSON.parse(JSON.stringify(INITIAL_NODES)));
  const linksRef = useRef<TopologyLink[]>(INITIAL_LINKS);
  const packetsRef = useRef<Packet[]>([]);

  const [filter, setFilter] = useState<'all' | 'hot' | 'gateways' | 'workstations'>('all');
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<TopologyNode | null>(null);
  const [physicsActive, setPhysicsActive] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDraggingNode, setIsDraggingNode] = useState(false);

  // Transform refs for direct event handling
  const transformRef = useRef({ zoom: 1, panX: 0, panY: 0 });
  transformRef.current = { zoom, panX: pan.x, panY: pan.y };

  const mouseState = useRef({
    isDown: false,
    dragNode: null as TopologyNode | null,
    startX: 0,
    startY: 0,
    lastX: 0,
    lastY: 0,
    hasMoved: false,
  });

  // Spawn dynamic data packets on links
  useEffect(() => {
    const iv = setInterval(() => {
      if (packetsRef.current.length > 25) return;
      const links = linksRef.current;
      const randomLink = links[Math.floor(Math.random() * links.length)];
      if (randomLink) {
        packetsRef.current.push({
          sourceId: randomLink.source,
          targetId: randomLink.target,
          progress: 0,
          speed: randomLink.alert ? 0.022 : 0.012 + Math.random() * 0.015,
          alert: randomLink.alert,
        });
      }
    }, 450);
    return () => clearInterval(iv);
  }, []);

  // Main Canvas Render & Physics Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;

    const render = () => {
      raf = requestAnimationFrame(render);
      const W = canvas.width / (window.devicePixelRatio || 1);
      const H = canvas.height / (window.devicePixelRatio || 1);
      const dpr = window.devicePixelRatio || 1;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();
      ctx.scale(dpr, dpr);

      // Apply Pan & Zoom
      const { zoom: z, panX, panY } = transformRef.current;
      ctx.translate(panX + W / 2, panY + H / 2);
      ctx.scale(z, z);
      ctx.translate(-W / 2, -H / 2);

      const nodes = nodesRef.current;
      const links = linksRef.current;

      // ---- 1. Force-Directed Physics Simulation (Obsidian-Style) ----
      if (physicsActive) {
        const centerX = W / 2;
        const centerY = H / 2;
        const repulsionStrength = 1800;
        const springLength = 140;
        const springStiffness = 0.035;
        const damping = 0.88;
        const centerGravity = 0.012;

        // Repulsion between all pairs
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i];
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j];
            const dx = b.x - a.x;
            const dy = b.y - a.y;
            const distSq = dx * dx + dy * dy || 1;
            const dist = Math.sqrt(distSq);
            if (dist < 320) {
              const force = (repulsionStrength / distSq);
              const fx = (dx / dist) * force;
              const fy = (dy / dist) * force;
              if (a.fx === null) { a.vx -= fx; a.vy -= fy; }
              if (b.fx === null) { b.vx += fx; b.vy += fy; }
            }
          }

          // Center gravity
          if (a.fx === null) {
            a.vx += (centerX - a.x) * centerGravity;
            a.vy += (centerY - a.y) * centerGravity;
          }
        }

        // Spring attraction along links
        for (const l of links) {
          const a = nodes.find(n => n.id === l.source);
          const b = nodes.find(n => n.id === l.target);
          if (!a || !b) continue;

          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const delta = dist - (l.alert ? springLength * 0.85 : springLength);
          const force = delta * springStiffness;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          if (a.fx === null) { a.vx += fx; a.vy += fy; }
          if (b.fx === null) { b.vx -= fx; b.vy -= fy; }
        }

        // Velocity integration & bounds decay
        for (const n of nodes) {
          if (n.fx !== null && n.fy !== null) {
            n.x = n.fx;
            n.y = n.fy;
            n.vx = 0;
            n.vy = 0;
          } else {
            n.vx *= damping;
            n.vy *= damping;
            n.x += n.vx;
            n.y += n.vy;
          }
        }
      }

      // Colors from design tokens
      const isDark = document.documentElement.dataset.theme === 'dark';
      const inkColor = isDark ? '#EDE8DC' : '#171510';
      const softColor = isDark ? '#918B79' : '#635D4C';
      const lineColor = isDark ? '#2B2820' : '#DED7C5';
      const accentColor = isDark ? '#E5532B' : '#C63A14';
      const warnColor = isDark ? '#D5A44E' : '#B27E1C';
      const okColor = isDark ? '#7FAF8B' : '#2F7547';

      // ---- 2. Draw Links ----
      for (const l of links) {
        const a = nodes.find(n => n.id === l.source);
        const b = nodes.find(n => n.id === l.target);
        if (!a || !b) continue;

        const isRelatedToHover = hoveredNode && (hoveredNode.id === a.id || hoveredNode.id === b.id);
        const isRelatedToSelected = selectedNode && (selectedNode.id === a.id || selectedNode.id === b.id);
        const isDimmed = (hoveredNode || selectedNode) && !isRelatedToHover && !isRelatedToSelected;

        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);

        if (l.alert) {
          ctx.strokeStyle = accentColor;
          ctx.lineWidth = isRelatedToHover || isRelatedToSelected ? 2.5 : 1.8;
          ctx.setLineDash([5, 5]);
        } else {
          ctx.strokeStyle = isRelatedToHover || isRelatedToSelected ? accentColor : lineColor;
          ctx.lineWidth = isRelatedToHover || isRelatedToSelected ? 2 : 1;
          ctx.setLineDash([]);
        }

        ctx.globalAlpha = isDimmed ? 0.15 : (l.alert ? 0.9 : 0.65);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // ---- 3. Draw Traveling Data Packets ----
      const updatedPackets: Packet[] = [];
      for (const p of packetsRef.current) {
        p.progress += p.speed;
        const a = nodes.find(n => n.id === p.sourceId);
        const b = nodes.find(n => n.id === p.targetId);
        if (a && b && p.progress < 1) {
          const px = a.x + (b.x - a.x) * p.progress;
          const py = a.y + (b.y - a.y) * p.progress;

          ctx.beginPath();
          ctx.arc(px, py, p.alert ? 3.5 : 2.2, 0, Math.PI * 2);
          ctx.fillStyle = p.alert ? accentColor : (isDark ? '#FFF' : accentColor);
          ctx.globalAlpha = p.alert ? 0.95 : 0.75;
          ctx.fill();

          // Packet glow tail
          ctx.beginPath();
          ctx.arc(px, py, p.alert ? 6 : 4, 0, Math.PI * 2);
          ctx.fillStyle = p.alert ? 'rgba(229,83,43,0.3)' : 'rgba(198,58,20,0.15)';
          ctx.fill();

          updatedPackets.push(p);
        }
      }
      packetsRef.current = updatedPackets;

      // ---- 4. Draw Nodes ----
      const now = performance.now();
      for (const n of nodes) {
        // Filter checks
        let passesFilter = true;
        if (filter === 'hot' && n.status !== 'hot') passesFilter = false;
        if (filter === 'gateways' && n.type !== 'gateway' && n.type !== 'switch') passesFilter = false;
        if (filter === 'workstations' && n.type !== 'workstation') passesFilter = false;

        const isHovered = hoveredNode?.id === n.id;
        const isSelected = selectedNode?.id === n.id;
        const isNeighbor = (hoveredNode || selectedNode) && links.some(
          l => (l.source === n.id && (l.target === hoveredNode?.id || l.target === selectedNode?.id)) ||
               (l.target === n.id && (l.source === hoveredNode?.id || l.source === selectedNode?.id))
        );
        const isDimmed = !passesFilter || ((hoveredNode || selectedNode) && !isHovered && !isSelected && !isNeighbor);

        ctx.globalAlpha = isDimmed ? 0.18 : 1;

        // Pulsing sonar rings on compromised/hot nodes
        if (n.status === 'hot') {
          const pulsePhase = (now * 0.0018) % 1;
          const pulseRadius = n.radius + pulsePhase * 24;
          ctx.beginPath();
          ctx.arc(n.x, n.y, pulseRadius, 0, Math.PI * 2);
          ctx.strokeStyle = accentColor;
          ctx.lineWidth = 1.2;
          ctx.globalAlpha = (1 - pulsePhase) * (isDimmed ? 0.1 : 0.8);
          ctx.stroke();
          ctx.globalAlpha = isDimmed ? 0.18 : 1;
        }

        // Selected / Hovered Highlight Aura
        if (isSelected || isHovered) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius + 7, 0, Math.PI * 2);
          ctx.fillStyle = n.status === 'hot' ? 'rgba(229,83,43,0.25)' : 'rgba(198,58,20,0.15)';
          ctx.fill();
        }

        // Node Circle Body
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);

        if (n.status === 'hot') {
          ctx.fillStyle = accentColor;
        } else if (n.status === 'warn') {
          ctx.fillStyle = warnColor;
        } else if (n.type === 'switch' || n.type === 'gateway') {
          ctx.fillStyle = okColor;
        } else {
          ctx.fillStyle = inkColor;
        }
        ctx.fill();

        // Node border ring
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = isSelected ? accentColor : (isHovered ? inkColor : lineColor);
        ctx.stroke();

        // Center jewel icon/point
        ctx.beginPath();
        ctx.arc(n.x, n.y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = isDark ? '#171510' : '#FCFAF4';
        ctx.fill();

        // Text Label underneath node
        ctx.font = '10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillStyle = isSelected || isHovered ? accentColor : (isNeighbor ? inkColor : softColor);
        ctx.fillText(n.id, n.x, n.y + n.radius + 6);

        if (n.status === 'hot') {
          ctx.font = '8.5px "IBM Plex Mono", monospace';
          ctx.fillStyle = accentColor;
          ctx.fillText('▲ BEACON ALERT', n.x, n.y + n.radius + 18);
        }
      }

      ctx.restore();
    };

    render();

    return () => cancelAnimationFrame(raf);
  }, [physicsActive, filter, hoveredNode, selectedNode]);

  // Handle Resize for HiDPI
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = rect.width * dpr;
      canvas.height = 360 * dpr;
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `360px`;
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Screen-to-World Coordinate converter
  const screenToWorld = (screenX: number, screenY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const W = rect.width;
    const H = rect.height;
    const { zoom: z, panX, panY } = transformRef.current;

    const normX = screenX - rect.left;
    const normY = screenY - rect.top;

    const centeredX = normX - (panX + W / 2);
    const centeredY = normY - (panY + H / 2);

    const worldX = centeredX / z + W / 2;
    const worldY = centeredY / z + H / 2;

    return { x: worldX, y: worldY };
  };

  // Pointer & Drag Interactions
  const handlePointerDown = (e: React.PointerEvent) => {
    const world = screenToWorld(e.clientX, e.clientY);
    const nodes = nodesRef.current;

    // Find if clicked on a node
    let clickedNode: TopologyNode | null = null;
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = world.x - n.x;
      const dy = world.y - n.y;
      if (dx * dx + dy * dy <= (n.radius + 8) * (n.radius + 8)) {
        clickedNode = n;
        break;
      }
    }

    mouseState.current.isDown = true;
    mouseState.current.hasMoved = false;
    mouseState.current.startX = e.clientX;
    mouseState.current.startY = e.clientY;
    mouseState.current.lastX = e.clientX;
    mouseState.current.lastY = e.clientY;

    if (clickedNode) {
      mouseState.current.dragNode = clickedNode;
      clickedNode.fx = clickedNode.x;
      clickedNode.fy = clickedNode.y;
      setIsDraggingNode(true);
    } else {
      mouseState.current.dragNode = null;
    }
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const { isDown, dragNode, lastX, lastY } = mouseState.current;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;

    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
      mouseState.current.hasMoved = true;
    }

    if (isDown) {
      if (dragNode) {
        // Dragging a node (Obsidian graph drag)
        const world = screenToWorld(e.clientX, e.clientY);
        dragNode.fx = world.x;
        dragNode.fy = world.y;
      } else {
        // Panning the canvas
        setPan(p => ({ x: p.x + dx, y: p.y + dy }));
      }
      mouseState.current.lastX = e.clientX;
      mouseState.current.lastY = e.clientY;
    } else {
      // Hover detection
      const world = screenToWorld(e.clientX, e.clientY);
      const nodes = nodesRef.current;
      let found: TopologyNode | null = null;
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i];
        const ddx = world.x - n.x;
        const ddy = world.y - n.y;
        if (ddx * ddx + ddy * ddy <= (n.radius + 8) * (n.radius + 8)) {
          found = n;
          break;
        }
      }
      setHoveredNode(found);
    }
  };

  const handlePointerUp = () => {
    const { dragNode, hasMoved } = mouseState.current;
    if (dragNode) {
      // If it wasn't dragged much, treat as a selection click
      if (!hasMoved) {
        setSelectedNode(prev => (prev?.id === dragNode.id ? null : dragNode));
      }
      // Release node spring physics
      dragNode.fx = null;
      dragNode.fy = null;
      mouseState.current.dragNode = null;
      setIsDraggingNode(false);
    } else if (!hasMoved) {
      setSelectedNode(null);
    }
    mouseState.current.isDown = false;
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
    setZoom(z => Math.max(0.4, Math.min(2.5, z * zoomFactor)));
  };

  const handleResetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setSelectedNode(null);
    toast('Topology camera reset to default view.');
  };

  const handleIsolateNode = (node: TopologyNode) => {
    toast(`Node ${node.id} isolated from core routing table.`);
  };

  const handleDeepScan = (node: TopologyNode) => {
    toast(`Dispatched deep packet forensic inspection on ${node.ip}…`);
  };

  return (
    <div ref={containerRef} className="relative w-full overflow-hidden select-none">
      {/* Top Toolbar / Filter Strip */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 px-3 sm:px-5 py-2.5 sm:py-3 border-b border-line bg-inset">
        <div className="flex items-center gap-2">
          <span className="eyebrow text-[10px] flex items-center gap-1.5">
            <Radio size={12} className="text-accent animate-pulse" />
            <span className="hidden sm:inline">INTERACTIVE FORCE GRAPH</span>
            <span className="sm:hidden">FORCE GRAPH</span>
          </span>
          <span className="tag text-[9px] hidden sm:inline-block">OBSIDIAN PHYSICS</span>
        </div>

        {/* Filter categories */}
        <div className="flex items-center gap-1 overflow-x-auto max-w-full py-0.5">
          {(['all', 'hot', 'gateways', 'workstations'] as const).map(cat => (
            <button
              key={cat}
              type="button"
              className={`chip text-[10px] py-0.5 px-2 border-0 ${filter === cat ? 'on' : ''}`}
              onClick={() => setFilter(cat)}
            >
              {cat.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Graph interaction controls */}
        <div className="flex items-center gap-1.5 ml-auto sm:ml-0">
          <button
            className="icon-btn w-7 h-7"
            onClick={() => setPhysicsActive(!physicsActive)}
            title={physicsActive ? 'Pause physics' : 'Resume physics'}
          >
            {physicsActive ? <Pause size={12} /> : <Play size={12} />}
          </button>
          <button
            className="icon-btn w-7 h-7"
            onClick={() => setZoom(z => Math.min(2.5, z * 1.15))}
            title="Zoom in"
          >
            <ZoomIn size={12} />
          </button>
          <button
            className="icon-btn w-7 h-7"
            onClick={() => setZoom(z => Math.max(0.4, z * 0.85))}
            title="Zoom out"
          >
            <ZoomOut size={12} />
          </button>
          <button
            className="icon-btn w-7 h-7"
            onClick={handleResetView}
            title="Reset view"
          >
            <RotateCcw size={12} />
          </button>
        </div>
      </div>

      {/* Interactive Canvas Canvas Area */}
      <div className="relative bg-inset/40" style={{ height: 360 }}>
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onWheel={handleWheel}
          className={`w-full h-full block ${isDraggingNode ? 'cursor-grabbing' : 'cursor-grab'}`}
          style={{ touchAction: 'none' }}
        />

        {/* Hover Floating Tooltip */}
        {hoveredNode && !selectedNode && (
          <div
            className="absolute z-20 pointer-events-none p-2.5 rounded bg-raised border border-line-strong shadow-lg text-xs mono"
            style={{
              left: `${Math.min(window.innerWidth - 240, Math.max(16, hoveredNode.x * zoom + pan.x + 20))}px`,
              top: `${Math.min(300, Math.max(16, hoveredNode.y * zoom + pan.y - 40))}px`,
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold text-ink">{hoveredNode.id}</span>
              <span className={`tag text-[9px] ${hoveredNode.status === 'hot' ? 'acc' : ''}`}>
                {hoveredNode.status.toUpperCase()}
              </span>
            </div>
            <div className="text-[10px] text-soft mt-1">{hoveredNode.ip}</div>
            <div className="text-[10px] text-soft mt-0.5">TRAFFIC: {hoveredNode.traffic}</div>
          </div>
        )}

        {/* Node Detail Inspector Drawer / Overlay */}
        {selectedNode && (
          <div className="absolute top-2 left-2 sm:left-auto right-2 sm:right-3 bottom-2 sm:bottom-3 sm:w-80 z-30 p-3.5 sm:p-4 bg-raised border border-line-strong rounded shadow-xl flex flex-col justify-between animate-rise overflow-y-auto">
            <div>
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-sm font-semibold">{selectedNode.id}</span>
                    <span className={`tag text-[9px] ${selectedNode.status === 'hot' ? 'acc' : 'ok'}`}>
                      {selectedNode.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-xs mono text-soft mt-0.5">{selectedNode.ip}</div>
                </div>
                <button
                  className="icon-btn w-6 h-6"
                  onClick={() => setSelectedNode(null)}
                  title="Close inspector"
                >
                  <X size={13} />
                </button>
              </div>

              <p className="text-xs text-ink leading-relaxed my-2 sm:my-3 pb-2 sm:pb-3 border-b border-line">
                {selectedNode.role}
              </p>

              <dl className="grid grid-cols-2 gap-2 sm:gap-3 text-xs mono mb-3 sm:mb-4">
                <div>
                  <dt className="text-[10px] text-soft">NODE TYPE</dt>
                  <dd className="font-medium capitalize">{selectedNode.type}</dd>
                </div>
                <div>
                  <dt className="text-[10px] text-soft">THROUGHPUT</dt>
                  <dd className="font-medium">{selectedNode.traffic}</dd>
                </div>
                <div>
                  <dt className="text-[10px] text-soft">PEER LINKS</dt>
                  <dd className="font-medium">{selectedNode.connections} Active</dd>
                </div>
                <div>
                  <dt className="text-[10px] text-soft">ENCLAVE</dt>
                  <dd className="font-medium">Kano-01</dd>
                </div>
              </dl>
            </div>

            <div className="space-y-2 pt-2 sm:pt-3 border-t border-line">
              {selectedNode.status === 'hot' && (
                <button
                  className="btn btn-solid w-full justify-center text-xs py-2"
                  onClick={() => handleIsolateNode(selectedNode)}
                >
                  <ShieldAlert size={13} className="mr-1" /> ISOLATE FROM SWITCH
                </button>
              )}
              <button
                className="btn btn-ghost w-full justify-center text-xs py-2"
                onClick={() => handleDeepScan(selectedNode)}
              >
                <Zap size={13} className="mr-1 text-accent" /> DEEP PACKET SCAN
              </button>
            </div>
          </div>
        )}

        {/* Canvas Instructions Hint */}
        <div className="absolute bottom-2.5 left-4 pointer-events-none text-[10.5px] mono text-soft hidden sm:flex items-center gap-3">
          <span>● DRAG NODES TO SIMULATE ELASTIC SPRINGS</span>
          <span>● SCROLL TO ZOOM</span>
          <span>● CLICK NODE FOR ENCLAVE CONTROLS</span>
        </div>
        <div className="absolute bottom-2 left-3 pointer-events-none text-[9.5px] mono text-soft sm:hidden flex items-center gap-2">
          <span>● DRAG NODES</span>
          <span>● TAP TO INSPECT</span>
        </div>
      </div>
    </div>
  );
}
