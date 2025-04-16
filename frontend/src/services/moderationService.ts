import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const moderationService = {
  async deleteMessage(token: string, messageId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/chat/messages/${messageId}/delete`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  },

  async muteUser(token: string, roomId: string, userId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/chat/rooms/${roomId}/mute/${userId}`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  },

  async unmuteUser(token: string, roomId: string, userId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/chat/rooms/${roomId}/unmute/${userId}`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  },

  async promoteToModerator(token: string, roomId: string, userId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/chat/rooms/${roomId}/moderators/${userId}`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  }
};

export default moderationService; 