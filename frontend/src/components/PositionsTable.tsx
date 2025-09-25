import React from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Typography,
  Chip,
} from '@mui/material';
import { Position } from '../types';

interface PositionsTableProps {
  positions: Position[];
}

const PositionsTable: React.FC<PositionsTableProps> = ({ positions }) => {
  if (positions.length === 0) {
    return <Typography sx={{ p: 2 }}>No active positions.</Typography>;
  }

  const formatPnl = (pnl: number) => (
    <Typography variant="body2" color={pnl >= 0 ? 'success.main' : 'error.main'} sx={{ fontWeight: '500' }}>
      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
    </Typography>
  );

  return (
    <TableContainer component={Paper} sx={{ boxShadow: 'none' }}>
      <Table sx={{ minWidth: 650 }} aria-label="positions table">
        <TableHead sx={{ bgcolor: 'grey.50' }}>
          <TableRow>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }}>Coin</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }}>Type</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Size</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Entry Price</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Position Value</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Unrealized PNL</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Leverage</TableCell>
            <TableCell sx={{ fontWeight: '600', color: 'text.secondary', border: 0 }} align="right">Liq. Price</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {positions.map((pos) => (
            <TableRow key={`${pos.coin}-${pos.type}`} sx={{ '&:last-child td, &:last-child th': { border: 0 } }}>
              <TableCell component="th" scope="row" sx={{ fontWeight: '500' }}>
                {pos.coin}
              </TableCell>
              <TableCell>
                <Chip
                  label={pos.type}
                  size="small"
                  color={pos.type === 'perp' ? 'primary' : 'secondary'}
                  sx={{ fontWeight: '500' }}
                />
              </TableCell>
              <TableCell align="right">{pos.size.toFixed(4)}</TableCell>
              <TableCell align="right">
                {pos.entry_price ? `$${pos.entry_price.toFixed(4)}` : 'N/A'}
              </TableCell>
              <TableCell align="right">
                {pos.position_value ? `$${pos.position_value.toFixed(2)}` : 'N/A'}
              </TableCell>
              <TableCell align="right">
                {pos.unrealized_pnl ? formatPnl(pos.unrealized_pnl) : 'N/A'}
              </TableCell>
              <TableCell align="right">{pos.leverage ? `${pos.leverage.toFixed(2)}x` : 'N/A'}</TableCell>
              <TableCell align="right">
                {pos.liquidation_price ? `$${pos.liquidation_price.toFixed(2)}` : 'N/A'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
};

export default PositionsTable;
