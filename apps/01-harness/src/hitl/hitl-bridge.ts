import type { PendingAction, Stores } from '../types';

export interface HitlBridge {
  pause(runId: string): Promise<void>;
  signal(runId: string): void;
}

export class InProcessHitlBridge implements HitlBridge {
  private waiters = new Map<string, Set<() => void>>();
  constructor(private stores: Stores) {}

  async pause(runId: string): Promise<void> {
    const pending = await this.stores.pendingActions.list(runId);
    if (!pending.some((p) => p.status === 'pending')) return;
    return new Promise((resolve) => {
      const set = this.waiters.get(runId) ?? new Set();
      set.add(resolve);
      this.waiters.set(runId, set);
    });
  }

  signal(runId: string): void {
    const set = this.waiters.get(runId);
    if (!set) return;
    for (const fn of set) fn();
    this.waiters.delete(runId);
  }

  waitForResolved(actionId: string): Promise<PendingAction> {
    return new Promise((resolve, reject) => {
      const check = async () => {
        const action = await this.stores.pendingActions.get(actionId);
        if (!action) {
          reject(new Error(`no pending action ${actionId}`));
          return;
        }
        if (action.status === 'resolved') {
          resolve(action);
          return;
        }
        setTimeout(check, 5);
      };
      void check();
    });
  }
}

export function waitForResolved(stores: Stores, runId: string): Promise<void> {
  return new Promise((resolve) => {
    const check = async () => {
      const pending = await stores.pendingActions.list(runId);
      if (!pending.some((p) => p.status === 'pending')) {
        resolve();
        return;
      }
      setTimeout(check, 5);
    };
    void check();
  });
}
