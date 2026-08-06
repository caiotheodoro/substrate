import type { ConfidenceResponse } from '@substrate/substrate';
import type { Tier } from './routing-policy.js';

/**
 * A-E-16 confidence-adapter — 02's C5 confidence → routing tier.
 *
 * The thresholds are the execute thresholds of 01's gate (two-threshold
 * discipline): a step is only cheap-tier-eligible when confidence is high
 * ENOUGH to execute; the escalation band and reject band must never be
 * routed to a cheap tier, and reject-band escalates to the frontier where
 * 01's gate will make the final call.
 */

export interface TierThresholds {
  /** score >= small → cheap tier (execute-band territory). */
  small: number;
  /** score >= medium → mid tier; below → frontier. */
  medium: number;
}

export const DEFAULT_THRESHOLDS: TierThresholds = { small: 0.85, medium: 0.7 };

export function confidenceToTier(
  confidence: ConfidenceResponse,
  thresholds: TierThresholds = DEFAULT_THRESHOLDS,
): Tier {
  if (confidence.band === 'reject-band') return 'frontier';
  if (confidence.band === 'escalation-band' && confidence.score < thresholds.small) {
    return confidence.score >= thresholds.medium ? 'medium' : 'frontier';
  }
  if (confidence.score >= thresholds.small) return 'small';
  if (confidence.score >= thresholds.medium) return 'medium';
  return 'frontier';
}

/** Validation: thresholds are ordered so the tier map is well-formed. */
export function assertThresholdOrder(thresholds: TierThresholds): void {
  if (!(thresholds.small > thresholds.medium)) {
    throw new Error('thresholds must satisfy small > medium');
  }
}
