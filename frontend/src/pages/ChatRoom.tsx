import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useChat } from '../contexts/ChatContext';

const ChatRoom: React.FC = () => {
  const { roomId } = useParams<{ roomId: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { messages, currentRoom, loading, error, joinRoom, leaveRoom, sendMessage } = useChat();
  
  const [messageInput, setMessageInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Join room when component mounts
  useEffect(() => {
    if (roomId) {
      joinRoom(roomId);
    }
    
    // Leave room when component unmounts
    return () => {
      leaveRoom();
    };
  }, [roomId, joinRoom, leaveRoom]);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageInput.trim()) return;
    
    sendMessage(messageInput);
    setMessageInput('');
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="flex flex-col h-screen bg-gray-100">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <div className="flex items-center">
            <button
              onClick={() => navigate('/dashboard')}
              className="mr-4 text-gray-600 hover:text-gray-800"
            >
              &larr; Back
            </button>
            {loading ? (
              <div className="h-6 w-32 bg-gray-200 animate-pulse rounded"></div>
            ) : (
              <h1 className="text-xl font-bold text-gray-800">
                Chat Room {currentRoom}
              </h1>
            )}
          </div>
        </div>
      </header>

      <main className="flex-grow overflow-hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-full flex flex-col">
          {error && (
            <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 my-4" role="alert">
              <p>{error}</p>
            </div>
          )}

          {loading ? (
            <div className="flex-grow flex justify-center items-center">
              <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary"></div>
            </div>
          ) : (
            <div className="flex-grow overflow-y-auto p-4 space-y-4 mb-4">
              {messages.length === 0 ? (
                <div className="text-center text-gray-500 p-4">
                  No messages yet. Start the conversation!
                </div>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex ${
                      message.senderId === user?.id ? 'justify-end' : 'justify-start'
                    }`}
                  >
                    <div
                      className={`max-w-md px-4 py-2 rounded-lg ${
                        message.senderId === user?.id
                          ? 'bg-primary text-white'
                          : 'bg-white text-gray-800'
                      }`}
                    >
                      <div className="flex justify-between items-baseline mb-1">
                        <span className={`font-medium text-sm ${
                          message.senderId === user?.id ? 'text-blue-100' : 'text-gray-600'
                        }`}>
                          {message.senderUsername}
                        </span>
                        <span className={`text-xs ml-2 ${
                          message.senderId === user?.id ? 'text-blue-100' : 'text-gray-500'
                        }`}>
                          {formatTimestamp(message.timestamp)}
                        </span>
                      </div>
                      <p>{message.content}</p>
                    </div>
                  </div>
                ))
              )}
              <div ref={messagesEndRef} />
            </div>
          )}

          <form onSubmit={handleSendMessage} className="p-4 bg-white border-t">
            <div className="flex">
              <input
                type="text"
                value={messageInput}
                onChange={(e) => setMessageInput(e.target.value)}
                placeholder="Type a message..."
                className="flex-grow shadow-sm rounded-l-md border-r-0 border focus:ring-2 focus:ring-primary focus:border-transparent px-4 py-2"
                disabled={loading || error !== null}
              />
              <button
                type="submit"
                className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-r-md"
                disabled={loading || !messageInput.trim() || error !== null}
              >
                Send
              </button>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
};

export default ChatRoom; 