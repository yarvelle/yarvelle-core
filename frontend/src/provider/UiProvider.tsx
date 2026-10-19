// Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
// Copyright 2026 Spectrayan (https://spectrayan.com)
//
// Licensed under the PolyForm Noncommercial License 1.0.0 and the
// Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
// Personal and household local use only. Commercial use, hosted service
// offering, rebranding, white-labeling, and redistribution of modified
// forks are prohibited without a written commercial license from Spectrayan.
//
// Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

import React, { createContext, useContext, useEffect, useState } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';

export interface ProductConfig {
  name: string;
  logo?: React.ReactNode;
}

export interface I18nContextValue {
  locale: string;
  t: (id: string, defaultText?: string) => string;
}

export interface UiContextValue {
  theme: ThemeMode;
  resolvedTheme: 'light' | 'dark';
  setTheme: (mode: ThemeMode) => void;
  product: ProductConfig;
  storageNamespace: string;
  i18n: I18nContextValue;
}

const defaultI18n: I18nContextValue = {
  locale: 'en-US',
  t: (_id: string, defaultText?: string) => defaultText || _id,
};

const UiContext = createContext<UiContextValue>({
  theme: 'system',
  resolvedTheme: 'light',
  setTheme: () => {},
  product: { name: 'Yarvelle' },
  storageNamespace: 'yarvelle',
  i18n: defaultI18n,
});

export interface UiProviderProps {
  children: React.ReactNode;
  defaultTheme?: ThemeMode;
  product?: ProductConfig;
  storageNamespace?: string;
  locale?: string;
  messages?: Record<string, string>;
}

export const UiProvider: React.FC<UiProviderProps> = ({
  children,
  defaultTheme = 'system',
  product = { name: 'Yarvelle' },
  storageNamespace = 'yarvelle',
  locale = 'en-US',
  messages = {},
}) => {
  const [theme, setThemeState] = useState<ThemeMode>(defaultTheme);
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>('light');

  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const updateTheme = () => {
      let isDark = false;
      if (theme === 'dark') {
        isDark = true;
      } else if (theme === 'system') {
        isDark = mediaQuery.matches;
      }

      setResolvedTheme(isDark ? 'dark' : 'light');
      root.setAttribute('data-theme', isDark ? 'dark' : 'light');
      if (isDark) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
    };

    updateTheme();
    mediaQuery.addEventListener('change', updateTheme);
    return () => mediaQuery.removeEventListener('change', updateTheme);
  }, [theme]);

  const t = (id: string, defaultText?: string): string => {
    if (messages[id]) {
      return messages[id];
    }
    return defaultText || id;
  };

  const value: UiContextValue = {
    theme,
    resolvedTheme,
    setTheme: setThemeState,
    product,
    storageNamespace,
    i18n: { locale, t },
  };

  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
};

export const useUi = (): UiContextValue => useContext(UiContext);
export const useTheme = () => {
  const { theme, resolvedTheme, setTheme } = useUi();
  return { theme, resolvedTheme, setTheme };
};
export const useProduct = () => useUi().product;
export const useStorageNamespace = () => useUi().storageNamespace;
export const useI18n = () => useUi().i18n;
