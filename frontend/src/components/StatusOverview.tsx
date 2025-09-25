import React from 'react';
import {
  Paper,
  Typography,
  Grid,
  Chip,
  CircularProgress,
  Alert,
  Button,
  Box,
} from '@mui/material';
import PowerSettingsNewIcon from '@mui/icons-material/PowerSettingsNew';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
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
        // We don't need to wait for a response, as the server will be shutting down.
        apiClient.post('/bot/shutdown');
        alert('Shutdown signal sent to backend. You may need to refresh the page later.');
      } catch (err) {
        // This part may not even be reached if the server shuts down immediately.
        console.error('Failed to send shutdown signal', err);
      }
    }
  };

  if (loading && !status) {
    return <CircularProgress />;
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (!status) {
    return <Typography>No status data available.</Typography>;
  }

  return (
    <Paper sx={{ p: 2 }}>
      <Grid container spacing={2} alignItems="center">
        <Grid size={{ xs: 12, md: 4 }}>
          <Typography variant="subtitle2" color="text.secondary">
            Account Value
          </Typography>
          <Typography variant="h5" component="div" fontWeight="bold">
            ${status.account.total_value.toFixed(2)}
          </Typography>
        </Grid>
        <Grid size={{ xs: 12, md: 4 }}>
          <Typography variant="subtitle2" color="text.secondary">
            Bot Status
          </Typography>
          <Chip
            icon={status.running ? <PlayCircleOutlineIcon /> : <PowerSettingsNewIcon />}
            label={status.running ? 'Running' : 'Stopped'}
            color={status.running ? 'success' : 'error'}
            sx={{ mt: 1, fontWeight: 'bold' }}
          />
        </Grid>
        <Grid size={{ xs: 12, md: 4 }} sx={{ textAlign: { xs: 'left', md: 'right' }, mt: { xs: 2, md: 0 } }}>
          <Box>
            <Button
              variant="contained"
              color="success"
              onClick={handleStart}
              disabled={status.running}
              sx={{ mr: 1 }}
            >
              Start
            </Button>
            <Button
              variant="contained"
              color="error"
              onClick={handleStop}
              disabled={!status.running}
              sx={{ mr: 1 }}
            >
              Stop
            </Button>
            <Button
              variant="outlined"
              color="error"
              onClick={handleShutdown}
            >
              Shutdown Backend
            </Button>
          </Box>
        </Grid>
      </Grid>
    </Paper>
  );
};

export default StatusOverview;
