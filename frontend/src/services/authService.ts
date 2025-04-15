import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterCredentials {
  username: string;
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface User {
  id: string;
  username: string;
  email: string;
}

const authService = {
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await axios.post<AuthResponse>(`${API_URL}/api/auth/login`, credentials);
    return response.data;
  },

  async register(credentials: RegisterCredentials): Promise<void> {
    await axios.post(`${API_URL}/api/auth/register`, credentials);
  },

  async refreshToken(refreshToken: string): Promise<AuthResponse> {
    const response = await axios.post<AuthResponse>(`${API_URL}/api/auth/refresh`, {
      refresh_token: refreshToken
    });
    return response.data;
  },

  async getUser(token: string): Promise<User> {
    const response = await axios.get<User>(`${API_URL}/api/users/me`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    return response.data;
  },

  async updateUser(token: string, data: Partial<User & { password: string }>): Promise<User> {
    const response = await axios.patch<User>(`${API_URL}/api/users/me`, data, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    return response.data;
  },

  async deleteUser(token: string): Promise<void> {
    await axios.delete(`${API_URL}/api/users/me`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
  }
};

export default authService; 