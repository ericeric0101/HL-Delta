#!/usr/bin/env python3
"""
HL-Delta: Automated trading system for Hyperliquid
"""

import os
import logging
import asyncio
import time
import json
import math
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
import eth_account
from eth_account.signers.local import LocalAccount
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any, Tuple
from datetime import datetime
from enum import Enum, auto
import uuid
from api.utils.db_logger import db_logger

# ANSI color codes for colored terminal output
class Colors:
    RESET = "\033[0m"
    RED = "\033[91m"     # Error messages
    GREEN = "\033[92m"   # Success messages
    YELLOW = "\033[93m"  # Warnings and important highlights
    BLUE = "\033[94m"    # Info messages
    BOLD = "\033[1m"     # Bold text for headers

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("delta.log")
    ]
)
logger = logging.getLogger("HL-Delta")


@dataclass
class SpotMarket:
    name: str
    token_id: str
    index: int
    sz_decimals: int
    wei_decimals: int
    is_canonical: bool
    full_name: str
    evm_contract: Optional[Dict] = None
    deployer_trading_fee_share: str = "0.0"
    position: Dict[str, Any] = field(default_factory=dict)
    tick_size: float = 0

@dataclass
class PerpMarket:
    name: str
    sz_decimals: int
    max_leverage: int
    index: int
    position: Dict[str, Any] = field(default_factory=dict)
    funding_rate: Optional[float] = None
    yearly_funding_rate: Optional[float] = None
    tick_size: float = 0

@dataclass
class CoinInfo:
    name: str
    spot: Optional[SpotMarket] = None
    perp: Optional[PerpMarket] = None


class PositionState(Enum):
    EMPTY = auto()
    OPENING_SPOT = auto()
    OPENING_PERP = auto()
    OPENING_HEDGE = auto()
    DELTA_NEUTRAL = auto()
    ONE_LEG_SPOT_ONLY = auto()
    ONE_LEG_PERP_ONLY = auto()
    REBALANCING = auto()
    CLOSING = auto()
    ERROR_RECOVERY = auto()


@dataclass
class PositionSnapshot:
    coin: str
    spot_size: float
    perp_size: float
    spot_notional: float
    perp_notional: float
    delta_pct: float
    spot_price: float
    perp_price: float


@dataclass
class OrderGroup:
    group_id: str
    coin: str
    intent: str
    market: str
    oids: List[int] = field(default_factory=list)
    created_ts: float = field(default_factory=time.time)
    last_status: Optional[str] = None
    side: str = ""
    qty: float = 0.0
    price: float = 0.0
    needs_fallback: bool = False


@dataclass
class PendingDeltaOrder:
    coin_name: str
    spot_oid: Optional[int] = None
    perp_oid: Optional[int] = None
    creation_time: float = field(default_factory=time.time)
    last_check_time: float = field(default_factory=time.time)
    spot_filled: bool = False
    perp_filled: bool = False
    max_wait_time: int = 60  # 1 minute in seconds
    relist_count: int = 0
    is_closing_position: bool = False  # Flag to indicate if this is for closing a position


