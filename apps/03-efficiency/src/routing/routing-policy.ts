import { z } from 'zod';
import type { ConfidenceResponse } from '@substrate/substrate';

/**
 * A-E-14 routing-policy — declarative (model, provider, quantization)
 * tuple policy with confidence-gated tiering.
 *
 * A policy is a list of tiers. Each tier has a minimum confidence; the
 * highest tier whose minimum is met wins. Falling below every minimum
 * sends the step to the frontier (the last tier) — routing must never
 * silently pick a weaker model on a low-confidence step.
 */

export const TierSchema = z.enum(['small', 'medium', 'frontier']);
export type Tier = z.infer<typeof TierSchema>;

export const RouteTupleSchema = z.object({
  model: z.string(),
  provider: z.string(),
  quantization: z.string().nullable(),
});
export type RouteTuple = z.infer<typeof RouteTupleSchema>;

export const TierPolicySchema = z.object({
  tier: TierSchema,
  minConfidence: z.number().min(0).max(1),
  route: RouteTupleSchema,
});
export type TierPolicy = z.infer<typeof TierPolicySchema>;

export const RoutingPolicySchema = z.object({
  tiers: z.array(TierPolicySchema).min(1),
});
export type RoutingPolicy = z.infer<typeof RoutingPolicySchema>;

export const DEFAULT_POLICY: RoutingPolicy = {
  tiers: [
    {
      tier: 'small',
      minConfidence: 0.85,
      route: { model: 'llama3.1:8b', provider: 'ollama', quantization: 'q4_k_m' },
    },
    {
      tier: 'medium',
      minConfidence: 0.7,
      route: { model: 'qwen2.5:14b', provider: 'ollama', quantization: 'q6_k' },
    },
    {
      tier: 'frontier',
      minConfidence: 0,
      route: { model: 'llama3.3:70b', provider: 'litellm', quantization: null },
    },
  ],
};

/**
 * Select the tier for a confidence score. The band (C5) overrides score
 * only in the unsafe direction: reject-band never routes to a cheap tier.
 */
export function selectTier(
  policy: RoutingPolicy,
  confidence: number,
  band?: ConfidenceResponse['band'],
): Tier {
  if (band === 'reject-band') return 'frontier';
  for (const tier of policy.tiers) {
    if (confidence >= tier.minConfidence) return tier.tier;
  }
  return 'frontier';
}

export function routeFor(
  policy: RoutingPolicy,
  confidence: number,
  band?: ConfidenceResponse['band'],
): RouteTuple {
  const tier = selectTier(policy, confidence, band);
  const found = policy.tiers.find((t) => t.tier === tier);
  return found?.route ?? policy.tiers[policy.tiers.length - 1]!.route;
}

export function tierOfRoute(policy: RoutingPolicy, route: RouteTuple): Tier | null {
  return policy.tiers.find((t) =>
    t.route.model === route.model &&
    t.route.provider === route.provider &&
    t.route.quantization === route.quantization,
  )?.tier ?? null;
}
