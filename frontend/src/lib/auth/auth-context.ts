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

import React, { createContext, useContext, useState } from 'react';

export interface UserSession {
  userId: string;
  username: string;
  role: string;
  token?: string;
}

export interface AuthContextValue {
  session: UserSession | null;
  isAuthenticated: boolean;
  setSession: (session: UserSession | null) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  isAuthenticated: false,
  setSession: () => {},
  logout: () => {},
});

export const AuthProvider: React.FC<{ children: React.ReactNode; initialSession?: UserSession | null }> = ({
  children,
  initialSession = null,
}) => {
  const [session, setSession] = useState<UserSession | null>(initialSession);

  const logout = () => {
    setSession(null);
  };

  return React.createElement(
    AuthContext.Provider,
    {
      value: {
        session,
        isAuthenticated: !!session,
        setSession,
        logout,
      },
    },
    children
  );
};

export const useAuth = () => useContext(AuthContext);