class Delta:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        try:
            self.tracked_coins = self.config["general"]["tracked_coins"]
            self.coins: Dict[str, CoinInfo] = {}
            self.pending_orders: List[PendingDeltaOrder] = []
            self._is_running = False
            self.state: PositionState = PositionState.EMPTY
            self.active_coin: Optional[str] = None
            self.last_state_change: float = time.time()
            self.order_groups: Dict[str, OrderGroup] = {}
            self.last_rebalance_ts: float = 0.0
            self.last_entry_ts: Optional[float] = None
            self.last_replace_ts: Optional[float] = None
            self.funding_cache: Dict[str, float] = {}
            self.funding_ema: Dict[str, float] = {}
            self._last_funding_refresh: float = 0.0
            self._last_position_refresh: float = 0.0
            self._last_heartbeat: float = 0.0
            self._active_order_group: Optional[str] = None
            self._retry_counters: Dict[str, int] = {}
            self.min_qty: float = 0.0
            self.qty_step: float = 0.0
            self.price_tick: float = 0.0
            self.slippage_cap_bps: float = 0.0
            self.fee_bps: float = 0.0
            self.delta_threshold_pct: float = 5.0
            self.min_rebalance_interval_sec: float = 5.0
            self.max_retries: int = 3
            self.heartbeat_sec: float = 3.0
            self.use_post_only_for_entry: bool = True
            self.use_post_only_for_hedge: bool = False
            self.rebalance_order_type: str = "passive_then_ioc"
            self.funding_use_ema: bool = True
            self.funding_ema_alpha: float = 0.3
            self.funding_refresh_sec: float = 60.0
            self.min_hold_minutes: float = 60.0
            self.cooldown_after_replace_minutes: float = 30.0
            
            if self.config["general"].get("debug", False):
                logger.setLevel(logging.DEBUG)
                logger.debug("偵錯模式已啟用")
            
            private_key = self._get_required_env("HYPERLIQUID_PRIVATE_KEY")
            self.address = self._get_required_env("HYPERLIQUID_ADDRESS")
            
            self.account: LocalAccount = eth_account.Account.from_key(private_key)
            self.exchange = Exchange(self.account, constants.MAINNET_API_URL)
            self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
            self.api_url = constants.MAINNET_API_URL
            
            self.user_state = {}
            self.spot_user_state = {}
            self.margin_summary = {}
            self.perp_user_state = 0
            self.account_value = 0
            self.spot_account_value = 0
            self.margin_account_value = 0
            self.total_raw_usd = 0
            self.total_margin_used = 0

        except Exception as e:
            logger.error(f"初始化客戶端失敗: {e}", exc_info=True)
            raise RuntimeError("客戶端初始化失敗") from e

    async def initialize(self):
        """Performs asynchronous setup tasks after construction."""
        try:
            await self._initial_load()
        except Exception as e:
            logger.error(f"初始化客戶端失敗: {e}", exc_info=True)
            raise RuntimeError("客戶端初始化失敗") from e

    async def _initial_load(self):
        """Loads all initial market data and user states."""
        logger.info("正在載入市場資料與帳戶狀態...")
        self.user_state = self.info.user_state(self.address)
        self.spot_user_state = self.info.spot_user_state(self.address)
        self.margin_summary = self.user_state["marginSummary"]

        spot_meta = self.info.spot_meta()
        spot_coins = spot_meta["tokens"]
        perp_meta = self.info.meta()
        perp_coins = perp_meta["universe"]
        
        for coin_name in self.tracked_coins:
            self.coins[coin_name] = CoinInfo(name=coin_name)
            spot_market_found = False
            for spot_coin in spot_coins:
                spot_name = spot_coin["name"]
                normalized_name = spot_name.lstrip('U') if spot_name.startswith('U') else spot_name
                if coin_name == spot_name or coin_name == normalized_name:
                    self.coins[coin_name].spot = SpotMarket(
                        name=spot_name,
                        token_id=spot_coin["tokenId"],
                        index=spot_coin["index"],
                        sz_decimals=spot_coin["szDecimals"],
                        wei_decimals=spot_coin["weiDecimals"],
                        is_canonical=spot_coin["isCanonical"],
                        full_name=spot_coin["fullName"],
                        evm_contract=spot_coin.get("evmContract"),
                        deployer_trading_fee_share=spot_coin["deployerTradingFeeShare"],
                        tick_size=spot_coin.get("tickSize", 0.001)
                    )
                    if coin_name == "BTC":
                        self.coins[coin_name].spot.tick_size = 1
                    elif coin_name == "ETH":
                        self.coins[coin_name].spot.tick_size = 0.1
                    elif coin_name == "SOL":
                        self.coins[coin_name].spot.tick_size = 0.001
                    spot_market_found = True
                    break
            
            if spot_market_found:
                for perp_coin in perp_coins:
                    if perp_coin["name"] == coin_name:
                        self.coins[coin_name].perp = PerpMarket(
                            name=perp_coin["name"],
                            sz_decimals=perp_coin["szDecimals"],
                            max_leverage=perp_coin["maxLeverage"],
                            index=perp_coins.index(perp_coin),
                            tick_size=self.coins[coin_name].spot.tick_size
                        )
                        break
            
            if not self.coins[coin_name].spot or not self.coins[coin_name].perp:
                logger.warning(f"'{coin_name}' 的市場配對不完整 (現貨: {"有" if self.coins[coin_name].spot else "無"}, 合約: {"有" if self.coins[coin_name].perp else "無"})，將無法交易。")

        self.spot_allocation_pct = self.config["allocation"]["spot_pct"] / 100.0
        self.perp_allocation_pct = self.config["allocation"]["perp_pct"] / 100.0
        self.rebalance_threshold = self.config["allocation"]["rebalance_threshold"]

        trading_cfg = self.config.get("trading", {})
        self.refresh_interval_sec = float(trading_cfg.get("refresh_interval_sec", 60))
        self.heartbeat_sec = max(float(trading_cfg.get("heartbeat_sec", 3)), 1.0)
        self.min_spot_balance_to_open = float(trading_cfg.get("min_spot_balance_to_open", 50))
        self.target_perp_leverage = max(float(trading_cfg.get("target_perp_leverage", 1.0)), 0.1)
        self.delta_threshold_pct = float(trading_cfg.get("delta_threshold_pct", 5.0))
        self.min_rebalance_interval_sec = float(trading_cfg.get("min_rebalance_interval_sec", 5))
        self.max_retries = max(int(trading_cfg.get("max_retries", 3)), 1)
        self.slippage_cap_bps = float(trading_cfg.get("slippage_cap_bps", 15))
        self.fee_bps = float(trading_cfg.get("fee_bps", 2))
        self.min_qty = float(trading_cfg.get("min_qty", 0))
        self.price_tick = float(trading_cfg.get("price_tick", 0))
        self.qty_step = float(trading_cfg.get("qty_step", 0))
        self.funding_refresh_sec = max(float(trading_cfg.get("funding_refresh_sec", 60)), 5.0)
        self.funding_use_ema = bool(trading_cfg.get("funding_use_ema", True))
        self.funding_ema_alpha = float(trading_cfg.get("funding_ema_alpha", 0.3))
        self.funding_check_minute = int(trading_cfg.get("funding_check_minute", 50))
        self.funding_open_threshold_pct = float(trading_cfg.get("funding_open_threshold_pct", 5.0))
        self.funding_replace_threshold_pct = float(
            trading_cfg.get("funding_replace_threshold_pct", self.funding_open_threshold_pct)
        )
        self.min_hold_minutes = float(trading_cfg.get("min_hold_minutes", 60))
        self.cooldown_after_replace_minutes = float(trading_cfg.get("cooldown_after_replace_minutes", 30))
        self.use_post_only_for_entry = bool(trading_cfg.get("use_post_only_for_entry", True))
        self.use_post_only_for_hedge = bool(trading_cfg.get("use_post_only_for_hedge", False))
        self.rebalance_order_type = trading_cfg.get("rebalance_order_type", "passive_then_ioc")

        self._log_runtime_config()
        
        await self._update_positions()
        logger.info(f"已使用帳戶初始化: {self.address[:8]}...")
        logger.info(f"總帳戶價值 (現貨 + 合約): ${self.account_value:.2f}")
    async def _log_filled_trade(self, oid: int, operation_type: str):
        """Queries the details of a filled order by its OID and logs it to the database."""
        try:
            order_status = self.info.query_order_by_oid(self.address, oid)
            order_info = order_status.get('order') if isinstance(order_status, dict) else None

            if not order_info or order_info.get('status') != 'filled':
                logger.warning(f"試圖記錄訂單 {oid}，但其狀態不是 'filled'。將略過記錄。")
                return

            coin = order_info.get('coin')
            if not coin:
                logger.error(f"訂單 {oid} 缺少 'coin' 欄位，無法記錄 Supabase 日誌。原始資料: {order_info}")
                return

            # Handle asset id strings like '@107' returned by Hyperliquid
            if isinstance(coin, str) and coin.startswith('@'):
                asset_id_str = coin.lstrip('@')
                resolved_coin = None
                asset_to_name = getattr(self.info, 'asset_to_name', None)
                if asset_to_name:
                    try:
                        resolved_coin = asset_to_name.get(int(asset_id_str))
                    except (ValueError, TypeError):
                        resolved_coin = None
                if not resolved_coin:
                    # Fallback using inverse of name_to_asset if available
                    name_to_asset = getattr(self.info, 'name_to_asset', None)
                    if name_to_asset:
                        inverse_map = {str(v).lstrip('@'): k for k, v in name_to_asset.items()}
                        resolved_coin = inverse_map.get(asset_id_str)
                if resolved_coin:
                    coin = resolved_coin
                else:
                    logger.warning(f"無法將資產編號 {coin} 解析為幣種名稱，Supabase 將記錄原始值。")

            is_spot = order_info.get('isSpot', False)
            market = 'spot' if is_spot else 'perp'

            side_field = order_info.get('side')
            side = 'buy'
            if isinstance(side_field, str):
                side_code = side_field.upper()
                if side_code in ('B', 'BUY'):
                    side = 'buy'
                elif side_code in ('S', 'SELL', 'A'):
                    # Hyperliquid 回傳 'A' 代表 Ask (賣單)
                    side = 'sell'
                else:
                    side = 'buy'
            elif isinstance(side_field, bool):
                side = 'buy' if side_field else 'sell'

            timestamp_ms = order_info.get('timestamp') or order_info.get('t')
            if not timestamp_ms:
                timestamp_iso = datetime.utcnow().isoformat()
            else:
                timestamp_iso = datetime.fromtimestamp(timestamp_ms / 1000).isoformat()

            avg_fill_price = order_info.get('avgFillPx') or order_info.get('avgPx') or order_info.get('px')
            filled_size = order_info.get('sz') or order_info.get('size')

            try:
                avg_fill_price = float(avg_fill_price) if avg_fill_price is not None else 0.0
            except (TypeError, ValueError):
                avg_fill_price = 0.0

            try:
                filled_size = float(filled_size) if filled_size is not None else 0.0
            except (TypeError, ValueError):
                filled_size = 0.0

            if filled_size <= 0:
                logger.debug(f"訂單 {oid} 的成交數量為 0，跳過 Supabase 紀錄。原始資料: {order_info}")
                return

            trade_data = {
                'timestamp': timestamp_iso,
                'coin': coin,
                'market': market,
                'side': side,
                'price': avg_fill_price,
                'size': filled_size,
                'order_id': oid,
                'order_status': 'filled',
                'operation_type': operation_type,
                'raw_response': json.dumps(order_status)
            }

            db_logger.log_trade(trade_data)

        except Exception as e:
            logger.error(f"記錄已成交訂單 {oid} 時發生錯誤: {e}", exc_info=True)

    async def _finalize_successful_execution(
        self,
        coin_name: str,
        spot_oid: Optional[int],
        perp_oid: Optional[int],
        operation_type: str,
    ):
        """Refresh cached positions and record successful trades."""
        try:
            await self._update_positions()
            logger.info(f"{coin_name} 的持倉狀態已更新。")
        except Exception as e:
            logger.error(f"{coin_name} 的持倉狀態更新失敗: {e}", exc_info=True)

        for oid in (spot_oid, perp_oid):
            if oid:
                await self._log_filled_trade(oid, operation_type)

    def _log_order_submission(
        self,
        coin_name: str,
        market: str,
        side: str,
        size: float,
        price: float,
        result: Optional[dict],
        context: str,
    ) -> None:
        """Log the outcome of an order submission for easier troubleshooting."""
        try:
            status = result.get("status") if isinstance(result, dict) else None
            response = result.get("response", {}) if isinstance(result, dict) else {}
            oid = None
            state = "unknown"
            error_msg = None

            if status == "ok":
                statuses = response.get("data", {}).get("statuses", [])
                if statuses:
                    raw_status = statuses[0]
                    if "filled" in raw_status:
                        state = "filled"
                        oid = int(raw_status["filled"].get("oid", 0))
                    elif "resting" in raw_status:
                        state = "resting"
                        oid = int(raw_status["resting"].get("oid", 0))
                    elif "error" in raw_status:
                        state = "error_response"
                        error_msg = raw_status.get("error")
                    else:
                        state = "accepted"
                logger.info(
                    f"訂單提交成功 [{context}] - 幣種:{coin_name} 市場:{market} 方向:{side} 數量:{size} 價格:{price} 狀態:{state} OID:{oid}"
                )
                if error_msg:
                    logger.error(f"訂單提交回傳錯誤訊息: {error_msg}")
            else:
                error_msg = response or result
                logger.error(
                    f"訂單提交失敗 [{context}] - 幣種:{coin_name} 市場:{market} 方向:{side} 數量:{size} 價格:{price}，回傳: {error_msg}"
                )
        except Exception as e:
            logger.error(f"記錄訂單提交結果時發生錯誤: {e}", exc_info=True)


    def _get_required_env(self, env_name):
        """Get a required environment variable or raise an informative error."""
        value = os.getenv(env_name)
        if not value or value == "your_private_key_here" or value == "your_eth_address_here":
            raise ValueError(f"{env_name} 環境變數未設定或仍為預設值")
        return value

    def _load_config(self):
        """Load configuration from config.json"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"已從 {self.config_path} 載入設定")
                return config
        except FileNotFoundError:
            logger.error(f"找不到設定檔 {self.config_path}")
            raise
        except json.JSONDecodeError:
            logger.error(f"解析 {self.config_path} 的 JSON 時發生錯誤")
            raise
        except Exception as e:
            logger.error(f"載入設定時發生未預期的錯誤: {e}")
            raise
        
    def _get_total_usdc_balance(self):
        """Get the total USDC balance across both spot and perp accounts."""
        spot_usdc = self._get_spot_account_USDC()
        
        # Get perp account USDC balance (margin)
        perp_usdc = 0
        for asset in self.user_state.get("crossAssetPositions", []):
            if asset.get("position", {}).get("coin") == "USDC":
                perp_usdc = float(asset.get("position", {}).get("szi", 0))
                break
        
        total_usdc = spot_usdc + perp_usdc
        logger.debug(f"總 USDC 餘額: {total_usdc} (現貨: {spot_usdc}, 永續: {perp_usdc})")
        return total_usdc

    def _get_spot_account_USDC(self):
        if not self.spot_user_state:
            self.spot_user_state = self.info.spot_user_state(self.address)
        for balance in self.spot_user_state.get("balances", []):
            if balance.get("coin") == "USDC":
                return float(balance.get("total", 0))
        return 0
    
    def _get_spot_price(self, coin_name):
        mid_price = self.info.all_mids()
        for key, value in mid_price.items():
            if key == coin_name:
                return float(value)
        return 0
    
    def _get_perp_price(self, coin_name):
        mid_price = self.info.all_mids()
        for key, value in mid_price.items():
            if key == coin_name:
                return float(value)
        return 0

    def _get_filled_size_from_oid(self, oid: Optional[int]) -> Optional[float]:
        if not oid:
            return None
        try:
            order_status = self.info.query_order_by_oid(self.address, oid)
            order_info = order_status.get('order') if isinstance(order_status, dict) else None
            if not order_info:
                return None

            orig_sz = order_info.get('origSz')
            remaining_sz = order_info.get('sz')
            filled_sz = order_info.get('filledSz') or order_info.get('totalFilledSz')

            def to_float(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            orig_sz = to_float(orig_sz)
            remaining_sz = to_float(remaining_sz)
            filled_sz = to_float(filled_sz)

            if orig_sz is not None and remaining_sz is not None:
                return max(orig_sz - remaining_sz, 0.0)
            if filled_sz is not None:
                return max(filled_sz, 0.0)
        except Exception as e:
            logger.debug(f"查詢訂單 {oid} 的成交數量失敗: {e}")
        return None

    def _get_emergency_price(self, coin_name: str, is_buy: bool, is_spot: bool) -> float:
        """Fetch a price that is likely to execute immediately for rollback purposes."""
        price = 0.0
        try:
            book = self.info.l2_snapshot(coin_name)
            levels = book.get("levels", []) if isinstance(book, dict) else []
            if levels and len(levels) >= 2:
                best_bid = float(levels[0][0]['px']) if levels[0] else 0.0
                best_ask = float(levels[1][0]['px']) if levels[1] else 0.0
                price = best_ask if is_buy else best_bid
        except Exception as e:
            logger.warning(f"取得 {coin_name} 訂單簿失敗，改用中間價回退: {e}")

        if price <= 0:
            price = self._get_spot_price(coin_name) if is_spot else self._get_perp_price(coin_name)

        if price <= 0:
            # 當仍無法取得合理價格時，使用保守預設值避免送出無效訂單
            price = 1.0

        # 為確保 Ioc 訂單能成交，買單略微抬價、賣單略微降價
        adjustment = 1.01 if is_buy else 0.99
        return price * adjustment
    
    def round_size(self, coin_name: str, is_spot: bool, size: float) -> float:
        if size <= 0:
            return 0
        decimals = 8
        if coin_name in self.coins:
            if is_spot and self.coins[coin_name].spot:
                decimals = self.coins[coin_name].spot.sz_decimals
            elif not is_spot and self.coins[coin_name].perp:
                decimals = self.coins[coin_name].perp.sz_decimals

        rounded = round(size, decimals)
        step = self.qty_step if self.qty_step > 0 else None
        if step:
            rounded = math.floor(rounded / step) * step
        if self.min_qty > 0 and rounded < self.min_qty:
            return 0
        return max(rounded, 0)
    
    def round_price(self, coin_name: str, price: float) -> float:
        if coin_name not in self.coins:
            return price
            
        tick_size = self.coins[coin_name].spot.tick_size
        if tick_size <= 0:
            return price
            
        return round(price / tick_size) * tick_size
    
    def _calculate_optimal_spot_size(self, coin_name):
        # Get the latest L1 price for accurate calculation
        try:
            l2_book = self.info.l2_snapshot(coin_name)
            if not l2_book or not l2_book["levels"][0]:
                logger.warning(f"無法取得 {coin_name} 的 L2 訂單簿來計算最佳規模，將使用中間價。")
                price = self._get_spot_price(coin_name)
            else:
                price = float(l2_book["levels"][0][0]['px']) # Use best bid for a more conservative size calculation
        except Exception as e:
            logger.error(f"計算最佳規模時獲取價格出錯: {e}，將使用中間價。")
            price = self._get_spot_price(coin_name)

        if price <= 0:
            logger.error(f"無法為 {coin_name} 取得有效價格以計算規模。")
            return 0

        # Use the available USDC in the spot account as the basis for our position size.
        min_balance_threshold = getattr(self, "min_spot_balance_to_open", 50.0)
        target_perp_leverage = getattr(self, "target_perp_leverage", 1.0)

        available_usdc = self._get_spot_account_USDC()

        if available_usdc < min_balance_threshold:
            logger.info(
                f"現貨 USDC 餘額 ${available_usdc:.2f} 低於開倉保留閾值 ${min_balance_threshold:.2f}，跳過計算。"
            )
            return 0

        usable_usdc = max(0, available_usdc - min_balance_threshold)
        if usable_usdc < 10:
            logger.info(
                f"扣除保留金後可用 USDC 僅 ${usable_usdc:.2f}，低於最低交易門檻 $10。"
            )
            return 0

        # Use at most 95% of the usable capital to leave a small buffer for fees/slippage.
        capital_for_position = usable_usdc * 0.95

        if capital_for_position < 10:
            logger.info(
                f"扣除緩衝後可用資金 ${capital_for_position:.2f} 低於 $10，跳過建立 {coin_name} 部位。"
            )
            return 0

        if self.perp_user_state > 0 and target_perp_leverage > 0:
            max_notional_allowed = self.perp_user_state * target_perp_leverage
            if max_notional_allowed <= 0:
                logger.info("永續帳戶價值不足以支援新部位。")
                return 0
            if capital_for_position > max_notional_allowed:
                logger.info(
                    f"依照目標槓桿 {target_perp_leverage:.2f}x，永續可動用資金為 ${max_notional_allowed:.2f}，將限制開倉規模。"
                )
                capital_for_position = max_notional_allowed

        # The size of the spot leg determines the size of the perp leg.
        # The USDC required for the spot leg is size * price.
        # Let's allocate the configured percentage of our capital to the spot purchase.
        # This is a conceptual allocation to determine size, the actual USDC will come from the total balance.
        
        size = capital_for_position / price
        
        min_size_value_in_asset = 10 / price
        
        if size < min_size_value_in_asset:
            logger.warning(f"計算出的現貨規模太小: {size} (最小: {min_size_value_in_asset})")
            return 0
            
        rounded_size = self.round_size(coin_name, True, size)
        
        logger.info(f"計算 {coin_name} 的最佳現貨規模: {size:.6f} -> 四捨五入至 {rounded_size} (基於現貨 USDC 餘額 ${available_usdc:.2f})")
        
        return rounded_size
    
    def _calculate_optimal_perp_size(self, coin_name):
        # For delta-neutral, perp size should match spot size
        spot_size = self._calculate_optimal_spot_size(coin_name)
        
        # If spot size is zero, perp size should also be zero
        if spot_size <= 0:
            return 0
        
        # Round perp size according to the coin's perp sz_decimals
        rounded_size = self.round_size(coin_name, False, spot_size)
        
        # Log the calculation for debugging
        logger.info(f"計算 {coin_name} 的最佳永續合約規模: {spot_size} -> 四捨五入至 {rounded_size}")
        
        return rounded_size
    
    def _normalize_spot_coin(self, coin_name: str) -> str:
        if coin_name == "UBTC":
            return "BTC"
        if coin_name == "UETH":
            return "ETH"
        if coin_name == "USOL":
            return "SOL"
        return coin_name

    def _get_total_spot_account_value(self):
        if not self.spot_user_state:
            self.spot_user_state = self.info.spot_user_state(self.address)

        total_spot_value = 0.0
        for balance in self.spot_user_state.get("balances", []):
            total = float(balance.get("total", 0))
            if total <= 0:
                continue

            usd_value = balance.get("usdValue")
            if usd_value is not None:
                total_spot_value += float(usd_value)
                continue

            coin_name = self._normalize_spot_coin(balance.get("coin", ""))
            price = 1.0 if coin_name == "USDC" else self._get_spot_price(coin_name)
            total_spot_value += total * price

        return total_spot_value

    def _get_spot_account_value(self):
        # Legacy debug helper retained for compatibility
        if not self.spot_user_state:
            self.spot_user_state = self.info.spot_user_state(self.address)
        for balance in self.spot_user_state.get("balances", []):
            print(balance)
    
    def spot_perp_repartition(self):
        spot_value = self._get_total_spot_account_value()
        perp_value = self.perp_user_state
        total_value = spot_value + perp_value
        if total_value == 0:
            return 0.0
        return spot_value / total_value

    def _get_top_of_book(self, coin_name: str) -> Tuple[float, float]:
        """Return (best_bid, best_ask) with graceful fallbacks."""
        best_bid = best_ask = 0.0
        try:
            book = self.info.l2_snapshot(coin_name)
            levels = book.get("levels", []) if isinstance(book, dict) else []
            if levels:
                bids = levels[0]
                asks = levels[1] if len(levels) > 1 else []
                if bids:
                    best_bid = float(bids[0]['px'])
                if asks:
                    best_ask = float(asks[0]['px'])
        except Exception as exc:
            logger.debug(f"取得 {coin_name} 訂單簿失敗: {exc}")

        mid = self._get_spot_price(coin_name) or self._get_perp_price(coin_name)
        if best_bid <= 0 and mid:
            best_bid = mid * 0.999
        if best_ask <= 0 and mid:
            best_ask = mid * 1.001
        if best_bid <= 0 and best_ask > 0:
            best_bid = best_ask * 0.999
        if best_ask <= 0 and best_bid > 0:
            best_ask = best_bid * 1.001
        return best_bid, best_ask

    def position_snapshot(self, coin_name: str) -> PositionSnapshot:
        coin_info = self.coins.get(coin_name)
        if not coin_info or not (coin_info.spot and coin_info.perp):
            return PositionSnapshot(coin_name, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        spot_size = float(coin_info.spot.position.get("total", 0) or 0)
        perp_size = float(coin_info.perp.position.get("size", 0) or 0)

        spot_price = coin_info.spot.position.get("mark_price") or self._get_spot_price(coin_name)
        perp_price = self._get_perp_price(coin_name)

        if not spot_price or spot_price <= 0:
            spot_price = perp_price
        if not perp_price or perp_price <= 0:
            perp_price = spot_price
        if not spot_price or spot_price <= 0:
            spot_price = perp_price = 0.0

        spot_notional = abs(spot_size * spot_price)
        perp_notional = abs(perp_size * perp_price)
        denominator = max(spot_notional, perp_notional, 1e-9)
        delta_pct = 0.0 if denominator == 0 else abs(spot_notional - perp_notional) / denominator * 100

        return PositionSnapshot(
            coin=coin_name,
            spot_size=spot_size,
            perp_size=perp_size,
            spot_notional=spot_notional,
            perp_notional=perp_notional,
            delta_pct=delta_pct,
            spot_price=spot_price,
            perp_price=perp_price,
        )

    def is_delta_ok(self, delta_pct: float, threshold: Optional[float] = None) -> bool:
        threshold = threshold if threshold is not None else self.delta_threshold_pct
        return delta_pct <= threshold

    def calc_rebalance_qty(self, snapshot: PositionSnapshot) -> Optional[Dict[str, Any]]:
        if snapshot.delta_pct <= 0 or (snapshot.spot_notional == 0 and snapshot.perp_notional == 0):
            return None

        diff_notional = snapshot.spot_notional - snapshot.perp_notional
        if abs(diff_notional) < 1e-9:
            return None

        action: Dict[str, Any] = {"coin": snapshot.coin}
        if diff_notional > 0:
            # Spot leg larger -> add more perp short exposure
            price = snapshot.perp_price or snapshot.spot_price
            if price <= 0:
                return None
            raw_qty = abs(diff_notional) / price
            qty = self.round_size(snapshot.coin, False, raw_qty)
            if qty <= 0:
                return None
            action.update({
                "market": "perp",
                "side": "sell",
                "qty": qty,
                "price": price,
            })
        else:
            # Perp leg larger -> accumulate more spot
            price = snapshot.spot_price or snapshot.perp_price
            if price <= 0:
                return None
            raw_qty = abs(diff_notional) / price
            qty = self.round_size(snapshot.coin, True, raw_qty)
            if qty <= 0:
                return None
            action.update({
                "market": "spot",
                "side": "buy",
                "qty": qty,
                "price": price,
            })

        return action

    def has_delta_neutral_position(self, coin_name, error_margin=0.05):
        if coin_name not in self.coins:
            logger.warning(f"在追蹤的幣種中找不到 {coin_name}")
            return False, 0, 0, 0
        
        coin_info = self.coins[coin_name]
        
        if not (coin_info.perp and coin_info.spot):
            logger.debug(f"{coin_name} 沒有同時擁有永續合約和現貨市場")
            return False, 0, 0, 0
            
        perp_size = 0
        if coin_info.perp.position:
            perp_size = coin_info.perp.position.get("size", 0)
        
        spot_size = 0
        if coin_info.spot.position:
            spot_size = coin_info.spot.position.get("total", 0)
        
        if perp_size == 0 or spot_size == 0:
            return False, perp_size, spot_size, 0

        is_proper_direction = perp_size < 0 and spot_size > 0

        abs_perp_size = abs(perp_size)
        size_diff = abs(abs_perp_size - spot_size)
        
        larger_size = max(abs_perp_size, spot_size)
        diff_percentage = (size_diff / larger_size) * 100 if larger_size > 0 else 0
        
        is_delta_neutral = is_proper_direction

        return is_delta_neutral, perp_size, spot_size, diff_percentage

    async def _update_positions(self, verbose: bool = True):
        """Fetches and updates the bot's internal state for all spot and perp positions."""
        try:
            if verbose:
                logger.info("正在刷新持倉狀態...")
            self.user_state = self.info.user_state(self.address)
            self.spot_user_state = self.info.spot_user_state(self.address)

            cross_summary_snapshot = self.user_state.get("crossMarginSummary", {})
            current_perp_account_value = 0.0
            cross_account_value = cross_summary_snapshot.get("accountValue")
            if cross_account_value is not None:
                try:
                    current_perp_account_value = float(cross_account_value)
                except (TypeError, ValueError):
                    current_perp_account_value = 0.0

            # Clear existing position data before updating
            for coin in self.coins.values():
                if coin.perp: coin.perp.position = {}
                if coin.spot: coin.spot.position = {}

            # Update perp positions
            for position in self.user_state.get("assetPositions", []):
                if position["type"] == "oneWay" and "position" in position:
                    pos = position["position"]
                    coin_name = pos["coin"]
                    if coin_name in self.coins and self.coins[coin_name].perp:
                        perp_position_value = float(pos.get("positionValue", 0))
                        leverage_reported = pos.get("leverage", {}).get("value")
                        try:
                            leverage_reported = float(leverage_reported) if leverage_reported is not None else None
                        except (TypeError, ValueError):
                            leverage_reported = None

                        effective_leverage = None
                        if perp_position_value and current_perp_account_value:
                            try:
                                effective_leverage = abs(perp_position_value) / max(abs(current_perp_account_value), 1e-9)
                            except Exception:
                                effective_leverage = None

                        self.coins[coin_name].perp.position = {
                            "size": float(pos["szi"]),
                            "entry_price": float(pos["entryPx"]),
                            "position_value": perp_position_value,
                            "unrealized_pnl": float(pos["unrealizedPnl"]),
                            "leverage": leverage_reported,
                            "effective_leverage": effective_leverage,
                            "liquidation_price": float(pos["liquidationPx"]),
                            "cum_funding": pos["cumFunding"]["allTime"]
                        }
            
            # Update spot positions
            for balance in self.spot_user_state.get("balances", []):
                total_amount = float(balance.get("total", 0))
                if total_amount <= 0:
                    continue

                raw_coin_name = balance.get("coin", "")
                coin_name = self._normalize_spot_coin(raw_coin_name)
                if coin_name not in self.coins or not self.coins[coin_name].spot:
                    continue

                hold_amount = float(balance.get("hold", 0))
                entry_ntl = float(balance.get("entryNtl", 0))
                entry_price = None
                if entry_ntl and total_amount:
                    try:
                        entry_price = entry_ntl / total_amount
                    except ZeroDivisionError:
                        entry_price = None

                current_price = self._get_spot_price(coin_name)
                position_value = None
                unrealized_pnl = None
                if current_price:
                    position_value = total_amount * current_price
                    if entry_price is not None:
                        unrealized_pnl = position_value - entry_ntl

                self.coins[coin_name].spot.position = {
                    "total": total_amount,
                    "hold": hold_amount,
                    "entry_ntl": entry_ntl,
                    "entry_price": entry_price,
                    "position_value": position_value,
                    "unrealized_pnl": unrealized_pnl,
                    "mark_price": current_price
                }
            # Update derived account metrics
            self.margin_summary = self.user_state.get("marginSummary", {})
            cross_summary = cross_summary_snapshot

            spot_account_value = self._get_total_spot_account_value()
            self.perp_user_state = current_perp_account_value

            margin_account_value = self.margin_summary.get("accountValue")
            if margin_account_value is not None:
                self.margin_account_value = float(margin_account_value)
            else:
                self.margin_account_value = 0.0

            self.account_value = spot_account_value + self.perp_user_state

            total_margin_used_value = self.margin_summary.get("totalMarginUsed", 0)
            self.total_margin_used = float(total_margin_used_value) if total_margin_used_value is not None else 0.0

            total_raw_usd = self.margin_summary.get("totalRawUsd")
            self.total_raw_usd = float(total_raw_usd) if total_raw_usd is not None else self.account_value
            self.spot_account_value = spot_account_value

            if verbose:
                logger.info(
                    f"帳戶價值明細 -> 現貨: ${spot_account_value:.2f}, 永續: ${self.perp_user_state:.2f}, 總計: ${self.account_value:.2f}"
                )

                logger.info("持倉狀態刷新完成。")
        except Exception as e:
            logger.error("刷新持倉狀態時發生錯誤", exc_info=True)
            raise

    async def _refresh_positions_if_due(self, force: bool = False) -> None:
        now = time.time()
        if force or (now - self._last_position_refresh) >= max(self.heartbeat_sec / 2, 1):
            await self._update_positions(verbose=not force and (now - self._last_position_refresh) > self.heartbeat_sec * 3)
            self._last_position_refresh = time.time()

    async def _refresh_funding_if_due(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_funding_refresh) < self.funding_refresh_sec:
            return

        try:
            from test_market_data import check_funding_rates
        except ImportError:
            logger.error("找不到 funding 資料來源函式 test_market_data.check_funding_rates")
            return

        try:
            funding_rates = await check_funding_rates()
        except Exception as exc:
            logger.error(f"取得資金費率失敗: {exc}", exc_info=True)
            return

        for coin, raw_rate in funding_rates.items():
            try:
                rate_float = float(raw_rate)
            except (TypeError, ValueError):
                continue

            if self.funding_use_ema:
                prev = self.funding_ema.get(coin)
                smoothed = (
                    self.funding_ema_alpha * rate_float + (1 - self.funding_ema_alpha) * prev
                    if prev is not None else rate_float
                )
                self.funding_ema[coin] = smoothed
                effective_rate = smoothed
            else:
                effective_rate = rate_float

            self.funding_cache[coin] = effective_rate
            if coin in self.coins and self.coins[coin].perp:
                self.coins[coin].perp.funding_rate = effective_rate
                yearly_pct = effective_rate * 24 * 365 * 100
                self.coins[coin].perp.yearly_funding_rate = yearly_pct

        self._last_funding_refresh = time.time()

        best_coin = self.get_best_yearly_funding_rate()
        if best_coin:
            best_rate = self.coins[best_coin].perp.yearly_funding_rate
            logger.info(
                f"最新資金費率領先: {best_coin} {best_rate:.2f}% 年化"
            )

    def _log_runtime_config(self) -> None:
        """Emit a concise summary of key runtime parameters."""
        logger.info("年化資金費率換算: 1 小時預測 × 24 × 365")
        smoothing_desc = (
            f"EMA α={self.funding_ema_alpha:.2f}"
            if self.funding_use_ema else "停用平滑"
        )
        logger.info(
            f"資金費率採樣來源: Hyperliquid REST predictedFundings，每 {self.funding_refresh_sec:.0f} 秒，{smoothing_desc}"
        )
        logger.info(
            f"資金費率門檻: 空倉開倉 {self.funding_open_threshold_pct:.2f}%，換倉 {self.funding_replace_threshold_pct:.2f}%"
        )
        logger.info(
            f"持倉時間保護: 最小 {self.min_hold_minutes:.0f} 分鐘，換倉冷卻 {self.cooldown_after_replace_minutes:.0f} 分鐘"
        )
        logger.info(
            f"Delta 管理: 閾值 {self.delta_threshold_pct:.2f}%，重平衡最小間隔 {self.min_rebalance_interval_sec:.0f} 秒"
        )
        logger.info(
            f"下單策略: heartbeat {self.heartbeat_sec:.1f}s，max retries {self.max_retries}, rebalance 模式 {self.rebalance_order_type}"
        )
        logger.info(
            f"Post only 設定: entry={self.use_post_only_for_entry}, hedge={self.use_post_only_for_hedge}"
        )
        logger.info(
            f"滑點/費用限制: slippage≤{self.slippage_cap_bps:.1f}bps, fee≈{self.fee_bps:.1f}bps, min_qty={self.min_qty}, price_tick={self.price_tick}, qty_step={self.qty_step}"
        )

    
    def get_best_yearly_funding_rate(self):
        best_rate = 0
        best_coin = None
        for coin_name, coin_info in self.coins.items():
            if coin_info.perp and coin_info.perp.yearly_funding_rate:
                if coin_info.perp.yearly_funding_rate > best_rate:
                    best_rate = coin_info.perp.yearly_funding_rate
                    best_coin = coin_name
        return best_coin

    def _detect_active_coin(self) -> Optional[str]:
        if self.active_coin:
            return self.active_coin
        for coin in self.tracked_coins:
            if coin not in self.coins:
                continue
            snapshot = self.position_snapshot(coin)
            if snapshot.spot_size > 0 or abs(snapshot.perp_size) > 0:
                return coin
        return None

    def _transition_state(self, new_state: PositionState) -> None:
        if new_state != self.state:
            logger.info(f"狀態變更: {self.state.name} -> {new_state.name}")
            self.state = new_state
            self.last_state_change = time.time()

    async def _maybe_open_position(self) -> None:
        if self._active_order_group:
            return

        now = time.time()
        if self.last_replace_ts and (now - self.last_replace_ts) < self.cooldown_after_replace_minutes * 60:
            remaining = self.cooldown_after_replace_minutes * 60 - (now - self.last_replace_ts)
            logger.info(f"換倉冷卻中，尚需等待 {remaining:.0f} 秒")
            return

        best_coin = self.get_best_yearly_funding_rate()
        if not best_coin:
            logger.debug("尚未取得有效資金費率資料，維持空倉。")
            return

        best_rate = self.coins[best_coin].perp.yearly_funding_rate
        if best_rate is None:
            logger.debug("資金費率資料缺失，暫不開倉。")
            return

        logger.info(
            f"空倉：空倉開倉門檻={self.funding_open_threshold_pct:.2f}%；最佳={best_coin}({best_rate:.2f}%)"
        )

        if best_rate < self.funding_open_threshold_pct:
            logger.info("最佳資金費率未達門檻 → 維持空倉")
            return

        await self._open_position(best_coin)

    async def _open_position(self, coin_name: str) -> bool:
        spot_size = self._calculate_optimal_spot_size(coin_name)
        if spot_size <= 0:
            logger.info(f"{coin_name} 計算得出開倉數量為 0，放棄開倉。")
            return False

        self.active_coin = coin_name
        self._transition_state(PositionState.OPENING_SPOT)

        for attempt in range(self.max_retries):
            logger.info(f"開倉第 {attempt + 1} 次嘗試：先買入現貨 {coin_name}")
            group = await self.place_order_best_effort(coin_name, "spot", "buy", spot_size, "entry")
            if not group:
                continue
            outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
            if outcome.get("filled"):
                logger.info(f"{coin_name} 現貨腿建立完成。")
                break
        else:
            logger.error(f"{coin_name} 現貨腿連續 {self.max_retries} 次失敗，進入錯誤復原。")
            self._transition_state(PositionState.ERROR_RECOVERY)
            await self.close_existing_leg_asap(coin_name, "spot")
            self.active_coin = None
            self._transition_state(PositionState.EMPTY)
            return False

        await self._refresh_positions_if_due(force=True)
        self._transition_state(PositionState.OPENING_PERP)

        perp_qty = self.round_size(coin_name, False, spot_size)
        if perp_qty <= 0:
            logger.error(f"{coin_name} 永續腿數量計算為 0，啟動錯誤復原。")
            await self.close_existing_leg_asap(coin_name, "spot")
            self.active_coin = None
            self._transition_state(PositionState.EMPTY)
            return False

        for attempt in range(self.max_retries):
            logger.info(f"開倉第 {attempt + 1} 次嘗試：賣出永續 {coin_name}")
            group = await self.place_order_best_effort(coin_name, "perp", "sell", perp_qty, "entry")
            if not group:
                continue
            outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
            if outcome.get("filled"):
                logger.info(f"{coin_name} 永續腿建立完成。")
                break
        else:
            logger.error(f"{coin_name} 永續腿連續 {self.max_retries} 次失敗，回滾現貨腿。")
            await self.close_existing_leg_asap(coin_name, "spot")
            self.active_coin = None
            self._transition_state(PositionState.ERROR_RECOVERY)
            return False

        await self._refresh_positions_if_due(force=True)
        self.last_entry_ts = time.time()
        snapshot = self.position_snapshot(coin_name)
        if self.is_delta_ok(snapshot.delta_pct):
            self._transition_state(PositionState.DELTA_NEUTRAL)
        else:
            logger.warning(f"{coin_name} 開倉後 Delta 偏離 {snapshot.delta_pct:.2f}% ，將進入再平衡。")
            self._transition_state(PositionState.REBALANCING)
        return True

    async def _handle_one_leg(self, coin_name: str, snapshot: PositionSnapshot, missing_leg: str) -> None:
        key = f"hedge:{coin_name}:{missing_leg}"
        attempts = self._retry_counters.get(key, 0)
        if attempts >= self.max_retries:
            logger.error(f"{coin_name} {missing_leg} 補腿已達 {self.max_retries} 次失敗，改為平掉現有腿。")
            existing_leg = "spot" if missing_leg == "perp" else "perp"
            await self.close_existing_leg_asap(coin_name, existing_leg)
            self._retry_counters[key] = 0
            await self._refresh_positions_if_due(force=True)
            self.active_coin = None
            self._transition_state(PositionState.EMPTY)
            return

        if missing_leg == "perp":
            qty = snapshot.spot_size
            side = "sell"
            market = "perp"
        else:
            qty = abs(snapshot.perp_size)
            side = "buy" if snapshot.perp_size < 0 else "sell"
            market = "spot"

        logger.warning(f"偵測到 {coin_name} 單腿 ({missing_leg})，啟動補腿。嘗試次數 {attempts + 1}/{self.max_retries}")

        group = await self.place_order_best_effort(coin_name, market, side, qty, "hedge", allow_post_only=False)
        if not group:
            self._retry_counters[key] = attempts + 1
            return

        outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
        if outcome.get("filled"):
            logger.info(f"{coin_name} 單腿補齊成功。")
            self._retry_counters[key] = 0
            await self._refresh_positions_if_due(force=True)
            new_snapshot = self.position_snapshot(coin_name)
            if new_snapshot.spot_size > 0 and abs(new_snapshot.perp_size) > 0:
                if self.is_delta_ok(new_snapshot.delta_pct):
                    self._transition_state(PositionState.DELTA_NEUTRAL)
                else:
                    self._transition_state(PositionState.REBALANCING)
            else:
                logger.warning(f"{coin_name} 補腿後仍未建立雙邊，持續監控。")
        else:
            self._retry_counters[key] = attempts + 1
            logger.warning(f"{coin_name} 單腿補救未成交 ({outcome.get('status')}), 將於下一心跳重試。")

    async def _handle_rebalance(self, coin_name: str, snapshot: PositionSnapshot) -> None:
        since_last = time.time() - self.last_rebalance_ts
        if since_last < self.min_rebalance_interval_sec:
            logger.debug(f"距離上次再平衡僅 {since_last:.1f}s，等待。")
            return

        action = self.calc_rebalance_qty(snapshot)
        if not action:
            logger.info(f"{coin_name} 再平衡需求消失，回到 Delta 中性。")
            self._transition_state(PositionState.DELTA_NEUTRAL)
            return

        logger.info(
            f"{coin_name} Delta 偏離 {snapshot.delta_pct:.2f}% (>={self.delta_threshold_pct:.2f}%)，僅對 {action['market']} 下單 {action['side']} {action['qty']}"
        )

        group = await self.place_order_best_effort(
            coin_name,
            action["market"],
            action["side"],
            action["qty"],
            "rebalance",
            allow_post_only=False,
        )
        if not group:
            return

        outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
        if outcome.get("filled"):
            self.last_rebalance_ts = time.time()
            await self._refresh_positions_if_due(force=True)
            updated = self.position_snapshot(coin_name)
            if self.is_delta_ok(updated.delta_pct):
                logger.info(f"{coin_name} 再平衡完成，Δ={updated.delta_pct:.2f}%")
                self._transition_state(PositionState.DELTA_NEUTRAL)
            else:
                logger.warning(f"{coin_name} 再平衡後 Δ 仍為 {updated.delta_pct:.2f}% ，將再次嘗試。")
        else:
            logger.warning(f"{coin_name} 再平衡訂單未成交 ({outcome.get('status')})")

    async def _evaluate_funding_for_replace(self, coin_name: str) -> None:
        coin_info = self.coins.get(coin_name)
        if not coin_info or not coin_info.perp:
            return

        current_rate = coin_info.perp.yearly_funding_rate
        if current_rate is None:
            logger.debug(f"{coin_name} 缺少年化資金費率資料，暫不換倉。")
            return

        logger.info(
            f"持倉：持倉換倉門檻={self.funding_replace_threshold_pct:.2f}%；當前={coin_name}({current_rate:.2f}%)"
        )

        if current_rate >= self.funding_replace_threshold_pct:
            logger.info("收益率高於門檻 → 維持現倉")
            return

        now = time.time()
        if self.last_entry_ts and (now - self.last_entry_ts) < self.min_hold_minutes * 60:
            wait = self.min_hold_minutes * 60 - (now - self.last_entry_ts)
            logger.info(f"距離最小持倉時間尚有 {wait:.0f} 秒，暫不換倉")
            return

        logger.info("收益率低於門檻 → 啟動換倉流程，先平舊倉。")
        await self._close_position(coin_name, reason="replace")

    async def _close_position(self, coin_name: str, reason: str = "manual") -> bool:
        snapshot = self.position_snapshot(coin_name)
        if snapshot.spot_size == 0 and abs(snapshot.perp_size) == 0:
            logger.info(f"{coin_name} 無持倉可平。")
            self._transition_state(PositionState.EMPTY)
            self.active_coin = None
            return True

        self._transition_state(PositionState.CLOSING)
        success = True

        if abs(snapshot.perp_size) > 0:
            perp_side = "buy" if snapshot.perp_size < 0 else "sell"
            group = await self.place_order_best_effort(
                coin_name,
                "perp",
                perp_side,
                abs(snapshot.perp_size),
                "close",
                allow_post_only=False,
            )
            if group:
                outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
                if not outcome.get("filled"):
                    logger.warning(f"{coin_name} 永續腿平倉未成交 ({outcome.get('status')})，改用緊急平倉。")
                    success = await self.close_existing_leg_asap(coin_name, "perp") and success

        await self._refresh_positions_if_due(force=True)
        snapshot = self.position_snapshot(coin_name)

        if snapshot.spot_size > 0:
            group = await self.place_order_best_effort(
                coin_name,
                "spot",
                "sell",
                snapshot.spot_size,
                "close",
                allow_post_only=False,
            )
            if group:
                outcome = await self.await_fills_or_timeout(group.group_id, timeout_sec=5)
                if not outcome.get("filled"):
                    logger.warning(f"{coin_name} 現貨腿平倉未成交 ({outcome.get('status')})，改用緊急平倉。")
                    success = await self.close_existing_leg_asap(coin_name, "spot") and success

        await self._refresh_positions_if_due(force=True)
        final_snapshot = self.position_snapshot(coin_name)
        if final_snapshot.spot_size == 0 and abs(final_snapshot.perp_size) == 0:
            logger.info(f"{coin_name} 部位已全部平倉。")
            self.active_coin = None
            self._transition_state(PositionState.EMPTY)
            if reason == "replace":
                self.last_replace_ts = time.time()
            return success

        logger.warning(f"{coin_name} 平倉後仍有殘留部位 (spot={final_snapshot.spot_size}, perp={final_snapshot.perp_size})")
        if final_snapshot.spot_size > 0 and abs(final_snapshot.perp_size) == 0:
            self._transition_state(PositionState.ONE_LEG_SPOT_ONLY)
        elif final_snapshot.spot_size == 0 and abs(final_snapshot.perp_size) > 0:
            self._transition_state(PositionState.ONE_LEG_PERP_ONLY)
        else:
            self._transition_state(PositionState.ERROR_RECOVERY)
        return False

    async def _run_state_machine(self) -> None:
        await self._refresh_positions_if_due()
        await self._refresh_funding_if_due()

        coin = self._detect_active_coin()
        if coin:
            self.active_coin = coin
            snapshot = self.position_snapshot(coin)

            if snapshot.spot_size == 0 and abs(snapshot.perp_size) == 0:
                self.active_coin = None
                self._transition_state(PositionState.EMPTY)
                return

            if snapshot.spot_size > 0 and abs(snapshot.perp_size) == 0:
                self._transition_state(PositionState.ONE_LEG_SPOT_ONLY)
                await self._handle_one_leg(coin, snapshot, "perp")
                return

            if snapshot.spot_size == 0 and abs(snapshot.perp_size) > 0:
                self._transition_state(PositionState.ONE_LEG_PERP_ONLY)
                await self._handle_one_leg(coin, snapshot, "spot")
                return

            # Both legs present
            if self.is_delta_ok(snapshot.delta_pct):
                if self.state not in (PositionState.CLOSING, PositionState.ERROR_RECOVERY):
                    self._transition_state(PositionState.DELTA_NEUTRAL)
                await self._evaluate_funding_for_replace(coin)
            else:
                self._transition_state(PositionState.REBALANCING)
                await self._handle_rebalance(coin, snapshot)
        else:
            self.active_coin = None
            if self.state not in (PositionState.CLOSING, PositionState.ERROR_RECOVERY):
                self._transition_state(PositionState.EMPTY)
                await self._maybe_open_position()


    def _get_order_status(self, order_result: dict) -> dict:
        """Parses an order result to get a standardized status object."""
        if not order_result or order_result.get('status') != 'ok':
            error_msg = order_result.get('response', 'No response')
            return {"status": "error", "state": "failed_submission", "oid": None, "error_message": f"Submission failed: {error_msg}"}
        
        try:
            status_info = order_result['response']['data']['statuses'][0]
            if 'resting' in status_info:
                return {"status": "ok", "state": "resting", "oid": int(status_info['resting']['oid']), "error_message": None}
            elif 'filled' in status_info:
                return {"status": "ok", "state": "filled", "oid": int(status_info['filled']['oid']), "error_message": None}
            elif 'error' in status_info:
                return {"status": "error", "state": "error_response", "oid": None, "error_message": status_info['error']}
            else:
                return {"status": "error", "state": "unknown", "oid": None, "error_message": "Unknown order status response"}
        except (KeyError, IndexError) as e:
            return {"status": "error", "state": "parsing_error", "oid": None, "error_message": f"Failed to parse order response: {e}"}

    async def place_order_best_effort(
        self,
        coin_name: str,
        market: str,
        side: str,
        qty: float,
        intent: str,
        allow_post_only: bool = True,
    ) -> Optional[OrderGroup]:
        """Place an order with contextual strategy and automatic fallbacks."""
        if self._active_order_group:
            logger.debug(f"已有活躍 order_group {self._active_order_group}，略過新下單請求。")
            return None

        is_spot = market == "spot"
        rounded_qty = self.round_size(coin_name, is_spot, qty)
        if rounded_qty <= 0:
            logger.warning(f"{coin_name} {market} {side} 訂單規模過小 ({qty}), 未送出。")
            return None

        best_bid, best_ask = self._get_top_of_book(coin_name)
        base_price = best_ask if side == "buy" else best_bid
        if base_price <= 0:
            fallback_price = self._get_spot_price(coin_name) or self._get_perp_price(coin_name)
            base_price = fallback_price

        if not base_price or base_price <= 0:
            logger.error(f"{coin_name} 缺少有效價格，無法送出 {market} {side} 訂單。")
            return None

        slippage_factor = self.slippage_cap_bps / 10000 if self.slippage_cap_bps > 0 else 0
        if side == "buy":
            price = base_price * (1 + slippage_factor)
        else:
            price = base_price * (1 - slippage_factor)

        price = self.round_price(coin_name, price)
        if price <= 0:
            logger.error(f"{coin_name} 欠缺有效價格，終止下單。")
            return None

        params = {"limit": {}}
        use_post_only = False
        if allow_post_only:
            if intent == "entry" and self.use_post_only_for_entry:
                params["limit"]["tif"] = "Alo"
                use_post_only = True
            elif intent == "hedge" and self.use_post_only_for_hedge:
                params["limit"]["tif"] = "Alo"
                use_post_only = True

        needs_fallback = False
        if intent in ("hedge", "close") and not use_post_only:
            params["limit"]["tif"] = "Ioc"
        elif intent == "rebalance":
            if self.rebalance_order_type == "passive_then_ioc":
                params["limit"]["tif"] = "Gtc"
                needs_fallback = True
            else:
                params["limit"]["tif"] = "Ioc"
        elif "tif" not in params["limit"] and not use_post_only:
            params["limit"]["tif"] = "Ioc" if intent != "entry" else "Gtc"

        market_name = self._get_spot_pair(coin_name) if is_spot else coin_name
        side_bool = True if side == "buy" else False

        logger.info(
            f"下單 {intent}: {coin_name} {market} {side} {rounded_qty} @ {price} (postOnly={use_post_only}, tif={params['limit'].get('tif')})"
        )

        try:
            result = self.exchange.order(market_name, side_bool, rounded_qty, price, params)
        except Exception as exc:
            logger.error(f"{coin_name} {market} 下單失敗: {exc}", exc_info=True)
            return None

        self._log_order_submission(coin_name, market, side, rounded_qty, price, result, intent)
        status = self._get_order_status(result)

        error_message = status.get("error_message") or ""
        if status["status"] == "error" and use_post_only and "immediately matched" in error_message:
            logger.warning(f"Post only 被拒 ({error_message})，改用非 post only 策略。")
            return await self.place_order_best_effort(coin_name, market, side, qty, intent, allow_post_only=False)

        if status["status"] == "error":
            logger.error(f"{coin_name} {market} 下單失敗: {error_message}")
            return None

        oid = status.get("oid")
        group_id = str(uuid.uuid4())
        group = OrderGroup(
            group_id=group_id,
            coin=coin_name,
            intent=intent,
            market=market,
            oids=[oid] if oid else [],
            last_status=status.get("state"),
            side=side,
            qty=rounded_qty,
            price=price,
            needs_fallback=needs_fallback,
        )
        self.order_groups[group_id] = group
        self._active_order_group = group_id
        return group

    async def await_fills_or_timeout(
        self,
        order_group_id: str,
        timeout_sec: float = 3.0,
        poll_interval: float = 0.5,
    ) -> Dict[str, Any]:
        group = self.order_groups.get(order_group_id)
        if not group:
            return {"status": "unknown_group"}

        start_ts = time.time()
        result_summary = {"status": "pending", "filled": False}

        async def _poll_status(oids: List[int]) -> Tuple[bool, bool]:
            all_done = True
            any_filled = False
            for oid in oids:
                if not oid:
                    continue
                try:
                    status = self.info.query_order_by_oid(self.address, oid)
                    order_info = status.get("order", {}) if isinstance(status, dict) else {}
                    state = order_info.get("status")
                    if state in ("filled", "determined", "closed"):
                        any_filled = True
                    elif state in ("canceled", "cancelled", "failed"):
                        any_filled = any_filled or False
                    else:
                        all_done = False
                except Exception as exc:
                    logger.debug(f"查詢訂單 {oid} 狀態失敗: {exc}")
                    all_done = False
            return all_done, any_filled

        async def _cancel_oids(oids: List[int]) -> None:
            for oid in oids:
                if not oid:
                    continue
                try:
                    if group.market == "spot":
                        self.exchange.cancel(self._get_spot_pair(group.coin), oid)
                    else:
                        self.exchange.cancel(group.coin, oid)
                    logger.info(f"已取消 {group.coin} {group.market} 訂單 {oid}")
                except Exception as exc:
                    logger.warning(f"取消 {group.coin} 訂單 {oid} 失敗: {exc}")

        while time.time() - start_ts < timeout_sec:
            all_done, any_filled = await _poll_status(group.oids)
            if all_done:
                result_summary.update({"status": "completed", "filled": any_filled})
                break
            await asyncio.sleep(poll_interval)

        if result_summary["status"] != "completed" and group.needs_fallback:
            logger.info(f"{group.coin} {group.intent} 第一階段未成交，降級為 IOC。")
            await _cancel_oids(group.oids)
            best_bid, best_ask = self._get_top_of_book(group.coin)
            base_price = best_ask if group.side == "buy" else best_bid
            slippage_factor = self.slippage_cap_bps / 10000 if self.slippage_cap_bps > 0 else 0
            if group.side == "buy":
                price = base_price * (1 + slippage_factor)
            else:
                price = base_price * (1 - slippage_factor)
            price = self.round_price(group.coin, price)
            params = {"limit": {"tif": "Ioc"}}
            market_name = self._get_spot_pair(group.coin) if group.market == "spot" else group.coin
            side_bool = True if group.side == "buy" else False
            try:
                fallback_result = self.exchange.order(
                    market_name,
                    side_bool,
                    group.qty,
                    price,
                    params,
                )
            except Exception as exc:
                logger.error(f"執行 IOC 回退失敗: {exc}", exc_info=True)
                result_summary.update({"status": "fallback_failed", "filled": False})
            else:
                self._log_order_submission(group.coin, group.market, group.side, group.qty, price, fallback_result, f"{group.intent}-fallback")
                status = self._get_order_status(fallback_result)
                if status["status"] == "ok":
                    group.oids = [status.get("oid")]
                    group.needs_fallback = False
                    start_ts = time.time()
                    while time.time() - start_ts < timeout_sec:
                        all_done, any_filled = await _poll_status(group.oids)
                        if all_done:
                            result_summary.update({"status": "completed", "filled": any_filled})
                            break
                        await asyncio.sleep(poll_interval)
                else:
                    result_summary.update({"status": "fallback_failed", "filled": False})

        if result_summary["status"] == "pending":
            result_summary.update({"status": "timeout", "filled": False})

        # Cleanup
        self.order_groups.pop(order_group_id, None)
        if self._active_order_group == order_group_id:
            self._active_order_group = None

        return result_summary

    async def close_existing_leg_asap(self, coin_name: str, leg: str) -> bool:
        snapshot = self.position_snapshot(coin_name)
        if leg == "spot":
            qty = self.round_size(coin_name, True, snapshot.spot_size)
            side = "sell"
            is_spot = True
        elif leg == "perp":
            if snapshot.perp_size == 0:
                return True
            qty = self.round_size(coin_name, False, abs(snapshot.perp_size))
            side = "buy" if snapshot.perp_size < 0 else "sell"
            is_spot = False
        else:
            logger.error(f"未知的腿型 {leg}")
            return False

        if qty <= 0:
            logger.info(f"{coin_name} {leg} 無需緊急平倉 (qty={qty}).")
            return True

        price = self._get_emergency_price(coin_name, side == "buy", is_spot)
        params = {"limit": {"tif": "Ioc"}}
        market_name = self._get_spot_pair(coin_name) if is_spot else coin_name
        logger.warning(f"緊急平倉 {coin_name} {leg}: {side} {qty} @ {price}")
        try:
            result = self.exchange.order(market_name, side == "buy", qty, price, params)
        except Exception as exc:
            logger.error(f"緊急平倉 {coin_name} {leg} 失敗: {exc}", exc_info=True)
            return False

        self._log_order_submission(coin_name, leg, side, qty, price, result, f"close-{leg}")
        status = self._get_order_status(result)
        return status.get("status") == "ok"

    async def _rollback_position(self, coin_name: str, spot_info: dict, perp_info: dict, spot_size: float, perp_size: float):
        """Rollback logic to cancel resting orders or market-close filled orders."""
        logger.warning("開倉/平倉不完全成功，啟動回滾程序...")
        spot_pair = self._get_spot_pair(coin_name)

        if spot_info and spot_info["status"] == 'ok':
            if spot_info['state'] == 'resting':
                logger.info(f"正在取消未成交的現貨訂單 {spot_info['oid']}...")
                self.exchange.cancel(spot_pair, spot_info['oid'])
            elif spot_info['state'] == 'filled':
                logger.critical(f"現貨訂單 {spot_info['oid']} 已被成交！正在提交市價單以緊急回滾！")
                side_to_rollback = not (spot_info.get('side') == 'buy')
                filled_spot_sz = self._get_filled_size_from_oid(spot_info.get('oid'))
                effective_spot_size = filled_spot_sz if filled_spot_sz is not None else spot_size
                if effective_spot_size <= 0:
                    logger.info("緊急回滾時現貨成交數量為 0，略過現貨回滾。")
                else:
                    emergency_price = self._get_emergency_price(coin_name, side_to_rollback, True)
                    logger.info(
                        f"緊急回滾現貨 {'買' if side_to_rollback else '賣'}單 {effective_spot_size:.8f}，價格 {emergency_price:.4f} (IOC)"
                    )
                    self.exchange.order(
                        spot_pair,
                        side_to_rollback,
                        effective_spot_size,
                        emergency_price,
                        {"limit": {"tif": "Ioc"}},
                    )

        if perp_info and perp_info["status"] == 'ok':
            if perp_info['state'] == 'resting':
                logger.info(f"正在取消未成交的合約訂單 {perp_info['oid']}...")
                self.exchange.cancel(coin_name, perp_info['oid'])
            elif perp_info['state'] == 'filled':
                logger.critical(f"合約訂單 {perp_info['oid']} 已被成交！正在提交市價單以緊急回滾！")
                side_to_rollback = not (perp_info.get('side') == 'buy')
                filled_perp_sz = self._get_filled_size_from_oid(perp_info.get('oid'))
                effective_perp_size = filled_perp_sz if filled_perp_sz is not None else perp_size
                if effective_perp_size <= 0:
                    logger.info("緊急回滾時永續成交數量為 0，略過永續回滾。")
                else:
                    emergency_price = self._get_emergency_price(coin_name, side_to_rollback, False)
                    logger.info(
                        f"緊急回滾永續 {'買' if side_to_rollback else '賣'}單 {effective_perp_size:.8f}，價格 {emergency_price:.4f} (IOC)"
                    )
                    self.exchange.order(
                        coin_name,
                        side_to_rollback,
                        effective_perp_size,
                        emergency_price,
                        {"limit": {"tif": "Ioc"}},
                    )

    async def _attempt_order_placement(self, coin_name: str, side: str, order_type: str) -> tuple:
        """Attempts to place orders based on side (opening/closing) and type (maker/taker)."""
        try:
            l2_book = self.info.l2_snapshot(coin_name)
            if not l2_book or not l2_book["levels"][0] or not l2_book["levels"][1]:
                logger.warning(f"無法取得 {coin_name} 的 L2 訂單簿。")
                return None, None, None, None

            best_bid = float(l2_book["levels"][0][0]['px'])
            best_ask = float(l2_book["levels"][1][0]['px'])

            if order_type == 'maker':
                spot_price = self.round_price(coin_name, best_bid if side == 'opening' else best_ask)
                perp_price = self.round_price(coin_name, best_ask if side == 'opening' else best_bid)
                order_params = {"limit": {"tif": "Alo"}}
            else: # taker
                spot_price = self.round_price(coin_name, best_ask if side == 'opening' else best_bid)
                perp_price = self.round_price(coin_name, best_bid if side == 'opening' else best_ask)
                order_params = {"limit": {"tif": "Ioc"}} # Immediate Or Cancel

            if side == 'opening':
                spot_size = self._calculate_optimal_spot_size(coin_name)
                if spot_size <= 0: return None, None, None, None
                perp_size = spot_size
            else: # closing
                _, perp_size_val, spot_size_val, _ = self.has_delta_neutral_position(coin_name)
                spot_size = spot_size_val
                perp_size = abs(perp_size_val)

            spot_pair = self._get_spot_pair(coin_name)
            spot_side_is_buy = (side == 'opening')
            perp_side_is_buy = (side == 'closing')

            spot_order_result = self.exchange.order(spot_pair, spot_side_is_buy, spot_size, spot_price, order_params)
            perp_order_result = self.exchange.order(coin_name, perp_side_is_buy, perp_size, perp_price, order_params)
            
            self._log_order_submission(coin_name, 'spot', 'buy' if spot_side_is_buy else 'sell', spot_size, spot_price, spot_order_result, f"{side}_{order_type}")
            self._log_order_submission(coin_name, 'perp', 'buy' if perp_side_is_buy else 'sell', perp_size, perp_price, perp_order_result, f"{side}_{order_type}")

            spot_info = self._get_order_status(spot_order_result)
            perp_info = self._get_order_status(perp_order_result)
            spot_info['side'] = 'buy' if spot_side_is_buy else 'sell'
            perp_info['side'] = 'buy' if perp_side_is_buy else 'sell'

            return spot_info, perp_info, spot_size, perp_size
        except Exception as e:
            logger.error(f"在 _attempt_order_placement 中發生錯誤: {e}", exc_info=True)
            return None, None, None, None

    async def _execute_hybrid_strategy(self, coin_name: str, side: str):
        """Executes the full hybrid maker-taker strategy for opening or closing a position."""
        # --- 1. Maker Attempt ---
        logger.info(f"階段 1: 嘗試以 Maker 方式 {side} {coin_name} 部位...")
        operation_type = 'closing' if side == 'closing' else 'opening'
        spot_info, perp_info, spot_size, perp_size = await self._attempt_order_placement(coin_name, side, 'maker')

        if not all([spot_info, perp_info, spot_size, perp_size]):
            logger.info(f"{coin_name} 的 {operation_type} Maker 嘗試因資金或掛單限制未能建立有效規模。")
            return False

        if spot_info and perp_info and spot_info["status"] == 'ok' and perp_info["status"] == 'ok':
            logger.info(f"Maker 訂單提交成功 (現貨: {spot_info['state']}, 合約: {perp_info['state']})。")
            pending_order = PendingDeltaOrder(coin_name=coin_name, is_closing_position=(side == 'closing'))
            pending_order.spot_oid = spot_info['oid']
            pending_order.perp_oid = perp_info['oid']
            pending_order.spot_filled = spot_info['state'] == 'filled'
            pending_order.perp_filled = perp_info['state'] == 'filled'
            
            if pending_order.spot_filled and pending_order.perp_filled:
                await self._finalize_successful_execution(
                    coin_name,
                    pending_order.spot_oid,
                    pending_order.perp_oid,
                    operation_type,
                )
                return True

            if not (pending_order.spot_filled and pending_order.perp_filled):
                MAKER_WAIT_SECONDS = 5
                logger.info(f"等待 {MAKER_WAIT_SECONDS} 秒觀察 Maker 訂單成交情況...")
                await asyncio.sleep(MAKER_WAIT_SECONDS)

                spot_status_after_wait = self.info.query_order_by_oid(self.address, pending_order.spot_oid)
                perp_status_after_wait = self.info.query_order_by_oid(self.address, pending_order.perp_oid)
                spot_filled_after_wait = spot_status_after_wait.get('order', {}).get('status') != 'open'
                perp_filled_after_wait = perp_status_after_wait.get('order', {}).get('status') != 'open'

                if spot_filled_after_wait and perp_filled_after_wait:
                    logger.info("Maker 訂單在等待期間完全成交！")
                    pending_order.spot_filled = True
                    pending_order.perp_filled = True
                    await self._finalize_successful_execution(
                        coin_name,
                        pending_order.spot_oid,
                        pending_order.perp_oid,
                        operation_type,
                    )
                    return True
                else:
                    logger.warning("Maker 訂單未在時限內完全成交，取消並轉為 Taker 策略。")
                    await self._rollback_position(coin_name, spot_info, perp_info, spot_size, perp_size)
        else:
            await self._rollback_position(coin_name, spot_info, perp_info, spot_size, perp_size)

        # --- 2. Taker Attempt ---
        logger.info(f"階段 2: 嘗試以 Taker 方式 {side} {coin_name} 部位...")
        spot_info_taker, perp_info_taker, spot_size_taker, perp_size_taker = await self._attempt_order_placement(coin_name, side, 'taker')

        if not all([spot_info_taker, perp_info_taker, spot_size_taker, perp_size_taker]):
            logger.info(f"{coin_name} 的 {operation_type} Taker 嘗試因資金或掛單限制未能建立有效規模。")
            return False

        if spot_info_taker and perp_info_taker and spot_info_taker["state"] == 'filled' and perp_info_taker["state"] == 'filled':
            logger.info("Taker 方式成功，兩邊均已立即成交。")
            await self._finalize_successful_execution(
                coin_name,
                spot_info_taker.get('oid') if isinstance(spot_info_taker, dict) else None,
                perp_info_taker.get('oid') if isinstance(perp_info_taker, dict) else None,
                operation_type,
            )
            return True
        else:
            logger.error("Taker 方式失敗，執行緊急回滾。")
            await self._rollback_position(coin_name, spot_info_taker, perp_info_taker, spot_size_taker, perp_size_taker)
            return False

    async def create_delta_position(self, coin_name):
        if coin_name not in self.coins or not self.coins[coin_name].spot or not self.coins[coin_name].perp:
            logger.warning(f"{coin_name} 市場不完整，無法建立部位。")
            return False
        if self.has_delta_neutral_position(coin_name)[0]:
            logger.info(f"已持有 {coin_name} 的 Delta 中性部位，無需重複建立。")
            return True

        available_usdc = self._get_spot_account_USDC()
        min_balance_threshold = getattr(self, "min_spot_balance_to_open", 50.0)
        if available_usdc <= min_balance_threshold:
            logger.info(
                f"現貨 USDC 餘額 (${available_usdc:.2f}) 低於設定的開倉閾值 (${min_balance_threshold:.2f})，跳過建立 {coin_name} 部位。"
            )
            return False

        target_perp_leverage = getattr(self, "target_perp_leverage", 1.0)
        max_notional_allowed = self.perp_user_state * target_perp_leverage if self.perp_user_state else 0
        if max_notional_allowed <= 0:
            logger.info(
                f"永續帳戶價值不足（{self.perp_user_state:.2f}），無法在 {coin_name} 建立新部位。"
            )
            return False
        
        return await self._execute_hybrid_strategy(coin_name, 'opening')
    
    async def check_pending_orders(self):
        """Check the status of all pending orders and handle accordingly."""
        if not self.pending_orders:
            return
        
        current_time = time.time()
        orders_to_remove = []
        relist_threshold = 15  # 15 seconds
        max_relists = 5

        for pending_order in self.pending_orders:
            # Skip if checked recently
            if current_time - pending_order.last_check_time < 10: # Check every 10s
                continue
            
            pending_order.last_check_time = current_time
            operation_type = "關閉" if pending_order.is_closing_position else "開啟"
            logger.info(f"正在檢查 {pending_order.coin_name} 的待處理 {operation_type} Delta 部位")

            # 1. Check if orders are filled
            await self._update_order_fill_status(pending_order)
            if pending_order.spot_filled and pending_order.perp_filled:
                logger.info(f"{pending_order.coin_name} 的兩筆 {operation_type} 訂單皆已成交。部位建立完成。")
                await self._finalize_successful_execution(
                    pending_order.coin_name,
                    pending_order.spot_oid,
                    pending_order.perp_oid,
                    'closing' if pending_order.is_closing_position else 'opening',
                )
                orders_to_remove.append(pending_order)
                continue

            # 2. Handle orders that have been pending for too long (abandon)
            if current_time - pending_order.creation_time > pending_order.max_wait_time:
                logger.warning(f"{pending_order.coin_name} 的 {operation_type} 訂單已超過最大等待時間。正在取消。")
                await self._cancel_unfilled_orders(pending_order, operation_type)
                orders_to_remove.append(pending_order)
                continue

            # 3. Handle re-listing for partially filled or unfilled orders
            if not (pending_order.spot_filled and pending_order.perp_filled) and (current_time - pending_order.last_check_time > relist_threshold):
                if pending_order.relist_count >= max_relists:
                    logger.error(f"{pending_order.coin_name} 的訂單已達最大重新掛單次數 ({max_relists})。放棄處理。")
                    await self._cancel_unfilled_orders(pending_order, operation_type)
                    orders_to_remove.append(pending_order)
                    continue
                
                logger.info(f"{pending_order.coin_name} 的訂單待處理中。嘗試重新掛單 (第 {pending_order.relist_count + 1}/{max_relists} 次)。")
                
                # Cancel existing unfilled orders before creating new ones
                await self._cancel_unfilled_orders(pending_order, operation_type)
                
                pending_order.relist_count += 1
                pending_order.last_check_time = current_time # Reset timer after relist

                # Re-create the logic for the unfilled part
                await self._relist_unfilled_orders(pending_order)

        # Remove processed orders
        for order in orders_to_remove:
            if order in self.pending_orders:
                self.pending_orders.remove(order)

    async def _update_order_fill_status(self, pending_order: PendingDeltaOrder):
        """Helper to check and update the fill status of an order from the exchange."""
        try:
            if not pending_order.spot_filled and pending_order.spot_oid:
                spot_order_status = self.info.query_order_by_oid(self.address, pending_order.spot_oid)
                if spot_order_status.get('order', {}).get('status') != 'open':
                    logger.info(f"{pending_order.coin_name} 的現貨訂單 {pending_order.spot_oid} 不再是開啟狀態。標記為已成交。")
                    pending_order.spot_filled = True

            if not pending_order.perp_filled and pending_order.perp_oid:
                perp_order_status = self.info.query_order_by_oid(self.address, pending_order.perp_oid)
                if perp_order_status.get('order', {}).get('status') != 'open':
                    logger.info(f"{pending_order.coin_name} 的永續合約訂單 {pending_order.perp_oid} 不再是開啟狀態。標記為已成交。")
                    pending_order.perp_filled = True
        except Exception as e:
            logger.error(f"更新 {pending_order.coin_name} 的訂單狀態時發生錯誤: {e}")

    async def _cancel_unfilled_orders(self, pending_order: PendingDeltaOrder, operation_type: str):
        """Helper to cancel any unfilled orders associated with a pending order."""
        coin_name = pending_order.coin_name
        if not pending_order.spot_filled and pending_order.spot_oid:
            try:
                spot_pair = self._get_spot_pair(coin_name)
                self.exchange.cancel(spot_pair, pending_order.spot_oid)
                logger.info(f"已取消 {coin_name} 的現貨 {operation_type} 訂單 {pending_order.spot_oid}")
            except Exception as e:
                logger.error(f"取消 {coin_name} 的現貨 {operation_type} 訂單時發生錯誤: {e}")
        
        if not pending_order.perp_filled and pending_order.perp_oid:
            try:
                self.exchange.cancel(coin_name, pending_order.perp_oid)
                logger.info(f"已取消 {coin_name} 的永續合約 {operation_type} 訂單 {pending_order.perp_oid}")
            except Exception as e:
                logger.error(f"取消 {coin_name} 的永續合約 {operation_type} 訂單時發生錯誤: {e}")

    def _get_spot_pair(self, coin_name: str) -> str:
        """Helper to get the correct spot pair name."""
        coin_info = self.coins.get(coin_name)
        if coin_info and coin_info.spot:
            return f"{coin_info.spot.name}/USDC"

        spot_name = coin_name if coin_name.startswith('U') else f"U{coin_name}"
        return f"{spot_name}/USDC"

    async def _relist_unfilled_orders(self, pending_order: PendingDeltaOrder):
        """Helper to re-place orders for the unfilled legs of a pending order."""
        coin_name = pending_order.coin_name
        is_closing = pending_order.is_closing_position

        try:
            l2_book = self.info.l2_snapshot(coin_name)
            if not l2_book or not l2_book["levels"][0] or not l2_book["levels"][1]:
                logger.error(f"無法取得 {coin_name} 的 L2 訂單簿以重新掛單。")
                return

            best_bid = float(l2_book["levels"][0][0]['px'])
            best_ask = float(l2_book["levels"][1][0]['px'])

            # Re-place spot order if not filled
            if not pending_order.spot_filled:
                _, _, spot_size, _ = self.has_delta_neutral_position(coin_name)
                if spot_size > 0:
                    spot_pair = self._get_spot_pair(coin_name)
                    side = not is_closing # Buy if opening, Sell if closing
                    price = best_bid if side else best_ask
                    rounded_price = self.round_price(coin_name, price)
                    rounded_size = self.round_size(coin_name, True, spot_size)
                    
                    logger.info(f"重新掛單現貨 {'買單' if side else '賣單'} ({coin_name}): {rounded_size} @ {rounded_price}")
                    result = self.exchange.order(spot_pair, side, rounded_size, rounded_price, {"limit": {"tif": "Alo"}})
                    self._log_order_submission(coin_name, 'spot', 'buy' if side else 'sell', rounded_size, rounded_price, result, 'relisting')
                    # Update oid
                    if result and result.get('status') == 'ok':
                        response = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
                        if 'resting' in response:
                            pending_order.spot_oid = int(response['resting']['oid'])

            # Re-place perp order if not filled
            if not pending_order.perp_filled:
                _, perp_size, _, _ = self.has_delta_neutral_position(coin_name)
                if perp_size != 0:
                    side = is_closing # Buy if closing, Sell if opening
                    price = best_bid if side else best_ask
                    rounded_price = self.round_price(coin_name, price)
                    rounded_size = self.round_size(coin_name, False, abs(perp_size))

                    logger.info(f"重新掛單永續合約 {'買單' if side else '賣單'} ({coin_name}): {rounded_size} @ {rounded_price}")
                    result = self.exchange.order(coin_name, side, rounded_size, rounded_price, {"limit": {"tif": "Alo"}})
                    self._log_order_submission(coin_name, 'perp', 'buy' if side else 'sell', rounded_size, rounded_price, result, 'relisting')
                    # Update oid
                    if result and result.get('status') == 'ok':
                        response = result.get('response', {}).get('data', {}).get('statuses', [{}])[0]
                        if 'resting' in response:
                            pending_order.perp_oid = int(response['resting']['oid'])

        except Exception as e:
            logger.error(f"重新掛單 {coin_name} 的訂單時發生錯誤: {e}")
    
    async def close_delta_position(self, coin_name):
        return await self._close_position(coin_name, reason="manual")
    
    async def close_all_delta_positions(self):
        """Close all active delta-neutral positions across all tracked coins."""
        logger.info("正在嘗試關閉所有 Delta 中性部位...")
        
        closed_positions = 0
        for coin_name in self.tracked_coins:
            if coin_name == "USDC":
                continue
                
            is_delta_neutral, _, _, _ = self.has_delta_neutral_position(coin_name)
            if is_delta_neutral:
                logger.info(f"正在關閉 {coin_name} 的 Delta 中性部位...")
                result = await self.close_delta_position(coin_name)
                if result:
                    logger.info(f"成功關閉 {coin_name} 的 Delta 中性部位")
                    closed_positions += 1
                else:
                    logger.warning(f"關閉 {coin_name} 的 Delta 中性部位失敗")
        
        if closed_positions > 0:
            logger.info(f"成功關閉 {closed_positions} 個 Delta 中性部位")
        else:
            logger.info("沒有 Delta 中性部位被關閉")
            
        return closed_positions > 0
    
    async def exit_program(self, close_positions=True):
        """Exit the program and optionally close all positions."""
        logger.info("正在退出程式...")
        
        # Set running state to False
        self._is_running = False
        
        if close_positions:
            logger.info("正在關閉所有部位...")
            await self.close_all_delta_positions()
        
        logger.info("已退出")
        return True
            
    async def execute_best_delta_strategy(self):
        best_coin = self.get_best_yearly_funding_rate()
        if not best_coin:
            logger.warning("找不到資金費率為正的幣種")
            return False
            
        is_delta_neutral, _, _, _ = self.has_delta_neutral_position(best_coin)
        if is_delta_neutral:
            logger.info(f"已持有 {best_coin} 的 Delta 中性部位")
            return False
            
        logger.info(f"正在為 {best_coin} 建立 Delta 中性部位，其資金費率最佳: {self.coins[best_coin].perp.yearly_funding_rate:.4f}%")
        return await self.create_delta_position(best_coin)

    async def check_and_rebalance_positions(self):
        """Check all active positions and rebalance them if they have drifted from delta neutral."""
        if not self.config["allocation"].get("auto_rebalance", False):
            return

        logger.debug("正在檢查部位以進行再平衡...")
        for coin_name in self.coins:
            is_delta_neutral, perp_size, spot_size, diff_percentage = self.has_delta_neutral_position(coin_name)

            if not is_delta_neutral:
                continue

            # Calculate the current value of both legs
            spot_price = self._get_spot_price(coin_name)
            perp_price = self._get_perp_price(coin_name)
            if spot_price == 0 or perp_price == 0:
                logger.warning(f"無法取得 {coin_name} 的價格以進行再平衡")
                continue

            spot_value = spot_size * spot_price
            perp_value = abs(perp_size) * perp_price
            
            value_diff_pct = abs(spot_value - perp_value) / max(spot_value, perp_value)

            if value_diff_pct > self.rebalance_threshold:
                logger.info(f"{Colors.YELLOW}{coin_name} 的部位已偏離中性超過閾值 ({value_diff_pct:.2%} > {self.rebalance_threshold:.2%})。正在啟動再平衡...{Colors.RESET}")
                await self._execute_rebalance_orders(coin_name, spot_value, perp_value, spot_price, perp_price)

    async def _execute_rebalance_orders(self, coin_name: str, spot_value: float, perp_value: float, spot_price: float, perp_price: float):
        """Executes the specific orders to bring a position back to neutral."""
        try:
            value_to_adjust = abs(spot_value - perp_value) / 2
            
            if spot_value > perp_value:
                # Sell spot, Buy (cover) perp
                adjustment_size_spot = self.round_size(coin_name, True, value_to_adjust / spot_price)
                adjustment_size_perp = self.round_size(coin_name, False, value_to_adjust / perp_price)
                
                logger.info(f"再平衡 {coin_name}: 賣出現貨 {adjustment_size_spot}, 買入永續合約 {adjustment_size_perp}")

                # Get best prices for maker orders
                l2_book = self.info.l2_snapshot(coin_name)
                best_bid = float(l2_book["levels"][0][0]['px'])
                best_ask = float(l2_book["levels"][1][0]['px'])

                # Place spot sell order
                spot_pair = self._get_spot_pair(coin_name)
                spot_order_result = self.exchange.order(spot_pair, False, adjustment_size_spot, self.round_price(coin_name, best_ask), {"limit": {"tif": "Alo"}})
                self._log_order_submission(coin_name, 'spot', 'sell', adjustment_size_spot, self.round_price(coin_name, best_ask), spot_order_result, 'rebalancing')
                
                # Place perp buy order
                perp_order_result = self.exchange.order(coin_name, True, adjustment_size_perp, self.round_price(coin_name, best_bid), {"limit": {"tif": "Alo"}})
                self._log_order_submission(coin_name, 'perp', 'buy', adjustment_size_perp, self.round_price(coin_name, best_bid), perp_order_result, 'rebalancing')

            else: # perp_value > spot_value
                # Buy spot, Sell (open) perp
                adjustment_size_spot = self.round_size(coin_name, True, value_to_adjust / spot_price)
                adjustment_size_perp = self.round_size(coin_name, False, value_to_adjust / perp_price)

                logger.info(f"再平衡 {coin_name}: 買入現貨 {adjustment_size_spot}, 賣出永續合約 {adjustment_size_perp}")

                # Get best prices for maker orders
                l2_book = self.info.l2_snapshot(coin_name)
                best_bid = float(l2_book["levels"][0][0]['px'])
                best_ask = float(l2_book["levels"][1][0]['px'])

                # Place spot buy order
                spot_pair = self._get_spot_pair(coin_name)
                spot_order_result = self.exchange.order(spot_pair, True, adjustment_size_spot, self.round_price(coin_name, best_bid), {"limit": {"tif": "Alo"}})
                self._log_order_submission(coin_name, 'spot', 'buy', adjustment_size_spot, self.round_price(coin_name, best_bid), spot_order_result, 'rebalancing')

                # Place perp sell order
                perp_order_result = self.exchange.order(coin_name, False, adjustment_size_perp, self.round_price(coin_name, best_ask), {"limit": {"tif": "Alo"}})
                self._log_order_submission(coin_name, 'perp', 'sell', adjustment_size_perp, self.round_price(coin_name, best_ask), perp_order_result, 'rebalancing')
            
            logger.info(f"已為 {coin_name} 送出再平衡訂單。")

        except Exception as e:
            logger.error(f"執行 {coin_name} 的再平衡訂單時發生錯誤: {e}")
    
    def check_allocation(self):
        ratio = self.spot_perp_repartition()
        lower_bound = self.spot_allocation_pct - self.rebalance_threshold
        upper_bound = self.spot_allocation_pct + self.rebalance_threshold
        
        if ratio < lower_bound:
            spot_value = self._get_total_spot_account_value()
            perp_value = self.perp_user_state
            amount_to_transfer = (perp_value * self.spot_allocation_pct - spot_value * self.perp_allocation_pct) / 1.0
            logger.info(f"資金分配不匹配: {ratio:.2f} (目標: {self.spot_allocation_pct:.2f})")
            logger.info(f"建議從永續合約轉帳至現貨: ${amount_to_transfer:.2f}")
            return False
        elif ratio > upper_bound:
            spot_value = self._get_total_spot_account_value()
            perp_value = self.perp_user_state
            amount_to_transfer = (spot_value * self.perp_allocation_pct - perp_value * self.spot_allocation_pct) / 1.0
            logger.info(f"資金分配不匹配: {ratio:.2f} (目標: {self.spot_allocation_pct:.2f})")
            logger.info(f"建議從現貨轉帳至永續合約: ${amount_to_transfer:.2f}")
            return False
        return True
    
    def display_position_info(self):
        """Display detailed information about tracked coins and positions."""
        logger.info(f"\n{Colors.BOLD}追蹤幣種資訊:{Colors.RESET}")
        for coin_name, coin_info in self.coins.items():
            if coin_name == "USDC":
                continue
                
            logger.info(f"\n{Colors.BOLD}{Colors.YELLOW}{coin_name} 市場:{Colors.RESET}")
            
            is_delta_neutral, perp_size, spot_size, diff_percentage = self.has_delta_neutral_position(coin_name)
            
            status_color = Colors.GREEN if is_delta_neutral else Colors.RED
            status_text = "✅ Delta 中性" if is_delta_neutral else "❌ 非 Delta 中性"
            logger.info(f"  Delta 狀態: {status_color}{status_text}{Colors.RESET}")
            
            if perp_size != 0 or spot_size != 0:
                logger.info(f"    永續合約規模: {Colors.BLUE}{perp_size:.4f}{Colors.RESET}")
                logger.info(f"    現貨規模: {Colors.GREEN}{spot_size:.4f}{Colors.RESET}")
                diff_color = Colors.GREEN if diff_percentage < 5 else Colors.YELLOW if diff_percentage < 10 else Colors.RED
                logger.info(f"    差異: {diff_color}{diff_percentage:.2f}%{Colors.RESET}")
            
            if coin_info.perp:
                logger.info(f"    {Colors.BOLD}永續合約市場:{Colors.RESET}")
                logger.info(f"      指數: {coin_info.perp.index}")
                logger.info(f"      規模小數位數: {coin_info.perp.sz_decimals}")
                logger.info(f"      最大槓桿: {coin_info.perp.max_leverage}x")
                logger.info(f"      價格跳動單位: {coin_info.perp.tick_size}")
                
                if coin_info.perp.funding_rate is not None:
                    logger.info(f"      當前資金費率: {Colors.GREEN}{coin_info.perp.funding_rate:.8f}{Colors.RESET}")
                    
                    # Color funding rate based on value
                    rate_color = Colors.RED
                    if coin_info.perp.yearly_funding_rate >= 20:
                        rate_color = Colors.GREEN + Colors.BOLD
                    elif coin_info.perp.yearly_funding_rate >= 10:
                        rate_color = Colors.GREEN
                    elif coin_info.perp.yearly_funding_rate >= 5:
                        rate_color = Colors.YELLOW
                        
                    logger.info(f"      年化資金費率: {rate_color}{coin_info.perp.yearly_funding_rate:.4f}%{Colors.RESET}")
                
                if coin_info.perp.position:
                    pos = coin_info.perp.position
                    logger.info(f"      部位: {Colors.BLUE}{pos['size']:.4f}{Colors.RESET} @ ${Colors.YELLOW}{pos['entry_price']:.2f}{Colors.RESET}")
                    logger.info(f"      部位價值: ${Colors.GREEN}{pos['position_value']:.2f}{Colors.RESET}")
                    
                    # Color PnL based on profit/loss
                    pnl_color = Colors.GREEN if pos['unrealized_pnl'] > 0 else Colors.RED
                    logger.info(f"      未實現損益: {pnl_color}${pos['unrealized_pnl']:.2f}{Colors.RESET}")
                    
                    logger.info(f"      槓桿: {Colors.YELLOW}{pos['leverage']}x{Colors.RESET}")
                    logger.info(f"      強平價格: ${Colors.RED}{pos['liquidation_price']:.2f}{Colors.RESET}")
                    logger.info(f"      累計資金費用: {pos['cum_funding']}")
                else:
                    logger.info(f"      部位: {Colors.RED}無{Colors.RESET}")
            
            if coin_info.spot:
                logger.info(f"    {Colors.BOLD}現貨市場:{Colors.RESET}")
                logger.info(f"      名稱: {coin_info.spot.name} ({coin_info.spot.full_name})")
                logger.info(f"      代幣 ID: {coin_info.spot.token_id}")
                logger.info(f"      指數: {coin_info.spot.index}")
                logger.info(f"      規模小數位數: {coin_info.spot.sz_decimals}")
                logger.info(f"      Wei 小數位數: {coin_info.spot.wei_decimals}")
                logger.info(f"      價格跳動單位: {coin_info.spot.tick_size}")
                if coin_info.spot.position:
                    pos = coin_info.spot.position
                    logger.info(f"      餘額: {Colors.GREEN}{pos['total']:.4f}{Colors.RESET}")
                    logger.info(f"      凍結中: {Colors.YELLOW}{pos['hold']:.4f}{Colors.RESET}")
                    logger.info(f"      入場價值: ${Colors.GREEN}{pos['entry_ntl']:.2f}{Colors.RESET}")
                else:
                    logger.info(f"      部位: {Colors.RED}無{Colors.RESET}")
        
        ratio = self.spot_perp_repartition()
        ratio_color = Colors.GREEN if 0.665 <= ratio <= 0.735 else Colors.YELLOW if 0.6 <= ratio <= 0.8 else Colors.RED
        logger.info(f"現貨/永續合約分配比例: {ratio_color}{ratio:.4f}{Colors.RESET} (目標: {Colors.GREEN}0.7{Colors.RESET})")
        
        allocation_ok = self.check_allocation()
        if allocation_ok == False:
            logger.info(f"{Colors.RED}投資組合分配未在目標比例內 (70% 現貨 / 30% 永續合約){Colors.RESET}")
        
        # Show the best funding rate coin (but don't try to create a position here)
        best_coin = self.get_best_yearly_funding_rate()
        if best_coin:
            rate_color = Colors.RED
            rate = self.coins[best_coin].perp.yearly_funding_rate
            if rate >= 20:
                rate_color = Colors.GREEN + Colors.BOLD
            elif rate >= 10:
                rate_color = Colors.GREEN
            elif rate >= self.funding_open_threshold_pct:
                rate_color = Colors.YELLOW
                
            logger.info(f"最佳資金費率幣種: {Colors.YELLOW}{best_coin}{Colors.RESET}，費率為 {rate_color}{rate:.4f}%{Colors.RESET}")

    async def check_hourly_funding_rates(self):
        """
        Legacy hourly funding check that respects configured replace thresholds.
        """
        try:
            # Get current time
            now = time.localtime()
            
            # Only run this function at 10 minutes before the hour (e.g., 8:50, 9:50, etc.)
            if now.tm_min != self.funding_check_minute:
                return
                
            minutes_before = (60 - self.funding_check_minute) % 60
            if minutes_before == 0:
                timing_desc = "整點檢查"
            else:
                timing_desc = f"整點前 {minutes_before} 分鐘"

            logger.info(f"\n{Colors.BOLD}正在執行每小時資金費率檢查 ({timing_desc}){Colors.RESET}")
            
            # Get current funding rates
            from test_market_data import check_funding_rates, calculate_yearly_funding_rates
            
            funding_rates = await check_funding_rates()
            yearly_rates = calculate_yearly_funding_rates(funding_rates, self.tracked_coins)
            
            # Update funding rates in our coin data structure
            for coin_name, rate in funding_rates.items():
                if coin_name in self.coins and self.coins[coin_name].perp:
                    self.coins[coin_name].perp.funding_rate = float(rate)
            
            for coin_name, rate in yearly_rates.items():
                if coin_name in self.coins and self.coins[coin_name].perp:
                    self.coins[coin_name].perp.yearly_funding_rate = rate
                    rate_color = Colors.RED
                    if rate >= 20:
                        rate_color = Colors.GREEN + Colors.BOLD
                    elif rate >= 10:
                        rate_color = Colors.GREEN
                    elif rate >= 5:
                        rate_color = Colors.YELLOW
                    logger.info(f"已更新 {Colors.YELLOW}{coin_name}{Colors.RESET} 的年化資金費率: {rate_color}{rate:.4f}%{Colors.RESET}")
            
            # Refresh user state to get latest positions
            try:
                self.user_state = self.info.user_state(self.address)
                self.spot_user_state = self.info.spot_user_state(self.address)
                
                # Update perp positions
                for position in self.user_state.get("assetPositions", []):
                    if position["type"] == "oneWay" and "position" in position:
                        pos = position["position"]
                        coin_name = pos["coin"]
                        if coin_name in self.coins and self.coins[coin_name].perp:
                            self.coins[coin_name].perp.position = {
                                "size": float(pos["szi"]),
                                "entry_price": float(pos["entryPx"]),
                                "position_value": float(pos["positionValue"]),
                                "unrealized_pnl": float(pos["unrealizedPnl"]),
                                "leverage": pos["leverage"]["value"],
                                "liquidation_price": float(pos["liquidationPx"]),
                                "cum_funding": pos["cumFunding"]["allTime"]
                            }
                
                # Update spot positions
                for balance in self.spot_user_state.get("balances", []):
                    if float(balance["total"]) > 0:
                        coin_name = balance["coin"]
                        
                        if coin_name == "UBTC":
                            coin_name = "BTC"
                        elif coin_name == "UETH":
                            coin_name = "ETH"
                        
                        if coin_name in self.coins and self.coins[coin_name].spot:
                            self.coins[coin_name].spot.position = {
                                "total": float(balance["total"]),
                                "hold": float(balance["hold"]),
                                "entry_ntl": float(balance["entryNtl"])
                            }
                            
                logger.info(f"{Colors.GREEN}成功刷新部位資料{Colors.RESET}")

                # --- Log Account Snapshot ---
                try:
                    # Re-calculate account values after state refresh
                    self.margin_summary = self.user_state["marginSummary"]
                    perp_account_value = float(self.user_state['crossMarginSummary'].get('accountValue', 0))
                    spot_account_value = self._get_total_spot_account_value()
                    total_account_value = spot_account_value + perp_account_value
                    total_margin_used = float(self.margin_summary["totalMarginUsed"])

                    snapshot_data = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "account_value": total_account_value,
                        "spot_account_value": spot_account_value,
                        "perp_account_value": perp_account_value,
                        "total_margin_used": total_margin_used,
                    }
                    db_logger.log_account_snapshot(snapshot_data)
                except Exception as e:
                    logger.error(f"{Colors.RED}紀錄帳戶快照失敗: {e}{Colors.RESET}", exc_info=True)
                # --- End of Snapshot ---
                
                # Display detailed position information in hourly check
                self.display_position_info()
                
            except Exception as e:
                logger.error(f"{Colors.RED}刷新部位資料時發生錯誤: {e}{Colors.RESET}")
            
            # Find current active delta neutral position
            current_position_coin = None
            for coin_name in self.tracked_coins:
                if coin_name == "USDC":
                    continue
                    
                is_delta_neutral, perp_size, spot_size, _ = self.has_delta_neutral_position(coin_name)
                if is_delta_neutral:
                    current_position_coin = coin_name
                    logger.info(f"{Colors.GREEN}找到活躍的 Delta 中性部位於 {Colors.YELLOW}{coin_name}{Colors.GREEN}，永續合約規模 {Colors.BLUE}{perp_size}{Colors.GREEN}，現貨規模 {Colors.GREEN}{spot_size}{Colors.RESET}")
                    break
            
            if not current_position_coin:
                logger.info(f"{Colors.YELLOW}未找到活躍的 Delta 中性部位。{Colors.RESET}")
                # Find the best coin and create a new position if its rate meets the configured threshold
                best_coin = self.get_best_yearly_funding_rate()
                if best_coin and self.coins[best_coin].perp.yearly_funding_rate >= self.funding_open_threshold_pct:
                    logger.info(f"{Colors.GREEN}正在為 {Colors.YELLOW}{best_coin}{Colors.GREEN} 建立新的 Delta 中性部位，費率為 {Colors.GREEN}{self.coins[best_coin].perp.yearly_funding_rate:.4f}%{Colors.RESET}")
                    await self.create_delta_position(best_coin)
                else:
                    logger.info(
                        f"{Colors.YELLOW}找不到資金費率 >= {self.funding_open_threshold_pct:.2f}% 的幣種。等待下次檢查。{Colors.RESET}"
                    )
                    return
            
            # Check if current position has yield below the replace threshold
            current_yield = self.coins[current_position_coin].perp.yearly_funding_rate
            rate_color = Colors.RED
            if current_yield >= 20:
                rate_color = Colors.GREEN + Colors.BOLD
            elif current_yield >= 10:
                rate_color = Colors.GREEN
            elif current_yield >= 5:
                rate_color = Colors.YELLOW
                
            logger.info(f"當前 Delta 中性部位: {Colors.YELLOW}{current_position_coin}{Colors.RESET}，收益率: {rate_color}{current_yield:.4f}%{Colors.RESET}")
            
            if current_yield is None or current_yield < self.funding_replace_threshold_pct:
                logger.info(
                    f"{Colors.YELLOW}{current_position_coin} 的當前收益率低於 {self.funding_replace_threshold_pct:.2f}% (或為空)。正在尋找更好的選擇...{Colors.RESET}"
                )
                
                # Find coin with highest funding rate
                best_coin = self.get_best_yearly_funding_rate()
                
                if not best_coin or (
                    best_coin
                    and self.coins[best_coin].perp.yearly_funding_rate < self.funding_open_threshold_pct
                ):
                    logger.info(
                        f"{Colors.YELLOW}找不到資金費率 >= {self.funding_open_threshold_pct:.2f}% 的幣種。暫時維持當前部位。{Colors.RESET}"
                    )
                    return
                
                # Make sure the best coin is different from current coin and has better rate
                if best_coin == current_position_coin:
                    logger.info(
                        f"{Colors.YELLOW}{current_position_coin} 仍然是最佳資金費率幣種，但其費率低於 {self.funding_replace_threshold_pct:.2f}%。{Colors.RESET}"
                    )
                    return
                    
                best_rate = self.coins[best_coin].perp.yearly_funding_rate
                best_rate_color = Colors.RED
                if best_rate >= 20:
                    best_rate_color = Colors.GREEN + Colors.BOLD
                elif best_rate >= 10:
                    best_rate_color = Colors.GREEN
                elif best_rate >= 5:
                    best_rate_color = Colors.YELLOW
                    
                logger.info(f"{Colors.GREEN}找到更好的幣種: {Colors.YELLOW}{best_coin}{Colors.GREEN}，收益率: {best_rate_color}{best_rate:.4f}%{Colors.RESET}")
                
                # Close current position and open new one
                logger.info(f"{Colors.YELLOW}正在關閉 {current_position_coin} 的當前部位...{Colors.RESET}")
                close_result = await self.close_delta_position(current_position_coin)
                
                if close_result:
                    logger.info(f"{Colors.GREEN}已成功啟動關閉 {current_position_coin} 部位的程序{Colors.RESET}")
                    # Wait for closing orders to be processed
                    close_pending = True
                    max_wait = 180  # 3 minutes max wait
                    start_time = time.time()
                    
                    while close_pending and time.time() - start_time < max_wait:
                        logger.info(f"{Colors.YELLOW}正在等待關倉訂單完成...{Colors.RESET}")
                        # Check pending orders
                        await self.check_pending_orders()
                        
                        # Check if any pending orders are for the current coin and are closing
                        close_pending = any(order.coin_name == current_position_coin and order.is_closing_position for order in self.pending_orders)
                        
                        if close_pending:
                            await asyncio.sleep(10)  # Wait 10 seconds before checking again
                    
                    if close_pending:
                        logger.warning(f"{Colors.YELLOW}關閉 {current_position_coin} 的部位耗時過長。將繼續開立新部位。{Colors.RESET}")
                    
                    logger.info(f"{Colors.GREEN}正在為 {best_coin} 建立新的 Delta 中性部位...{Colors.RESET}")
                    create_result = await self.create_delta_position(best_coin)
                    
                    if create_result:
                        logger.info(f"{Colors.GREEN}已成功啟動建立 {best_coin} 新 Delta 中性部位的程序{Colors.RESET}")
                    else:
                        logger.error(f"{Colors.RED}建立 {best_coin} 新 Delta 中性部位失敗{Colors.RESET}")
                else:
                    logger.error(f"{Colors.RED}關閉 {current_position_coin} 部位失敗{Colors.RESET}")
            else:
                logger.info(
                    f"{Colors.GREEN}{current_position_coin} 的當前收益率高於 {self.funding_replace_threshold_pct:.2f}%。無需操作。{Colors.RESET}"
                )
                
        except Exception as e:
            logger.error(f"{Colors.RED}檢查每小時資金費率時發生錯誤: {e}{Colors.RESET}", exc_info=True)
    
    async def stop(self):
        """Stop the bot's execution loop."""
        if not self._is_running:
            logger.info("機器人未在運行")
            return
            
        logger.info("正在停止 Delta 機器人...")
        self._is_running = False

    async def start(self):
        """Start the bot's execution loop."""
        if self._is_running:
            logger.info("機器人已在運行中")
            return

        self._is_running = True
        logger.info("正在啟動 Delta 機器人...")

        logger.info(f"{Colors.BOLD}帳戶摘要:{Colors.RESET}")
        logger.info(f"  總價值: ${Colors.GREEN}{self.total_raw_usd:.2f}{Colors.RESET}")
        logger.info(f"  帳戶價值: ${Colors.GREEN}{self.account_value:.2f}{Colors.RESET}")
        logger.info(f"  已用保證金: ${Colors.YELLOW}{self.total_margin_used:.2f}{Colors.RESET}")
        logger.info(f"  永續合約帳戶價值: ${Colors.BLUE}{self.perp_user_state:.2f}{Colors.RESET}")
        logger.info(f"  現貨 USDC 價值: ${Colors.GREEN}{self._get_spot_account_USDC():.2f}{Colors.RESET}")
        logger.info(f"  現貨帳戶價值: ${Colors.BLUE}{self._get_total_spot_account_value():.2f}{Colors.RESET}")

        await self._refresh_funding_if_due(force=True)
        await self._refresh_positions_if_due(force=True)

        while self._is_running:
            try:
                await self._run_state_machine()
                await asyncio.sleep(self.heartbeat_sec)
            except KeyboardInterrupt:
                logger.info(f"{Colors.YELLOW}在主迴圈中偵測到鍵盤中斷{Colors.RESET}")
                break
            except Exception as e:
                logger.error(f"{Colors.RED}主迴圈發生錯誤: {e}{Colors.RESET}", exc_info=True)
                await asyncio.sleep(max(self.heartbeat_sec, 5))

    async def _check_for_new_position_opportunities(self):
        """Checks if there's a good opportunity to open a new delta-neutral position."""
        # First, check if we already have any active position. If so, do nothing.
        for coin in self.coins:
            if self.has_delta_neutral_position(coin)[0]:
                logger.debug(f"已持有 {coin} 的部位，跳過尋找新機會。")
                return

        # If no active positions, find the best coin to open one.
        best_coin = self.get_best_yearly_funding_rate()
        if best_coin:
            rate = self.coins[best_coin].perp.yearly_funding_rate
            rate_color = Colors.RED
            if rate >= 20:
                rate_color = Colors.GREEN + Colors.BOLD
            elif rate >= 10:
                rate_color = Colors.GREEN
            elif rate >= 5:
                rate_color = Colors.YELLOW
                
            logger.info(f"{Colors.YELLOW}新部位的最佳資金費率幣種: {Colors.YELLOW}{best_coin}，費率為 {rate_color}{rate:.4f}%{Colors.RESET}")
            
            if rate >= self.funding_open_threshold_pct:
                logger.info(f"{Colors.GREEN}正在為 {Colors.YELLOW}{best_coin}{Colors.GREEN} 建立 Delta 中性部位...{Colors.RESET}")
                result = await self.execute_best_delta_strategy()
                if result:
                    logger.info(f"{Colors.GREEN}成功為 {Colors.YELLOW}{best_coin}{Colors.GREEN} 建立 Delta 中性部位{Colors.RESET}")
                else:
                    logger.warning(f"{Colors.RED}為 {Colors.YELLOW}{best_coin}{Colors.RED} 建立 Delta 中性部位失敗{Colors.RESET}")
            else:
                logger.info(
                    f"{Colors.YELLOW}最佳資金費率 ({rate:.4f}%) 低於 {self.funding_open_threshold_pct:.2f}% 的門檻，不建立部位{Colors.RESET}"
                )

