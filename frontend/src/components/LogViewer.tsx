import React, { useEffect, useRef } from 'react';
import { Paper, Typography, Box, Chip } from '@mui/material';
import { useLogStream } from '../hooks/useLogStream';
import AnsiToHtml from 'ansi-to-html';

const LogViewer: React.FC = () => {
  const { logs, isConnected } = useLogStream();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Initialize the converter
  const convert = React.useMemo(
    () =>
      new AnsiToHtml({
        fg: '#FFF',
        bg: '#000',
        newline: true,
        escapeXML: true, // 建議加這個，避免 XSS
      }),
    []
  );

  useEffect(() => {
    // Auto-scroll to the bottom
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <Paper sx={{ p: 2, display: 'flex', flexDirection: 'column', height: '400px' }}>
      <Box sx={{ bgcolor: 'grey.900', color: '#e5e7eb', p: 2, borderRadius: 1, mb: 1 }}>
        <Typography variant="h6" gutterBottom>
          實時日誌
        </Typography>
        <Chip
          label={isConnected ? 'Connected' : 'Disconnected'}
          color={isConnected ? 'success' : 'error'}
          size="small"
        />
      </Box>
      <Box
        ref={scrollRef}
        className="log-container"
        sx={{
          flexGrow: 1,
          overflowY: 'auto',
          bgcolor: 'grey.900',
          p: 2,
          borderRadius: 1,
          fontFamily: 'monospace',
          fontSize: '0.875rem',
          color: 'white',
        }}
      >
        {logs.map((log, index) => (
          <div key={index} dangerouslySetInnerHTML={{ __html: convert.toHtml(log) }} />
        ))}
      </Box>
    </Paper>
  );
};

export default LogViewer;
