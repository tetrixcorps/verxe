import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useChat } from '../contexts/ChatContext';

const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { rooms, loading, error, fetchRooms, createRoom } = useChat();
  
  const [isCreating, setIsCreating] = useState(false);
  const [newRoomName, setNewRoomName] = useState('');
  const [newRoomDescription, setNewRoomDescription] = useState('');
  const [newRoomPrivate, setNewRoomPrivate] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    fetchRooms();
  }, [fetchRooms]);

  const handleCreateRoom = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError('');
    
    if (!newRoomName.trim()) {
      setCreateError('Room name is required');
      return;
    }
    
    try {
      const roomId = await createRoom(newRoomName, newRoomDescription, newRoomPrivate);
      setIsCreating(false);
      setNewRoomName('');
      setNewRoomDescription('');
      setNewRoomPrivate(false);
      navigate(`/chat/${roomId}`);
    } catch (err: any) {
      setCreateError(err.response?.data?.detail || 'Failed to create room');
    }
  };

  const handleJoinRoom = (roomId: string) => {
    navigate(`/chat/${roomId}`);
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-800">Chat Rooms</h1>
          <div className="flex items-center space-x-4">
            <button
              onClick={() => navigate('/purchase-tokens')}
              className="text-sm font-medium text-primary hover:underline"
            >
              Get Tokens
            </button>
            <button
              onClick={() => navigate('/analytics')}
              className="text-gray-600 hover:text-gray-800"
            >
              Analytics
            </button>
            <button
              onClick={() => navigate('/profile')}
              className="text-gray-600 hover:text-gray-800"
            >
              Profile
            </button>
            <button
              onClick={handleLogout}
              className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded-md text-sm"
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-4 sm:px-0">
          {error && (
            <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4" role="alert">
              <p>{error}</p>
            </div>
          )}

          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-semibold text-gray-800">Available Rooms</h2>
            {!isCreating && (
              <button
                onClick={() => setIsCreating(true)}
                className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-md"
              >
                Create New Room
              </button>
            )}
          </div>

          {isCreating && (
            <div className="bg-white shadow rounded-lg p-6 mb-6">
              <h3 className="text-lg font-medium mb-4">Create New Room</h3>
              
              {createError && (
                <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-4" role="alert">
                  <p>{createError}</p>
                </div>
              )}
              
              <form onSubmit={handleCreateRoom}>
                <div className="mb-4">
                  <label htmlFor="roomName" className="block text-gray-700 text-sm font-bold mb-2">
                    Room Name*
                  </label>
                  <input
                    type="text"
                    id="roomName"
                    value={newRoomName}
                    onChange={(e) => setNewRoomName(e.target.value)}
                    className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                    required
                  />
                </div>
                
                <div className="mb-4">
                  <label htmlFor="roomDescription" className="block text-gray-700 text-sm font-bold mb-2">
                    Description
                  </label>
                  <textarea
                    id="roomDescription"
                    value={newRoomDescription}
                    onChange={(e) => setNewRoomDescription(e.target.value)}
                    className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
                    rows={3}
                  />
                </div>
                
                <div className="mb-6">
                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      id="roomPrivate"
                      checked={newRoomPrivate}
                      onChange={(e) => setNewRoomPrivate(e.target.checked)}
                      className="h-4 w-4 text-primary focus:ring-primary border-gray-300 rounded"
                    />
                    <label htmlFor="roomPrivate" className="ml-2 block text-sm text-gray-700">
                      Private Room
                    </label>
                  </div>
                </div>
                
                <div className="flex items-center justify-end space-x-4">
                  <button
                    type="button"
                    onClick={() => setIsCreating(false)}
                    className="text-gray-500 hover:text-gray-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="bg-primary hover:bg-primary-dark text-white font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
                  >
                    Create Room
                  </button>
                </div>
              </form>
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-10">
              <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary"></div>
            </div>
          ) : rooms.length === 0 ? (
            <div className="bg-white shadow rounded-lg p-6 text-center">
              <p className="text-gray-500">No chat rooms available. Create one to get started!</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {rooms.map((room) => (
                <div key={room.id} className="bg-white shadow rounded-lg overflow-hidden">
                  <div className="px-6 py-4">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-lg font-semibold text-gray-800">{room.name}</h3>
                      {room.isPrivate && (
                        <span className="bg-gray-200 text-gray-700 text-xs px-2 py-1 rounded-full">
                          Private
                        </span>
                      )}
                    </div>
                    <p className="text-gray-600 text-sm mb-4">
                      {room.description || 'No description provided'}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">
                        {room.participantCount} participant{room.participantCount !== 1 ? 's' : ''}
                      </span>
                      <button
                        onClick={() => handleJoinRoom(room.id)}
                        className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-md text-sm"
                      >
                        Join
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
};

export default Dashboard; 