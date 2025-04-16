import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import userService, { AnalyticsData } from '../services/userService';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { format } from 'date-fns'; // For formatting dates
import { formatCompactNumber, formatDuration } from '../utils/formatters'; // Assuming formatters exist

const Analytics: React.FC = () => {
    const navigate = useNavigate();
    const { token } = useAuth();
    const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchAnalytics = async () => {
            if (!token) {
                setError('Authentication token not found.');
                setLoading(false);
                return;
            }
            try {
                setLoading(true);
                const data = await userService.getMyAnalytics(token);
                setAnalytics(data);
                setError(null);
            } catch (err) {
                setError('Failed to fetch analytics data.');
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        fetchAnalytics();
    }, [token]);

    return (
        <div className="min-h-screen bg-gray-100">
            <header className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex justify-between items-center">
                    <h1 className="text-2xl font-bold text-gray-800">Creator Analytics</h1>
                    <button
                        onClick={() => navigate('/dashboard')}
                        className="text-gray-600 hover:text-gray-800"
                    >
                        &larr; Back to Dashboard
                    </button>
                </div>
            </header>

            <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
                {loading && (
                    <div className="flex justify-center items-center py-10">
                        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary"></div>
                    </div>
                )}
                {error && (
                    <div className="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 mb-6" role="alert">
                        <p>{error}</p>
                    </div>
                )}
                {!loading && !error && analytics && (
                    <div className="space-y-6">
                        {/* Summary Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            <Card>
                                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                                    <CardTitle className="text-sm font-medium">Total Streams</CardTitle>
                                    {/* Icon Placeholder */}
                                </CardHeader>
                                <CardContent>
                                    <div className="text-2xl font-bold">{analytics.total_streams}</div>
                                </CardContent>
                            </Card>
                             <Card>
                                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                                    <CardTitle className="text-sm font-medium">Total Unique Viewers</CardTitle>
                                </CardHeader>
                                <CardContent>
                                    <div className="text-2xl font-bold">{formatCompactNumber(analytics.total_unique_viewers)}</div>
                                </CardContent>
                            </Card>
                            <Card>
                                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                                    <CardTitle className="text-sm font-medium">Total Watch Time</CardTitle>
                                </CardHeader>
                                <CardContent>
                                     {/* We need a formatter for seconds to HH:MM:SS */}
                                    <div className="text-2xl font-bold">{formatDuration(analytics.total_watch_time_seconds)}</div>
                                </CardContent>
                            </Card>
                        </div>

                        {/* Streams Summary Table */}
                        <Card>
                            <CardHeader>
                                <CardTitle>Streams Summary</CardTitle>
                            </CardHeader>
                            <CardContent>
                                <Table>
                                    <TableHeader>
                                        <TableRow>
                                            <TableHead>Title</TableHead>
                                            <TableHead>Created Date</TableHead>
                                            <TableHead className="text-right">Sessions</TableHead>
                                            <TableHead className="text-right">Peak Viewers</TableHead>
                                            <TableHead className="text-right">Total Duration</TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {analytics.streams_summary.length > 0 ? (
                                            analytics.streams_summary.map((stream) => (
                                                <TableRow key={stream.id}>
                                                    <TableCell className="font-medium">{stream.title}</TableCell>
                                                    <TableCell>{format(new Date(stream.created_at), 'PP')}</TableCell>
                                                    <TableCell className="text-right">{stream.session_count}</TableCell>
                                                    <TableCell className="text-right">{formatCompactNumber(stream.peak_viewers)}</TableCell>
                                                    <TableCell className="text-right">{formatDuration(stream.total_duration_seconds)}</TableCell>
                                                </TableRow>
                                            ))
                                        ) : (
                                            <TableRow>
                                                <TableCell colSpan={5} className="text-center">No streams found.</TableCell>
                                            </TableRow>
                                        )}
                                    </TableBody>
                                </Table>
                            </CardContent>
                        </Card>
                    </div>
                )}
                 {!loading && !error && !analytics && (
                     <div className="text-center text-gray-500 py-10">No analytics data available.</div>
                 )}
            </main>
        </div>
    );
};

export default Analytics; 