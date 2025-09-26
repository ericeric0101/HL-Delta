import React from 'react';
import {
  Paper,
  Typography,
  Box,
  Chip,
  CircularProgress,
  Alert,
  Button,
  Stack,
  Grid,
  IconButton,
} from '@mui/material';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import RefreshIcon from '@mui/icons-material/Refresh';
import { BotStatus } from '../types';
import apiClient from '../api/client';

interface Props {
  status: BotStatus | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

const StatusOverview: React.FC<Props> = ({ status, error, loading, refresh }) => {
  const handleStart = async () => {
    try {
      await apiClient.post('/bot/start');
      refresh();
    } catch (err) {
      console.error('Failed to start bot', err);
    }
  };

  const handleStop = async () => {
    try {
      await apiClient.post('/bot/stop');
      refresh();
    } catch (err) {
      console.error('Failed to stop bot', err);
    }
  };

  const handleShutdown = async () => {
    if (window.confirm('Are you sure you want to shut down the entire backend? This will stop the bot and the API server.')) {
      try {
        apiClient.post('/bot/shutdown');
        alert('Shutdown signal sent to backend. You may need to refresh the page later.');
      } catch (err) {
        console.error('Failed to send shutdown signal', err);
      }
    }
  };

  if (loading && !status) return <CircularProgress />;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!status) return <Typography>No status data available.</Typography>;

  const running = status.running;

  return (
    <Grid container spacing={3}>
      {/* 上排：兩張小卡並排（md 以上各佔 6），和你提供的白底布局一致 */}
      <Grid size={{ xs: 12, md: 6 }}>
        <Paper sx={{ p: 2, height: '100%', borderRadius: 1 }}>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
            帳戶總值
          </Typography>
          <Typography variant="h4" fontWeight={700}>
            ${status.account.total_value.toFixed(2)}
          </Typography>
        </Paper>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Paper sx={{ p: 2, height: '100%', borderRadius: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Typography variant="subtitle2" color="text.secondary" gutterBottom>
            Bot 狀態
          </Typography>
          <Chip
            icon={running ? <PlayCircleOutlineIcon /> : <PowerSettingsNewIcon />}
            label={running ? 'Running' : 'Stopped'}
            color={running ? 'success' : 'error'}
            size="medium"
            sx={{ alignSelf: 'flex-start', fontWeight: 700, px: 1.25 }}
          />
        </Paper>
      </Grid>

      {/* 下排：Bot Controls 獨占一整行（xs/md 12） */}
      <Grid size={{ xs: 12 }}>
        <Paper sx={{ p: 2.5, borderRadius: 1 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                    Bot 控制
                </Typography>
                <IconButton onClick={refresh} disabled={loading} aria-label="refresh status">
                    <RefreshIcon />
                </IconButton>
            </Box>

          {/* 水平排列；空間不夠自動換行，不會擠在一起 */}
          <Stack
            direction="row"
            spacing={1.5}
            useFlexGap
            flexWrap="wrap"
          >
            <Button
              variant="contained"
              color="success"
              onClick={handleStart}
              disabled={running}
              sx={{ minWidth: 100 }}
            >
              啟動
            </Button>

            <Button
              variant="contained"
              color="warning"
              onClick={handleStop}
              disabled={!running}
              sx={{ minWidth: 100 }}
            >
              終止
            </Button>

            <Button
              variant="contained"
              color="error"
              onClick={handleShutdown}
              sx={{ minWidth: 100 }}
            >
              關閉後端
            </Button>
          </Stack>
        </Paper>
      </Grid>
    </Grid>
  );
};

export default StatusOverview;