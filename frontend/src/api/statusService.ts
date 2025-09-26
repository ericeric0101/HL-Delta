import apiClient from './client';

export interface Trade {
  id: number;
  timestamp: string;
  coin: string;
  market: 'spot' | 'perp';
  side: 'buy' | 'sell';
  price: number;
  size: number;
  order_id: number;
  order_status: string;
  operation_type: string;
}

export interface TradeHistoryResponse {
  trades: Trade[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

export const getTradeHistory = async (page: number = 1, limit: number = 15): Promise<TradeHistoryResponse> => {
  try {
    const response = await apiClient.get('/status/trade-history', {
      params: { page, limit },
    });
    return response.data;
  } catch (error) {
    console.error("Error fetching trade history:", error);
    // Return a default/empty response on error to prevent crashes
    return {
      trades: [],
      total: 0,
      page: 1,
      limit: 15,
      totalPages: 0,
    };
  }
};
