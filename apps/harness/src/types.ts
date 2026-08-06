import type {
  DecisionRecord,
  Event,
  StepRecord,
  StoredEvent,
} from '@substrate/substrate';

export type PendingActionKind = 'question' | 'form' | 'decision';

export interface PendingAction {
  id: string;
  runId: string;
  turnId: string;
  kind: PendingActionKind;
  prompt: string;
  schema: Record<string, unknown>;
  answer: Record<string, unknown> | null;
  status: 'pending' | 'resolved';
  createdAt: string;
  resolvedAt: string | null;
  resolvedBy: string | null;
}

export type EscalationVerdict = 'pending' | 'approved' | 'rejected' | 'vetoed';

export interface EscalationProposal {
  action: string;
  turnId: string;
  confidenceFeatures: Record<string, unknown>;
  context?: string;
}

export interface Escalation {
  id: string;
  runId: string | null;
  decisionId: string;
  proposal: EscalationProposal;
  confidence: number;
  explain: Record<string, unknown>;
  verdict: EscalationVerdict;
  createdAt: string;
  resolvedAt: string | null;
  decidedBy: string | null;
}

export type SandboxStatus = 'pending' | 'alive' | 'expired' | 'released';

export interface SandboxLease {
  id: string;
  containerId: string;
  image: string;
  leaseMs: number;
  expiresAt: string;
  updatedAt: string;
  status: SandboxStatus;
}

export interface ThresholdBand {
  taskType: string;
  executeThreshold: number;
  rejectThreshold: number;
  note?: string;
}

export interface RunRecord {
  id: string;
  task: string;
  status: 'running' | 'ended';
  reason: string | null;
  maxTurns: number;
  startedAt: string;
  endedAt: string | null;
  seq: number;
}

export interface RunResult {
  run: RunRecord;
  events: StoredEvent[];
}

export interface Stores {
  runs: {
    create(run: RunRecord): Promise<void>;
    get(id: string): Promise<RunRecord | null>;
    update(id: string, patch: Partial<RunRecord>): Promise<void>;
    list(): Promise<RunRecord[]>;
  };
  events: {
    tail(runId: string): Promise<{ seq: number; chainHash: string | null }>;
    append(runId: string, events: Event[], prev: { seq: number; chainHash: string | null }): Promise<StoredEvent[]>;
    list(runId: string): Promise<StoredEvent[]>;
  };
  decisions: {
    insert(record: DecisionRecord): Promise<void>;
    get(decisionId: string): Promise<DecisionRecord | null>;
    list(): Promise<DecisionRecord[]>;
    confirmOutcome(decisionId: string, outcome: boolean): Promise<void>;
  };
  pendingActions: {
    insert(action: PendingAction): Promise<void>;
    list(runId: string): Promise<PendingAction[]>;
    get(id: string): Promise<PendingAction | null>;
    resolve(id: string, answer: Record<string, unknown>, by: string): Promise<void>;
  };
  escalations: {
    insert(e: Escalation): Promise<void>;
    list(): Promise<Escalation[]>;
    get(id: string): Promise<Escalation | null>;
    decide(id: string, verdict: Exclude<EscalationVerdict, 'pending'>, by: string): Promise<void>;
  };
  sandboxLeases: {
    upsert(lease: SandboxLease): Promise<void>;
    get(id: string): Promise<SandboxLease | null>;
    remove(id: string): Promise<void>;
    list(): Promise<SandboxLease[]>;
  };
  thresholds: {
    set(taskType: string, band: Omit<ThresholdBand, 'taskType'>): Promise<void>;
    get(taskType: string): Promise<ThresholdBand | null>;
    list(): Promise<ThresholdBand[]>;
  };
  costLedger: {
    insert(step: StepRecord): Promise<void>;
    list(): Promise<StepRecord[]>;
  };
  emit: {
    on(fn: (e: StoredEvent) => void): () => void;
  };
}