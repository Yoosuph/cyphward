/* Thin async wrappers over the mock module.
   Every function resolves after ~300ms so the UI feels real.
   Swap the bodies for fetch calls when the backend exists. */

import * as mock from '../data/mock';
import type {
  Tenant, Posture, Score, ComplianceSummary, Alert, AlertDetail,
  DetectionLayer, Academy, CopilotSession, TickerItem,
} from '../data/mock';

const delay = (ms = 300) => new Promise<void>(r => setTimeout(r, ms));

export async function login(email: string, _password: string): Promise<Tenant> {
  await delay(450);
  // TODO: replace with real endpoint — POST /api/v1/auth/login
  return { ...mock.tenant, email: email || 'demo@acmetraders.ng' };
}

export async function getPosture(): Promise<Posture> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/posture
  return mock.posture;
}

export async function getScore(): Promise<Score> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/score
  return mock.score;
}

export async function getCompliance(framework: string): Promise<ComplianceSummary> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/compliance?framework=
  const controls = mock.controlsByFramework[framework] ?? [];
  const passing = controls.filter(c => c.status === 'PASS').length;
  return { frameworks: mock.frameworks, controls, passing, total: controls.length, remediations: mock.remediations };
}

export async function getAlerts(): Promise<Alert[]> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/alerts
  return mock.alerts;
}

export async function getAlertDetail(id: string): Promise<AlertDetail | null> {
  await delay(250);
  // TODO: replace with real endpoint — GET /api/v1/alerts/:id
  return mock.alertDetails[id] ?? null;
}

export async function getDetectionLayers(): Promise<DetectionLayer[]> {
  await delay(200);
  // TODO: replace with real endpoint — GET /api/v1/detect/layers
  return mock.detectionLayers;
}

export async function getAcademy(): Promise<Academy> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/academy
  return mock.academy;
}

export async function getCopilotSession(): Promise<CopilotSession> {
  await delay();
  // TODO: replace with real endpoint — GET /api/v1/copilot/session
  return mock.copilotSession;
}

export async function getTicker(): Promise<TickerItem[]> {
  await delay(200);
  // TODO: replace with real endpoint — GET /api/v1/ticker
  return mock.tickerItems;
}

export async function draftPolicy(controlId: string): Promise<{ ok: boolean; control: string }> {
  await delay(600);
  // TODO: replace with real endpoint — POST /api/v1/policies/draft
  return { ok: true, control: controlId };
}
