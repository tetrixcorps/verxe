import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import tokenService from '../services/tokenService';
import { useAuth } from './AuthContext';

interface Transaction {
  id: string;
  sender_id: string;
  receiver_id: string;
  amount: string;
  transaction_type: string;
  description: string;
  created_at: string;
  sender_username?: string;
  receiver_username?: string;
}

interface TokenContextType {
  balance: string;
  transactions: Transaction[];
  isLoading: boolean;
  error: string | null;
  refreshBalance: () => Promise<void>;
  getTransactionHistory: (page?: number, limit?: number) => Promise<void>;
  transferTokens: (receiverId: string, amount: number) => Promise<boolean>;
  tipUser: (userId: string, amount: number, streamId?: string) => Promise<boolean>;
}

const TokenContext = createContext<TokenContextType | undefined>(undefined);

export const TokenProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { token, user } = useAuth();
  
  const [balance, setBalance] = useState<string>('0');
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (token && user) {
      refreshBalance();
      getTransactionHistory();
    }
  }, [token, user]);

  const refreshBalance = async (): Promise<void> => {
    if (!token) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await tokenService.getBalance(token);
      setBalance(response.balance);
    } catch (err) {
      setError('Failed to fetch token balance');
      console.error('Error fetching token balance:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const getTransactionHistory = async (page = 1, limit = 10): Promise<void> => {
    if (!token) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await tokenService.getTransactions(token, page, limit);
      setTransactions(response);
    } catch (err) {
      setError('Failed to fetch transaction history');
      console.error('Error fetching transactions:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const transferTokens = async (receiverId: string, amount: number): Promise<boolean> => {
    if (!token) return false;
    
    setIsLoading(true);
    setError(null);
    
    try {
      await tokenService.transferTokens(token, receiverId, amount);
      await refreshBalance();
      await getTransactionHistory();
      return true;
    } catch (err) {
      setError('Failed to transfer tokens');
      console.error('Error transferring tokens:', err);
      return false;
    } finally {
      setIsLoading(false);
    }
  };

  const tipUser = async (userId: string, amount: number, streamId?: string): Promise<boolean> => {
    if (!token) return false;
    
    setIsLoading(true);
    setError(null);
    
    try {
      await tokenService.tipUser(token, userId, amount, streamId);
      await refreshBalance();
      await getTransactionHistory();
      return true;
    } catch (err) {
      setError('Failed to tip user');
      console.error('Error tipping user:', err);
      return false;
    } finally {
      setIsLoading(false);
    }
  };

  const value: TokenContextType = {
    balance,
    transactions,
    isLoading,
    error,
    refreshBalance,
    getTransactionHistory,
    transferTokens,
    tipUser
  };

  return <TokenContext.Provider value={value}>{children}</TokenContext.Provider>;
};

export const useTokens = (): TokenContextType => {
  const context = useContext(TokenContext);
  if (context === undefined) {
    throw new Error('useTokens must be used within a TokenProvider');
  }
  return context;
}; 