import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface Stream {
  id: string;
  title: string;
  description: string | null;
  room_id: string;
  owner_id: string;
  stream_key: string;
  rtmp_url: string | null;
  playlist_url: string | null;
  status: 'offline' | 'live' | 'ended';
  is_recorded: boolean;
  recording_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface StreamWithDetails extends Stream {
  viewer_count: number;
  owner_username: string;
}

export interface CreateStreamRequest {
  title: string;
  description?: string;
  room_id: string;
  is_recorded?: boolean;
}

export interface UploadUrlResponse {
  upload_url: string;
  download_url: string;
}

const streamService = {
  async createStream(token: string, data: CreateStreamRequest): Promise<Stream> {
    const response = await axios.post<Stream>(
      `${API_URL}/api/streams`,
      data,
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async getStreams(token: string, roomId?: string): Promise<StreamWithDetails[]> {
    const url = roomId 
      ? `${API_URL}/api/streams?room_id=${roomId}`
      : `${API_URL}/api/streams`;
    
    const response = await axios.get<StreamWithDetails[]>(url, {
      headers: {
        Authorization: `Bearer ${token}`
      }
    });
    return response.data;
  },

  async getStream(token: string, streamId: string): Promise<StreamWithDetails> {
    const response = await axios.get<StreamWithDetails>(
      `${API_URL}/api/streams/${streamId}`,
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async startStream(token: string, streamId: string): Promise<Stream> {
    const response = await axios.post<Stream>(
      `${API_URL}/api/streams/${streamId}/start`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async endStream(token: string, streamId: string): Promise<Stream> {
    const response = await axios.post<Stream>(
      `${API_URL}/api/streams/${streamId}/end`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async joinStream(token: string, streamId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/streams/${streamId}/join`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  },

  async leaveStream(token: string, streamId: string): Promise<void> {
    await axios.post(
      `${API_URL}/api/streams/${streamId}/leave`,
      {},
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
  },

  async getUploadUrl(token: string, filename: string): Promise<UploadUrlResponse> {
    const response = await axios.get<UploadUrlResponse>(
      `${API_URL}/api/streams/upload-url?filename=${encodeURIComponent(filename)}`,
      {
        headers: {
          Authorization: `Bearer ${token}`
        }
      }
    );
    return response.data;
  },

  async uploadFileToPresignedUrl(uploadUrl: string, file: File): Promise<void> {
    await axios.put(uploadUrl, file, {
      headers: {
        'Content-Type': file.type
      }
    });
  }
};

export default streamService; 