import React from 'react';
import {
  Grid,
  AppBar,
  Toolbar,
  Typography,
  Container,
  CssBaseline,
  Box,
  Paper,
  CircularProgress,
  Alert,
} from '@mui/material';
import StatusOverview from '../components/StatusOverview';
import PositionsTable from '../components/PositionsTable';
import ConfigManager from '../components/ConfigManager';
import LogViewer from '../components/LogViewer';
import { useBotStatus } from '../hooks/useBotStatus';

const Dashboard: React.FC = () => {
  const { status, error, loading, refresh } = useBotStatus();

  return (
    <Box sx={{ display: 'flex' }}>
      <CssBaseline />
      <AppBar position="fixed" color="default" elevation={1}>
        <Toolbar>
          <Typography variant="h6" noWrap component="div" sx={{ fontWeight: 600 }}>
            Delta Bot Dashboard
          </Typography>
        </Toolbar>
      </AppBar>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          bgcolor: 'background.default',
          p: 3,
          mt: '64px',
        }}
      >
        <Container maxWidth="xl">
          <Grid container spacing={3}>
            {/* Bot Status / Controls */}
            <Grid size={{ xs: 12, md: 4 }}>
              <StatusOverview status={status} error={error} loading={loading} refresh={refresh} />
            </Grid>

            {/* Current Positions */}
            <Grid size={{ xs: 12, md: 8 }}>
              <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', height: '100%' }}>
                <Typography variant="h6" gutterBottom fontWeight={600}>
                  Current Positions
                </Typography>
                {loading && !status ? (
                  <CircularProgress />
                ) : error ? (
                  <Alert severity="error">{error}</Alert>
                ) : status ? (
                  <PositionsTable positions={status.positions} />
                ) : (
                  <Typography>No data available.</Typography>
                )}
              </Paper>
            </Grid>

            {/* Config Manager */}
            <Grid size={{ xs: 12, md: 4 }}>
              <ConfigManager />
            </Grid>

            {/* Logs */}
            <Grid size={{ xs: 12, md: 8 }}>
              <LogViewer />
            </Grid>
          </Grid>
        </Container>
      </Box>
    </Box>
  );
};

export default Dashboard;
