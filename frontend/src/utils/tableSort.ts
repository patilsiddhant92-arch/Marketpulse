export type SortDirection = 'asc' | 'desc' | null;

export interface SortConfig<T> {
  key: keyof T | string | null;
  direction: SortDirection;
}

export function sortData<T>(data: T[], key: keyof T | string | null, direction: SortDirection): T[] {
  if (!key || !direction) {
    return data;
  }

  return [...data].sort((a, b) => {
    // @ts-ignore
    const rawA = a[key];
    // @ts-ignore
    const rawB = b[key];

    const isNullA = rawA === undefined || rawA === null || rawA === '' || (typeof rawA === 'number' && isNaN(rawA));
    const isNullB = rawB === undefined || rawB === null || rawB === '' || (typeof rawB === 'number' && isNaN(rawB));

    if (isNullA && isNullB) return 0;
    if (isNullA) return 1; // Always place nulls at the end
    if (isNullB) return -1;

    // Numeric comparison
    if (typeof rawA !== 'boolean' && typeof rawB !== 'boolean') {
      const numA = typeof rawA === 'number' ? rawA : Number(rawA);
      const numB = typeof rawB === 'number' ? rawB : Number(rawB);
      if (!isNaN(numA) && !isNaN(numB)) {
        return direction === 'asc' ? numA - numB : numB - numA;
      }
    }

    // String comparison
    const strA = String(rawA).toLowerCase();
    const strB = String(rawB).toLowerCase();
    if (strA < strB) {
      return direction === 'asc' ? -1 : 1;
    }
    if (strA > strB) {
      return direction === 'asc' ? 1 : -1;
    }
    return 0;
  });
}
