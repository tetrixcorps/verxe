import axios from 'axios';
import { decimify } from '../utils/numberUtils';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface TokenBalance {
  user_id: string;
  amount: string;
  updated_at: string;
}

export interface TokenTransaction {
  id: string;
  user_id: string;
  amount: string;
  type: string;
  description: string | null;
  reference_id: string | null;
  created_at: string;
}

const tokenService = {
  async getBalance(token: string): Promise<TokenBalance> {
    const response = await axios.get<TokenBalance>(`${API_URL}/api/tokens/balance`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    return response.data;
  },

  async getTransactions(token: string, limit: number = 100, offset: number = 0): Promise<TokenTransaction[]> {
    const response = await axios.get<TokenTransaction[]>(
      `${API_URL}/api/tokens/transactions?limit=${limit}&offset=${offset}`,
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async transferTokens(
    token: string,
    recipientId: string,
    amount: number,
    description: string = 'Token transfer'
  ): Promise<TokenTransaction> {
    const response = await axios.post<TokenTransaction>(
      `${API_URL}/api/tokens/transfer?recipient_id=${recipientId}&amount=${decimify(amount)}&description=${encodeURIComponent(description)}`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async tipUser(
    token: string,
    recipientId: string,
    amount: number,
    streamId?: string
  ): Promise<TokenTransaction> {
    let url = `${API_URL}/api/tokens/tip?recipient_id=${recipientId}&amount=${decimify(amount)}`;
    
    if (streamId) {
      url += `&stream_id=${streamId}`;
    }
    
    const response = await axios.post<TokenTransaction>(
      url,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  }
};

export default tokenService; 