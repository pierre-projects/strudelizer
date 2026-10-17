// Dark by default, light on request, remembered between visits.
import { useCallback, useEffect, useState } from 'preact/hooks';

export type Theme = 'dark' | 'light';

const KEY = 'strudelizer.theme';

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(stored() ?? 'dark');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // Private browsing: the theme simply does not stick.
    }
  }, [theme]);

  return [theme, useCallback(() => setTheme((current) => (current === 'dark' ? 'light' : 'dark')), [])];
}

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'dark' || value === 'light' ? value : null;
  } catch {
    return null;
  }
}
