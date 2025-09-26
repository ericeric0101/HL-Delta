import React, { useState } from 'react';
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
  IconButton,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import StatusOverview from '../components/StatusOverview';
import PositionsTable from '../components/PositionsTable';
import ConfigManager from '../components/ConfigManager';
import LogViewer from '../components/LogViewer';
import TradeHistoryTable from '../components/TradeHistoryTable'; // Import the new component
import { useBotStatus } from '../hooks/useBotStatus';

interface TabPanelProps {
  children?: React.ReactNode;
  index: number;
  value: number;
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`dashboard-tabpanel-${index}`}
      aria-labelledby={`dashboard-tab-${index}`}
      {...other}
    >
      {value === index && (
        <Box sx={{ pt: 3 }}>
          {children}
        </Box>
      )}
    </div>
  );
}

const Dashboard: React.FC = () => {
  const { status, error, loading, refresh } = useBotStatus();
  const [currentTab, setCurrentTab] = useState(0);

  const handleTabChange = (event: React.SyntheticEvent, newValue: number) => {
    setCurrentTab(newValue);
  };

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
          <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
            <Tabs value={currentTab} onChange={handleTabChange} aria-label="dashboard tabs">
              <Tab label="總覽" id="dashboard-tab-0" />
              <Tab label="交易紀錄" id="dashboard-tab-1" />
            </Tabs>
          </Box>

          <TabPanel value={currentTab} index={0}>
            <Grid container spacing={3}>
              {/* Bot Status / Controls */}
              <Grid size={{ xs: 12, md: 4 }}>
                <StatusOverview status={status} error={error} loading={loading} refresh={refresh} />
              </Grid>

              {/* Current Positions */}
              <Grid size={{ xs: 12, md: 8 }}>
                <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', height: '100%' }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="h6" gutterBottom fontWeight={600}>
                      目前持倉
                    </Typography>
                    <IconButton onClick={refresh} disabled={loading} aria-label="refresh positions">
                      <RefreshIcon />
                    </IconButton>
                  </Box>
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
          </TabPanel>

          <TabPanel value={currentTab} index={1}>
            <TradeHistoryTable />
          </TabPanel>

        </Container>
      </Box>
    </Box>
  );
};

export default Dashboard;
