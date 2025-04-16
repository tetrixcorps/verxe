/**
 * Formats a number into a compact representation (e.g., 1.2k, 1.5M).
 * Handles potential string inputs by parsing them first.
 */
export function formatCompactNumber(value: string | number | null | undefined): string {
  const numValue = safeParseFloat(value);
  if (numValue === 0) return '0';
  
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1
  }).format(numValue);
}

/**
 * Formats a duration given in seconds into HH:MM:SS format.
 */
export function formatDuration(totalSeconds: string | number | null | undefined): string {
  const numSeconds = safeParseFloat(totalSeconds);
  if (numSeconds <= 0) return '00:00';

  const hours = Math.floor(numSeconds / 3600);
  const minutes = Math.floor((numSeconds % 3600) / 60);
  const seconds = Math.floor(numSeconds % 60);

  const hoursStr = String(hours).padStart(2, '0');
  const minutesStr = String(minutes).padStart(2, '0');
  const secondsStr = String(seconds).padStart(2, '0');

  if (hours > 0) {
    return `${hoursStr}:${minutesStr}:${secondsStr}`;
  } else {
    return `${minutesStr}:${secondsStr}`;
  }
}

/**
 * Safely parses a string or number to a float, returning 0 if invalid or null/undefined.
 */
export function safeParseFloat(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  
  const numValue = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
  
  return isNaN(numValue) ? 0 : numValue;
} 