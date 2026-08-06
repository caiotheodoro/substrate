import { readFileSync } from 'node:fs';
import type { PromptRegion } from '../lib/prompt-regions.js';
import { dataFile } from '../lib/paths.js';

/**
 * A-E-25 task-families — the MTU dataset: synthetic, deterministic JSONL.
 * Five families × (easy/hard): classification, extraction, code-gen,
 * UI-gen, retrieval-answer. Each record carries the six C7 prompt regions
 * as plain strings so the harness can ablate (remove) any of them.
 */

export type TaskFamily = 'classification' | 'extraction' | 'code-gen' | 'ui-gen' | 'retrieval-answer';

export const TASK_FAMILIES: readonly TaskFamily[] = [
  'classification',
  'extraction',
  'code-gen',
  'ui-gen',
  'retrieval-answer',
];

export type TaskSplit = 'easy' | 'hard';

export interface TaskRecord {
  id: string;
  family: TaskFamily;
  split: TaskSplit;
  difficulty: TaskSplit;
  regions: Record<PromptRegion, string>;
  answer: string;
}

export const TASK_FAMILIES_PATH = dataFile('task-families.jsonl');

export function loadTaskFamilies(): TaskRecord[] {
  const text = readFileSync(TASK_FAMILIES_PATH, 'utf8');
  const tasks: TaskRecord[] = [];
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue;
    const parsed = JSON.parse(line) as TaskRecord;
    if (!TASK_FAMILIES.includes(parsed.family)) throw new Error(`unknown family: ${parsed.family}`);
    tasks.push(parsed);
  }
  return tasks;
}

export function familySplit(tasks: readonly TaskRecord[], family: TaskFamily): {
  easy: TaskRecord[];
  hard: TaskRecord[];
} {
  const easy = tasks.filter((t) => t.family === family && t.split === 'easy');
  const hard = tasks.filter((t) => t.family === family && t.split === 'hard');
  return { easy, hard };
}
