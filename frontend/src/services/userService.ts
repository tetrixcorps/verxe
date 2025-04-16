import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export interface AnalyticsData {
    total_streams: number;
    total_sessions: number;
    total_watch_time_seconds: number;
    total_peak_viewers: number;
    total_unique_viewers: number;
    streams_summary: StreamSummary[];
}

export interface StreamSummary {
    id: string;
    title: string;
    created_at: string;
    session_count: number;
    total_duration_seconds: number;
    peak_viewers: number;
}

const userService = {
    async getMyAnalytics(token: string): Promise<AnalyticsData> {
        const response = await axios.get<AnalyticsData>(
            `${API_URL}/api/users/me/analytics`,
            {
                headers: {
                    Authorization: `Bearer ${token}`
                }
            }
        );
        return response.data;
    }
    // Potentially add other user-related service methods here if needed
};

export default userService; 