import { describe, expect, it } from 'vitest';
import { loadTaskFamilies, TASK_FAMILIES } from '../mtu/task-families.js';
import {
  familyRanking,
  fakeGateConfidence,
  qualityOf,
  runMtuStudy,
} from '../mtu/mtu-harness.js';

describe('A-E-25 task-families dataset', () => {
  it('contains the five families with easy/hard splits, deterministically', () => {
    const tasks = loadTaskFamilies();
    expect(tasks.length).toBe(60);
    for (const family of TASK_FAMILIES) {
      const ofFamily = tasks.filter((t) => t.family === family);
      expect(ofFamily.length).toBe(12);
      expect(ofFamily.filter((t) => t.split === 'easy').length).toBe(6);
      expect(ofFamily.filter((t) => t.split === 'hard').length).toBe(6);
    }
    expect(loadTaskFamilies()).toEqual(tasks);
  });
});

describe('A-E-24 mtu-harness', () => {
  it('the fake gate is deterministic and threshold-driven', () => {
    const conf = fakeGateConfidence('classification', 'hard', ['task', 'few-shot', 'dynamic']);
    expect(conf).toBe(fakeGateConfidence('classification', 'hard', ['task', 'few-shot', 'dynamic']));
    expect(qualityOf(0.9)).toBe(1);
    expect(qualityOf(0.7)).toBe(0.5);
    expect(qualityOf(0.4)).toBe(0);
  });

  it('ablating the critical region drops quality on hard tasks', () => {
    const tasks = loadTaskFamilies().filter((t) => t.family === 'code-gen');
    const results = runMtuStudy(tasks);
    const hardTask = results.find(
      (r) => r.difficulty === 'hard' && r.region === 'task',
    )!;
    expect(hardTask.contribution).toBe(0.5);
    const hardFewShot = results.find(
      (r) => r.difficulty === 'hard' && r.region === 'few-shot',
    )!;
    expect(hardFewShot.contribution).toBe(0);
    expect(hardFewShot.fullQuality).toBe(1);
  });

  it('easy tasks execute regardless of ablation (nothing pays on easy)', () => {
    const tasks = loadTaskFamilies().filter((t) => t.family === 'classification' && t.split === 'easy');
    const results = runMtuStudy(tasks);
    for (const row of results) {
      expect(row.contribution).toBe(0);
      expect(row.fullQuality).toBe(1);
    }
  });

  it('ranking orders regions by contribution per token', () => {
    const results = runMtuStudy(loadTaskFamilies());
    const ranked = familyRanking(results, 'retrieval-answer');
    expect(ranked.length).toBe(72);
    for (let i = 1; i < ranked.length; i++) {
      expect(ranked[i - 1]!.contributionPerToken).toBeGreaterThanOrEqual(ranked[i]!.contributionPerToken);
    }
    expect(ranked[0]!.region).toBe('dynamic');
    expect(ranked[0]!.contribution).toBe(0.5);
  });

  it('reports per-family rankings with real token counts', () => {
    const results = runMtuStudy(loadTaskFamilies());
    expect(results.length).toBe(60 * 6);
    for (const row of results) {
      expect(row.tokens).toBeGreaterThan(0);
      expect(row.contribution).toBeGreaterThanOrEqual(0);
    }
  });
});
