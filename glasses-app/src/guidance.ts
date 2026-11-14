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
  /** Pace of the flashing circle and phone beep - middle of the target rate range. */
  metronomeBpm: 110,
} as const;

/**
 * Body-positioning instructions shown before hand alignment, each with a picture
 * (frame key in display/frames.ts). Text sits in a ~264 px column next to the
 * picture: max 5 lines; layout.test.ts checks it fits with the G2 font.
 */
export const SETUP_PAGES: { title: string; body: string; frame: string }[] = [
  {
    title: 'KNEEL',
    body: 'Kneel beside the chest,\nclose to the patient.\nKnees shoulder-width apart.',
    frame: 'setup-kneel',
  },
  {
    title: 'HANDS',
    body: 'Heel of one hand on the\ncenter of the chest,\nlower half of breastbone.\nOther hand on top,\nfingers laced.',
    frame: 'setup-hands',
  },
  {
    title: 'BODY',
    body: 'Shoulders straight\nover your hands.\nArms straight, elbows locked.\nPush with your body weight.',
    frame: 'setup-body',
  },
];

