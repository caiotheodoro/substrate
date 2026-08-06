import { PromptRegionSchema } from '@substrate/substrate';
import type { z } from 'zod';

/** C7 prompt region type + order, derived from the substrate contract. */
export type PromptRegion = z.infer<typeof PromptRegionSchema>;
export const REGIONS = PromptRegionSchema.options as readonly PromptRegion[];
