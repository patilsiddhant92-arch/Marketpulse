import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * tailwind-merge must know the custom font sizes from tailwind.config.js,
 * otherwise `text-kpi text-up` reads as two colours and the size is dropped.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: ['2xs', 'table', 'label', 'title', 'kpi', 'display'] }],
    },
  },
});

/** Merge class names; later Tailwind utilities win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
