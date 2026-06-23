import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// clsx for conditional composition + tailwind-merge so a caller's `className`
// override actually wins over a primitive's defaults (e.g. rounded-full beats
// rounded-xl) instead of both classes lingering.
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))
