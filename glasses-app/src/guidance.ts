/**
 * CPR instructional copy and targets.
 *
 * !! VERIFY BEFORE DEMO !!
 * These match the commonly published AHA / Red Cross adult hands-only CPR
 * guidance, but they were written from memory. Before demoing, check every line
 * against the current AHA Guidelines for CPR & ECC (or Red Cross material) and
 * record the source and date here.
 *   Source: TODO
 *   Checked by / date: TODO
 */

export const TARGETS = {
  rateMinCpm: 100,
  rateMaxCpm: 120,
  depthMinCm: 5,
  depthMaxCm: 6,
  /** Suggested time before swapping compressors. */
  swapSeconds: 120,
} as const;

/** Body-positioning instructions shown before hand alignment. Keep lines short (~34 chars). */
export const SETUP_PAGES: { title: string; body: string }[] = [
  {
    title: 'KNEEL',
    body: "Kneel at the patient's side,\nclose to their chest.\nKnees about shoulder-width apart.",
  },
  {
    title: 'HANDS',
    body: 'Heel of one hand on the center\nof the chest (lower breastbone).\nOther hand on top, fingers laced.',
  },
  {
    title: 'BODY',
    body: 'Shoulders straight over hands.\nArms straight, elbows locked.\nPush down with your body weight.',
  },
];

export const DISCLAIMER =
  'TRAINING TOOL - NOT A MEDICAL DEVICE\nPractice on a manikin or pillow only.';
