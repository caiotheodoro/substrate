export interface GatedTaskStep {
  action: string;
  confidenceFeatures: Record<string, unknown>;
  groundTruth: boolean;
}

export interface GatedTask {
  id: string;
  name: string;
  steps: GatedTaskStep[];
}

type StepTuple = [string, number, boolean, number?];

function steps(tuples: StepTuple[]): GatedTaskStep[] {
  return tuples.map(([action, score, gt, risk = 0.3]) => ({
    action,
    confidenceFeatures: { score, riskScore: risk, evidenceScore: 0.5, toolOk: true, schemaValid: true },
    groundTruth: gt,
  }));
}

export const GATED_TASK_SUITE: GatedTask[] = [
  {
    id: 'approvals',
    name: 'high-stakes approvals',
    steps: steps([
      ['approve-payment', 0.95, true, 0.9],
      ['approve-refund', 0.62, false, 0.85],
      ['approve-refund', 0.71, false, 0.85],
      ['approve-hold', 0.88, true, 0.6],
      ['approve-payment', 0.4, false, 0.9],
      ['approve-refund', 0.55, false, 0.85],
      ['approve-payment', 0.97, true, 0.9],
      ['approve-hold', 0.5, true, 0.6],
    ]),
  },
  {
    id: 'codegen',
    name: 'code generation pushes',
    steps: steps([
      ['push-commit', 0.8, true, 0.5],
      ['push-commit', 0.66, false, 0.5],
      ['push-commit', 0.91, true, 0.5],
      ['push-commit', 0.58, false, 0.5],
      ['deploy', 0.77, true, 0.8],
      ['deploy', 0.6, false, 0.8],
      ['deploy', 0.87, true, 0.8],
    ]),
  },
  {
    id: 'customer-service',
    name: 'customer support inbox',
    steps: steps([
      ['send-reply', 0.9, true, 0.2],
      ['send-reply', 0.73, true, 0.2],
      ['send-reply', 0.69, false, 0.2],
      ['send-reply', 0.55, false, 0.2],
      ['issue-refund', 0.84, true, 0.85],
      ['issue-refund', 0.68, false, 0.85],
      ['issue-refund', 0.95, true, 0.85],
      ['send-reply', 0.48, true, 0.2],
    ]),
  },
];

export function suiteSamples(taskId?: string): { score: number; outcome: boolean }[] {
  const tasks = taskId ? GATED_TASK_SUITE.filter((t) => t.id === taskId) : GATED_TASK_SUITE;
  const samples: { score: number; outcome: boolean }[] = [];
  for (const t of tasks) {
    for (const step of t.steps) {
      const raw = step.confidenceFeatures['score'];
      samples.push({ score: typeof raw === 'number' ? raw : 0.5, outcome: step.groundTruth });
    }
  }
  return samples;
}

export function outcomeOf(taskId: string, action: string): boolean | null {
  const task = GATED_TASK_SUITE.find((t) => t.id === taskId);
  if (!task) return null;
  const step = task.steps.find((s) => s.action === action);
  return step ? step.groundTruth : null;
}