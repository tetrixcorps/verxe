/**
 * Converts a number to a string with 2 decimal places
 * Used for API calls requiring decimal values
 */
export function decimify(value: number): string {
  return value.toFixed(2);
}

/**
 * Formats a number as currency
 */
export function formatCurrency(value: string | number): string {
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(numValue);
}

/**
 * Formats a large number with k/m/b suffixes
 */
export function formatCompactNumber(value: string | number): string {
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    maximumFractionDigits: 1
  }).format(numValue);
}

/**
 * Safely parses a string to float, returning 0 if invalid
 */
export function safeParseFloat(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const numValue = typeof value === 'string' ? parseFloat(value) : value;
  return isNaN(numValue) ? 0 : numValue;
} 