def setup_signal_handlers(delta_instance):
    """Set up signal handlers for graceful shutdown."""
    import signal
    import sys
    
    # Global flag to indicate shutdown is in progress
    shutdown_in_progress = False
    
    def signal_handler(sig, frame):
        nonlocal shutdown_in_progress
        
        if shutdown_in_progress:
            logger.info("已請求強制退出。立即退出。")
            sys.exit(1)
            
        shutdown_in_progress = True
        logger.info(f"收到信號 {sig}，正在關閉...")
        logger.info("再次按下 Ctrl+C 可強制立即退出")
        
        # Don't exit here, just set the flag for the main loop to check
        # The main loop handles the graceful shutdown
        # This causes KeyboardInterrupt to be raised in the main event loop
        raise KeyboardInterrupt()
    
    signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Handle termination signal
    
    logger.info("已設定信號處理器以實現優雅關閉")


async def main():
    delta = None
    try:
        delta = Delta("config.json")
        await delta.initialize()
        setup_signal_handlers(delta)
        await delta.start()
    except KeyboardInterrupt:
        logger.info("偵測到鍵盤中斷，正在關閉部位...")
        if delta:
            try:
                # Make sure to close positions before exiting
                logger.info("正在嘗試關閉所有部位...")
                await delta.close_all_delta_positions()
                logger.info("部位關閉完成")
                await delta.exit_program(close_positions=False)  # Already closed positions above
            except Exception as e:
                logger.error(f"關閉過程中發生錯誤: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"運行 Delta 時發生錯誤: {e}", exc_info=True)
        if delta:
            try:
                await delta.exit_program(close_positions=True)
            except Exception as shutdown_e:
                logger.error(f"關閉過程中發生錯誤: {shutdown_e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This will catch the KeyboardInterrupt at the top level after signal handling
        logger.info("因鍵盤中斷而退出")
    except SystemExit:
        # Handle the SystemExit exception from sys.exit() in the signal handler
        pass
    except Exception as e:
        logger.error(f"致命錯誤: {e}", exc_info=True)
