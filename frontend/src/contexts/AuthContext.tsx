import React, { createContext, useState, useEffect, useContext } from 'react';
import authService, { User } from '../services/authService';

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem('token'));
  const [refreshToken, setRefreshToken] = useState<string | null>(localStorage.getItem('refreshToken'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      fetchUser();
    } else {
      setLoading(false);
    }
  }, [token]);

  const fetchUser = async () => {
    try {
      if (!token) return;
      
      const userData = await authService.getUser(token);
      setUser(userData);
    } catch (error) {
      console.error('Error fetching user:', error);
      
      // Try to refresh the token if we have a refresh token
      if (refreshToken) {
        try {
          const tokens = await authService.refreshToken(refreshToken);
          localStorage.setItem('token', tokens.access_token);
          localStorage.setItem('refreshToken', tokens.refresh_token);
          setToken(tokens.access_token);
          setRefreshToken(tokens.refresh_token);
          
          // Now try to fetch the user again with the new token
          const userData = await authService.getUser(tokens.access_token);
          setUser(userData);
        } catch (refreshError) {
          console.error('Error refreshing token:', refreshError);
          logout();
        }
      } else {
        logout();
      }
    } finally {
      setLoading(false);
    }
  };

  const login = async (email: string, password: string) => {
    try {
      const tokens = await authService.login({ email, password });
      
      localStorage.setItem('token', tokens.access_token);
      localStorage.setItem('refreshToken', tokens.refresh_token);
      setToken(tokens.access_token);
      setRefreshToken(tokens.refresh_token);
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  };

  const register = async (username: string, email: string, password: string) => {
    try {
      await authService.register({ username, email, password });
    } catch (error) {
      console.error('Registration error:', error);
      throw error;
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('refreshToken');
    setToken(null);
    setRefreshToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}; 