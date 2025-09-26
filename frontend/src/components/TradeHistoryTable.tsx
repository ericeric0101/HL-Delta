import React, { useState, useEffect } from 'react';
import { 
    Table, 
    TableBody, 
    TableCell, 
    TableContainer, 
    TableHead, 
    TableRow, 
    Paper, 
    CircularProgress, 
    Box, 
    Typography, 
    Pagination 
} from '@mui/material';
import { getTradeHistory, Trade } from '../api/statusService';

const TradeHistoryTable: React.FC = () => {
    const [trades, setTrades] = useState<Trade[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [page, setPage] = useState<number>(1);
    const [totalPages, setTotalPages] = useState<number>(0);

    const fetchHistory = async (currentPage: number) => {
        setLoading(true);
        try {
            const response = await getTradeHistory(currentPage, 15); // Fetch 15 items per page
            setTrades(response.trades);
            setTotalPages(response.totalPages);
        } catch (error) {
            console.error("Failed to fetch trade history:", error);
        }
        setLoading(false);
    };

    useEffect(() => {
        fetchHistory(page);
    }, [page]);

    const handlePageChange = (event: React.ChangeEvent<unknown>, value: number) => {
        setPage(value);
    };

    if (loading) {
        return (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '400px' }}>
                <CircularProgress />
            </Box>
        );
    }

    return (
        <Box sx={{ p: 3 }}>
            <Typography variant="h5" gutterBottom>交易紀錄</Typography>
            <TableContainer component={Paper}>
                <Table sx={{ minWidth: 650 }} aria-label="trade history table">
                    <TableHead>
                        <TableRow>
                            <TableCell>時間</TableCell>
                            <TableCell>幣種</TableCell>
                            <TableCell>市場</TableCell>
                            <TableCell>方向</TableCell>
                            <TableCell>類型</TableCell>
                            <TableCell align="right">價格</TableCell>
                            <TableCell align="right">數量</TableCell>
                            <TableCell>訂單狀態</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {trades.length > 0 ? trades.map((trade) => (
                            <TableRow key={trade.id}>
                                <TableCell>{new Date(trade.timestamp).toLocaleString()}</TableCell>
                                <TableCell>{trade.coin}</TableCell>
                                <TableCell>{trade.market}</TableCell>
                                <TableCell sx={{ color: trade.side === 'buy' ? 'success.main' : 'error.main' }}>
                                    {trade.side === 'buy' ? '買入' : '賣出'}
                                </TableCell>
                                <TableCell>{trade.operation_type}</TableCell>
                                <TableCell align="right">{trade.price.toFixed(4)}</TableCell>
                                <TableCell align="right">{trade.size}</TableCell>
                                <TableCell>{trade.order_status}</TableCell>
                            </TableRow>
                        )) : (
                            <TableRow>
                                <TableCell colSpan={8} align="center">沒有可用的交易紀錄</TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </TableContainer>
            {totalPages > 1 && (
                <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
                    <Pagination count={totalPages} page={page} onChange={handlePageChange} color="primary" />
                </Box>
            )}
        </Box>
    );
};

export default TradeHistoryTable;
