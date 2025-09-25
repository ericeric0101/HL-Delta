// src/theme.ts
import { createTheme } from '@mui/material/styles';

const theme = createTheme({
  palette: {
    mode: 'light',
    background: {
      default: '#f5f7fb',   // 頁面淺灰底
      paper: '#ffffff',     // 卡片白底
    },
    text: {
      primary: 'rgba(0,0,0,0.87)',
      secondary: 'rgba(0,0,0,0.6)',
    },
    success: { main: '#2e7d32' },   // 綠色 (Start)
    warning: { main: '#f6c443' },   // ⚡ 更亮的黃色 (Stop)
    error: { main: '#d32f2f' },
  },
  shape: { borderRadius: 12 }, // 卡片圓角
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          borderRadius: 12,
          backgroundColor: '#fff',
          color: 'rgba(0,0,0,0.87)',
          boxShadow:
            '0 1px 2px rgba(16,24,40,0.06), 0 1px 3px rgba(16,24,40,0.10)',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          borderRadius: 9999,        // 膠囊形狀
          textTransform: 'none',
          fontWeight: 700,
          paddingInline: 20,
          paddingBlock: 10,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 700 },
      },
    },
  },
});

export default theme;