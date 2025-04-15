import React, { createContext, useState, useContext, useEffect, useCallback } from 'react';
import axios from 'axios';
import { useAuth } from './AuthContext';

interface ChatMessage {
  id: string;
  roomId: string;
  senderId: string;
  content: string;
  timestamp: string;
  senderUsername: string;
}

interface Room {
  id: string;
  name: string;
  description: string;
  isPrivate: boolean;
  createdAt: string;
  participantCount: number;
}

interface ChatContextType {
  rooms: Room[];
  currentRoom: string | null;
  messages: ChatMessage[];
  loading: boolean;
  error: string | null;
  sendMessage: (content: string) => void;
  joinRoom: (roomId: string) => void;
  leaveRoom: () => void;
  createRoom: (name: string, description: string, isPrivate: boolean) => Promise<string>;
  fetchRooms: () => Promise<void>;
}

const ChatContext = createContext<ChatContextType | undefined>(undefined);

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const ChatProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { token, user } = useAuth();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [currentRoom, setCurrentRoom] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);

  // Fetch available rooms
  const fetchRooms = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_URL}/api/rooms`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      });
      setRooms(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to fetch rooms');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Create a new room
  const createRoom = async (name: string, description: string, isPrivate: boolean) => {
    try {
      const response = await axios.post(
        `${API_URL}/api/rooms`,
        { name, description, is_private: isPrivate },
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      );
      await fetchRooms();
      return response.data.id;
    } catch (err) {
      setError('Failed to create room');
      console.error(err);
      throw err;
    }
  };

  // Connect to WebSocket when joining a room
  const joinRoom = useCallback((roomId: string) => {
    if (!token || !user) return;

    setCurrentRoom(roomId);
    setMessages([]);
    setLoading(true);

    // Fetch message history
    axios.get(`${API_URL}/api/rooms/${roomId}/messages`, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    })
      .then(response => {
        setMessages(response.data);
        setError(null);
      })
      .catch(err => {
        setError('Failed to fetch message history');
        console.error(err);
      })
      .finally(() => {
        setLoading(false);
      });

    // Connect to WebSocket
    if (socket) {
      socket.close();
    }

    const ws = new WebSocket(`${API_URL.replace('http', 'ws')}/ws/chat/${roomId}?token=${token}`);
    
    ws.onopen = () => {
      console.log('WebSocket connection established');
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      setMessages(prev => [...prev, message]);
    };

    ws.onerror = (event) => {
      console.error('WebSocket error:', event);
      setError('WebSocket connection error');
    };

    ws.onclose = () => {
      console.log('WebSocket connection closed');
    };

    setSocket(ws);
  }, [token, user]);

  // Disconnect from WebSocket when leaving a room
  const leaveRoom = useCallback(() => {
    if (socket) {
      socket.close();
      setSocket(null);
    }
    setCurrentRoom(null);
    setMessages([]);
  }, [socket]);

  // Send message through WebSocket
  const sendMessage = useCallback((content: string) => {
    if (!socket || socket.readyState !== WebSocket.OPEN || !currentRoom || !user) {
      setError('Cannot send message: not connected');
      return;
    }

    const message = {
      roomId: currentRoom,
      content
    };

    socket.send(JSON.stringify(message));
  }, [socket, currentRoom, user]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (socket) {
        socket.close();
      }
    };
  }, [socket]);

  // Fetch rooms on initial load
  useEffect(() => {
    if (token) {
      fetchRooms();
    }
  }, [token]);

  return (
    <ChatContext.Provider value={{
      rooms,
      currentRoom,
      messages,
      loading,
      error,
      sendMessage,
      joinRoom,
      leaveRoom,
      createRoom,
      fetchRooms
    }}>
      {children}
    </ChatContext.Provider>
  );
};

export const useChat = () => {
  const context = useContext(ChatContext);
  if (context === undefined) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
}; 